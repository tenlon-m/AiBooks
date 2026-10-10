"""AB稿/ABC稿多AI接力纠错服务 - 多AI接力纠错+评估+采纳."""
from __future__ import annotations


import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import AiGateway, get_gateway
from src.api.schemas.proofread_schema import (
    EvaluateResultDto,
    ProofreadDraftDto,
    ProofreadResultDto,
)
from src.config.settings import get_config
from src.db.models import Chapter, ChapterVersion, ProofreadDraft
from src.db.session import release_write_lock
from src.utils.logger import get_logger

_PROOFREAD_STAGE_LABEL = {
    "A": "A稿生成",
    "B": "B稿纠错",
    "C": "C稿纠错",
}

_EVALUATION_CRITERIA = (
    "情节连贯性、人物一致性、文笔流畅度、风格统一性、"
    "错别字与语病、大纲契合度，每项0-100分"
)


class ProofreadService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway: AiGateway = get_gateway()
        self.config = get_config()

    async def _get_chapter(self, chapter_id: str) -> Chapter:
        chapter = await self.session.get(Chapter, chapter_id)
        if chapter is None:
            raise ValueError(f"章节不存在: {chapter_id}")
        return chapter

    async def _call_proofread(
        self,
        input_content: str,
        proofread_stage: str,
        previous_draft: str,
        source_id: str,
        project_id: str | None,
    ) -> str:
        params = {
            "input_content": input_content,
            "proofread_stage": proofread_stage,
            "previous_draft": previous_draft,
        }
        timeout = self.config.proofread_timeout_seconds
        result = await self.gateway.call(
            module="writing",
            scene="proofread",
            params=params,
            project_id=project_id,
            source_id=source_id,
            timeout_seconds=timeout,
        )
        content = result.get("content", "")
        min_len = self.config.min_ai_content_length
        if len(content) < min_len:
            self.logger.warning(
                f"{_PROOFREAD_STAGE_LABEL.get(proofread_stage, proofread_stage)}"
                f"内容过短({len(content)}字)，重试一次"
            )
            retry_result = await self.gateway.call(
                module="writing",
                scene="proofread",
                params=params,
                project_id=project_id,
                source_id=source_id,
                timeout_seconds=timeout,
            )
            retry_content = retry_result.get("content", "")
            if len(retry_content) > len(content):
                content = retry_content
        return content

    async def _save_draft(
        self,
        chapter_id: str,
        draft_stage: str,
        ai_source_id: str,
        content: str,
    ) -> ProofreadDraft:
        now = datetime.now(timezone.utc)
        version = ChapterVersion(
            version_id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            version_type="auto",
            name=f"接力纠错{draft_stage}稿",
            content=content,
            word_count=len(content),
            created_at=now,
        )
        self.session.add(version)
        await self.session.flush()
        draft = ProofreadDraft(
            draft_id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            draft_stage=draft_stage,
            ai_source_id=ai_source_id,
            content=content,
            version_id=version.version_id,
            adopt_status="待采纳",
            created_at=now,
        )
        self.session.add(draft)
        await self.session.flush()
        return draft

    @staticmethod
    def _to_dto(draft: ProofreadDraft) -> ProofreadDraftDto:
        return ProofreadDraftDto(
            draft_id=draft.draft_id,
            chapter_id=draft.chapter_id,
            draft_stage=draft.draft_stage,
            ai_source_id=draft.ai_source_id,
            content=draft.content,
            score=draft.score,
            adopt_status=draft.adopt_status,
            created_at=draft.created_at,
        )

    async def _run_stage(
        self,
        chapter_id: str,
        stage: str,
        source_id: str,
        input_content: str,
        previous_draft: str,
        project_id: str | None,
    ) -> ProofreadDraft:
        content = await self._call_proofread(
            input_content=input_content,
            proofread_stage=stage,
            previous_draft=previous_draft,
            source_id=source_id,
            project_id=project_id,
        )
        draft = await self._save_draft(chapter_id, stage, source_id, content)
        await release_write_lock(self.session)
        return draft

    async def proofread_ab(
        self,
        chapter_id: str,
        source_a: str,
        source_b: str,
    ) -> ProofreadResultDto:
        chapter = await self._get_chapter(chapter_id)
        project_id = chapter.project_id
        original = chapter.content or ""
        drafts: list[ProofreadDraft] = []
        try:
            draft_a = await self._run_stage(
                chapter_id, "A", source_a, original, "", project_id,
            )
            drafts.append(draft_a)

            draft_b = await self._run_stage(
                chapter_id, "B", source_b, draft_a.content, draft_a.content, project_id,
            )
            drafts.append(draft_b)
        except Exception as e:
            self.logger.error(
                f"AB接力纠错第{len(drafts) + 1}步失败，"
                f"已保留前序稿件{len(drafts)}份，可重试或更换AI源: {e}"
            )
            if not drafts:
                raise
            return ProofreadResultDto(
                chapter_id=chapter_id,
                drafts=[self._to_dto(d) for d in drafts],
            )
        return ProofreadResultDto(
            chapter_id=chapter_id,
            drafts=[self._to_dto(d) for d in drafts],
        )

    async def proofread_abc(
        self,
        chapter_id: str,
        source_a: str,
        source_b: str,
        source_c: str,
        source_eval: str,
    ) -> ProofreadResultDto:
        chapter = await self._get_chapter(chapter_id)
        project_id = chapter.project_id
        original = chapter.content or ""
        drafts: list[ProofreadDraft] = []
        try:
            draft_a = await self._run_stage(
                chapter_id, "A", source_a, original, "", project_id,
            )
            drafts.append(draft_a)

            draft_b = await self._run_stage(
                chapter_id, "B", source_b, draft_a.content, draft_a.content, project_id,
            )
            drafts.append(draft_b)

            draft_c = await self._run_stage(
                chapter_id, "C", source_c, draft_b.content, draft_b.content, project_id,
            )
            drafts.append(draft_c)

            await self.evaluate(draft_c.draft_id, source_id=source_eval)
        except Exception as e:
            self.logger.error(
                f"ABC接力纠错第{len(drafts) + 1}步失败，"
                f"已保留前序稿件{len(drafts)}份，可重试或更换AI源: {e}"
            )
            if not drafts:
                raise
            return ProofreadResultDto(
                chapter_id=chapter_id,
                drafts=[self._to_dto(d) for d in drafts],
            )
        return ProofreadResultDto(
            chapter_id=chapter_id,
            drafts=[self._to_dto(d) for d in drafts],
        )

    async def evaluate(
        self,
        draft_id: str,
        source_id: str | None = None,
    ) -> EvaluateResultDto:
        draft = await self.session.get(ProofreadDraft, draft_id)
        if draft is None:
            raise ValueError(f"稿件不存在: {draft_id}")
        params = {
            "content": draft.content,
            "evaluation_criteria": _EVALUATION_CRITERIA,
        }
        timeout = self.config.evaluate_timeout_seconds
        call_kwargs: dict = {
            "module": "writing",
            "scene": "evaluate",
            "params": params,
        }
        if source_id:
            call_kwargs["source_id"] = source_id
        result = await self.gateway.call_and_parse(
            **call_kwargs,
            timeout_seconds=timeout,
        )
        parsed = result.get("parsed", {})
        score = float(parsed.get("score", 0))
        dimensions = parsed.get("dimensions", {})
        summary = parsed.get("summary", "")
        draft.score = score
        await self.session.flush()
        return EvaluateResultDto(
            draft_id=draft_id,
            score=score,
            dimensions=dimensions,
            summary=summary,
        )

    async def adopt_draft(self, draft_id: str) -> dict:
        draft = await self.session.get(ProofreadDraft, draft_id)
        if draft is None:
            raise ValueError(f"稿件不存在: {draft_id}")
        chapter = await self.session.get(Chapter, draft.chapter_id)
        if chapter is None:
            raise ValueError(f"章节不存在: {draft.chapter_id}")
        chapter.content = draft.content
        chapter.word_count = len(draft.content)
        chapter.last_modified_at = datetime.now(timezone.utc)
        draft.adopt_status = "已采纳"
        await self.session.flush()
        return {
            "draft_id": draft_id,
            "chapter_id": draft.chapter_id,
            "adopt_status": "已采纳",
        }

    async def list_drafts(self, chapter_id: str) -> list[ProofreadDraftDto]:
        result = await self.session.execute(
            select(ProofreadDraft)
            .where(ProofreadDraft.chapter_id == chapter_id)
            .order_by(ProofreadDraft.created_at)
        )
        return [self._to_dto(d) for d in result.scalars().all()]