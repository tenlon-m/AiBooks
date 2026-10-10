"""章节摘要自动生成服务 - SSE逐章生成，支持批量可暂停续写，UPSERT至chapter_summaries."""
from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.chapter_summary_schema import (
    ChapterSummaryDto,
    ChapterSummaryStreamChunk,
)
from src.config.settings import get_config
from src.db.models import Chapter, ChapterSummary, Project
from src.db.session import release_write_lock
from src.utils.logger import get_logger


class ChapterSummaryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def _upsert_summary(self, chapter_id: str, summary: str) -> ChapterSummary:
        entity = await self.session.get(ChapterSummary, chapter_id)
        if entity:
            entity.summary = summary
            entity.word_count = len(summary)
        else:
            entity = ChapterSummary(
                chapter_id=chapter_id,
                summary=summary,
                word_count=len(summary),
            )
            self.session.add(entity)
        await self.session.commit()
        return entity

    async def generate(
        self, chapter_id: str
    ) -> AsyncGenerator[ChapterSummaryStreamChunk, None]:
        chapter = await self.session.get(Chapter, chapter_id)
        if not chapter:
            yield ChapterSummaryStreamChunk(
                type="done", chapter_id=chapter_id, message="章节不存在"
            )
            return
        content = chapter.content or ""
        if len(content) < get_config().min_ai_content_length:
            yield ChapterSummaryStreamChunk(
                type="done",
                chapter_id=chapter_id,
                message=f"章节内容不足{get_config().min_ai_content_length}字",
            )
            return

        yield ChapterSummaryStreamChunk(
            type="progress",
            chapter_id=chapter_id,
            message="正在生成章节摘要...",
        )
        await release_write_lock(self.session)
        try:
            self.logger.info(f"AI生成章节摘要 chapter_id={chapter_id} chapter_no={chapter.chapter_no}")
            result = await self.gateway.call_and_parse(
                module="summary",
                scene="chapter",
                params={
                    "chapter_no": chapter.chapter_no,
                    "chapter_title": chapter.title,
                    "chapter_content": content,
                },
                project_id=chapter.project_id,
                timeout_seconds=get_config().chapter_summary_timeout_seconds,
            )
            parsed = result.get("parsed", {})
            summary = parsed.get("summary", "").strip()
            if not summary:
                summary = result.get("content", "").strip()
            min_len = get_config().min_ai_content_length
            if len(summary) < min_len:
                yield ChapterSummaryStreamChunk(
                    type="done",
                    chapter_id=chapter_id,
                    message=f"摘要不足{min_len}字",
                )
                return
            entity = await self._upsert_summary(chapter_id, summary)
            step = max(20, len(summary) // 10)
            for i in range(0, len(summary), step):
                yield ChapterSummaryStreamChunk(
                    type="chunk",
                    chapter_id=chapter_id,
                    summary=summary[i : i + step],
                )
            yield ChapterSummaryStreamChunk(
                type="done",
                chapter_id=chapter_id,
                summary=summary,
                message=f"摘要已生成，{entity.word_count}字",
            )
        except Exception as e:
            yield ChapterSummaryStreamChunk(
                type="done",
                chapter_id=chapter_id,
                message=f"AI生成异常: {e}",
            )

    async def batch_generate(
        self, project_id: str, chapter_ids: list[str]
    ) -> AsyncGenerator[ChapterSummaryStreamChunk, None]:
        project = await self.session.get(Project, project_id)
        if not project:
            yield ChapterSummaryStreamChunk(type="done", message="项目不存在")
            return
        total = len(chapter_ids)
        success_count = 0
        skipped_count = 0
        for idx, cid in enumerate(chapter_ids, 1):
            chapter = await self.session.get(Chapter, cid)
            if not chapter:
                skipped_count += 1
                yield ChapterSummaryStreamChunk(
                    type="skipped",
                    chapter_id=cid,
                    message=f"第 {idx}/{total} 章不存在，已跳过",
                )
                continue
            content = chapter.content or ""
            if len(content) < get_config().min_ai_content_length:
                skipped_count += 1
                yield ChapterSummaryStreamChunk(
                    type="skipped",
                    chapter_id=cid,
                    message=f"第 {idx}/{total} 章正文不足{get_config().min_ai_content_length}字，已跳过（请先撰写章节正文）",
                )
                continue
            yield ChapterSummaryStreamChunk(
                type="progress",
                chapter_id=cid,
                message=f"正在生成第 {idx}/{total} 章摘要...",
            )
            has_summary = False
            async for chunk in self.generate(cid):
                if chunk.type == "done" and chunk.summary:
                    has_summary = True
                yield chunk
            if has_summary:
                success_count += 1
            else:
                skipped_count += 1
        yield ChapterSummaryStreamChunk(
            type="done",
            message=f"批量摘要生成完成：成功 {success_count} 章，跳过 {skipped_count} 章",
        )

    async def get_summary(self, chapter_id: str) -> ChapterSummaryDto | None:
        entity = await self.session.get(ChapterSummary, chapter_id)
        if not entity:
            return None
        return ChapterSummaryDto(
            chapter_id=entity.chapter_id,
            summary=entity.summary,
            word_count=entity.word_count,
        )