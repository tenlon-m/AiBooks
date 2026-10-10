"""批量查找替换服务 - 全书/范围扫描、预览、事务内替换+版本快照."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.batch_replace_schema import (
    BatchReplaceExecuteResponse,
    BatchReplacePreviewRequest,
    BatchReplacePreviewResponse,
    MatchPreviewItem,
)
from src.config.settings import get_config
from src.db.models import Chapter, Project
from src.services._chapter_guard import (
    assert_chapters_not_locked,
    create_auto_version_snapshot,
)
from src.utils.logger import get_logger

PREVIEW_TTL_SECONDS = 600
_preview_store: dict[str, dict] = {}

CONTEXT_PADDING = 30


class BatchReplaceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    async def preview(self, req: BatchReplacePreviewRequest) -> BatchReplacePreviewResponse:
        project = await self.session.get(Project, req.project_id)
        if not project:
            raise ValueError("项目不存在")
        if not req.find:
            raise ValueError("查找内容不能为空")

        if req.mode == "regex":
            try:
                flags = 0 if req.case_sensitive else re.IGNORECASE
                pattern = re.compile(req.find, flags)
            except re.error as e:
                raise ValueError(f"正则表达式无效: {e}")
        else:
            pattern = None

        if req.scope == "chapters":
            if not req.chapter_ids:
                raise ValueError("scope=chapters 时必须指定 chapter_ids")
            ch_result = await self.session.execute(
                select(Chapter).where(
                    Chapter.project_id == req.project_id,
                    Chapter.chapter_id.in_(req.chapter_ids),
                ).order_by(Chapter.volume_no, Chapter.chapter_no)
            )
        else:
            ch_result = await self.session.execute(
                select(Chapter).where(
                    Chapter.project_id == req.project_id,
                ).order_by(Chapter.volume_no, Chapter.chapter_no)
            )
        chapters = list(ch_result.scalars().all())

        max_matches = get_config().batch_replace_max_matches
        matches: list[MatchPreviewItem] = []
        for ch in chapters:
            if not ch.content:
                continue
            paragraphs = ch.content.split("\n")
            for p_idx, para in enumerate(paragraphs):
                if not para:
                    continue
                for offset, match_text in self._scan_paragraph(
                    para, req, pattern
                ):
                    matches.append(MatchPreviewItem(
                        chapter_id=ch.chapter_id,
                        chapter_title=ch.title,
                        paragraph_index=p_idx,
                        offset=offset,
                        context=self._build_context(para, offset, len(match_text)),
                        match_text=match_text,
                    ))
                    if len(matches) >= max_matches:
                        break
                if len(matches) >= max_matches:
                    break
            if len(matches) >= max_matches:
                break

        truncated = len(matches) >= max_matches
        preview_id = str(uuid.uuid4())
        _preview_store[preview_id] = {
            "request": req.model_dump(),
            "matches": [m.model_dump() for m in matches],
            "created_at": datetime.now(timezone.utc),
        }

        return BatchReplacePreviewResponse(
            preview_id=preview_id,
            matches=matches,
            total=len(matches),
            truncated=truncated,
        )

    async def execute(
        self, preview_id: str, confirmed_indices: list[int]
    ) -> BatchReplaceExecuteResponse:
        record = _preview_store.get(preview_id)
        if not record:
            raise ValueError("预览不存在或已过期，请重新预览")
        req_dict = record["request"]
        matches_data: list[dict] = record["matches"]

        if confirmed_indices:
            selected = [matches_data[i] for i in confirmed_indices if 0 <= i < len(matches_data)]
        else:
            selected = matches_data
        if not selected:
            raise ValueError("无确认的匹配项可执行")

        affected_chapter_ids = list({m["chapter_id"] for m in selected})
        await assert_chapters_not_locked(self.session, affected_chapter_ids)

        find = req_dict["find"]
        replace = req_dict["replace"]
        mode = req_dict["mode"]
        case_sensitive = req_dict["case_sensitive"]

        if mode == "regex":
            try:
                flags = 0 if case_sensitive else re.IGNORECASE
                pattern = re.compile(find, flags)
            except re.error as e:
                raise ValueError(f"正则表达式无效: {e}")
        else:
            pattern = None

        chapter_ids = list({m["chapter_id"] for m in selected})
        ch_result = await self.session.execute(
            select(Chapter).where(Chapter.chapter_id.in_(chapter_ids))
        )
        chapter_map = {ch.chapter_id: ch for ch in ch_result.scalars().all()}

        replaced_count = 0
        now = datetime.now(timezone.utc)
        for ch_id in chapter_ids:
            chapter = chapter_map.get(ch_id)
            if not chapter or not chapter.content:
                continue
            new_content = self._apply_replace(
                chapter.content, find, replace, mode, case_sensitive, pattern
            )
            if new_content != chapter.content:
                await create_auto_version_snapshot(self.session, chapter)
                chapter.content = new_content
                chapter.word_count = len(new_content)
                chapter.modify_status = "modified"
                chapter.last_modified_at = now
                replaced_count += 1

        await self.session.commit()
        _preview_store.pop(preview_id, None)
        return BatchReplaceExecuteResponse(
            replaced_count=replaced_count,
            chapter_ids=chapter_ids,
        )

    @staticmethod
    def _scan_paragraph(
        para: str,
        req: BatchReplacePreviewRequest,
        pattern: re.Pattern | None,
    ) -> list[tuple[int, str]]:
        results: list[tuple[int, str]] = []
        if pattern is not None:
            for m in pattern.finditer(para):
                results.append((m.start(), m.group(0)))
        else:
            if req.case_sensitive:
                start = 0
                while True:
                    idx = para.find(req.find, start)
                    if idx == -1:
                        break
                    results.append((idx, req.find))
                    start = idx + len(req.find)
            else:
                lower_para = para.lower()
                lower_find = req.find.lower()
                start = 0
                while True:
                    idx = lower_para.find(lower_find, start)
                    if idx == -1:
                        break
                    results.append((idx, para[idx:idx + len(req.find)]))
                    start = idx + len(req.find)
        return results

    @staticmethod
    def _build_context(para: str, offset: int, match_len: int) -> str:
        start = max(0, offset - CONTEXT_PADDING)
        end = min(len(para), offset + match_len + CONTEXT_PADDING)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(para) else ""
        return f"{prefix}{para[start:end]}{suffix}"

    @staticmethod
    def _apply_replace(
        content: str,
        find: str,
        replace: str,
        mode: str,
        case_sensitive: bool,
        pattern: re.Pattern | None,
    ) -> str:
        if mode == "regex":
            return pattern.sub(replace, content)
        if case_sensitive:
            return content.replace(find, replace)
        return re.sub(re.escape(find), replace, content, flags=re.IGNORECASE)