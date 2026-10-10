"""批量提取/改写服务 - 按角色/地点提取章节片段，批量改写/扩写并流式回传进度."""
from __future__ import annotations

import json
import uuid
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import AiGateway, get_gateway
from src.api.schemas.batch_edit_schema import (
    BatchProgressEvent,
    ExtractItemDto,
    ExtractResultDto,
)
from src.config.settings import get_config
from src.db.models import BatchOperationRecord, Chapter
from src.db.session import release_write_lock
from src.utils.logger import get_logger

BATCH_LIMIT = 20


class BatchEditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def extract_by_character(
        self, project_id: str, character_name: str
    ) -> ExtractResultDto:
        return await self._extract(project_id, "角色", character_name)

    async def extract_by_place(
        self, project_id: str, place_name: str
    ) -> ExtractResultDto:
        return await self._extract(project_id, "地点", place_name)

    async def _extract(
        self, project_id: str, dimension: str, target_name: str
    ) -> ExtractResultDto:
        stmt = (
            select(Chapter)
            .where(
                Chapter.project_id == project_id,
                Chapter.content.like(f"%{target_name}%"),
            )
            .order_by(Chapter.volume_no, Chapter.chapter_no)
        )
        result = await self.session.execute(stmt)
        chapters = list(result.scalars().all())
        if not chapters:
            self.logger.info(
                f"提取{dimension}「{target_name}」无匹配章节，返回空结果"
            )
            return ExtractResultDto(
                dimension=dimension, target_name=target_name, items=[]
            )

        chapters_content = [
            {
                "chapter_no": ch.chapter_no,
                "title": ch.title,
                "content": ch.content or "",
            }
            for ch in chapters
        ]
        await release_write_lock(self.session)
        timeout = get_config().batch_extract_timeout_seconds
        ai_result = await self.gateway.call(
            module="analysis",
            scene="extract",
            params={
                "project_id": project_id,
                "dimension": dimension,
                "target_name": target_name,
                "chapters_content": chapters_content,
            },
            project_id=project_id,
            timeout_seconds=timeout,
        )
        content = ai_result.get("content", "")
        parsed = AiGateway._extract_json(content) or {}
        if not parsed:
            self.logger.warning(
                f"批量提取{dimension}「{target_name}」AI返回格式异常，未能解析提取结果: {content[:200]}"
            )
            return ExtractResultDto(
                dimension=dimension,
                target_name=target_name,
                items=[],
                message="AI返回格式异常，未能解析提取结果",
            )
        raw_items = parsed.get("results", [])
        items = [
            ExtractItemDto(
                chapter_no=int(item.get("chapter_no", 0)),
                excerpt=str(item.get("excerpt", "")),
            )
            for item in raw_items
        ]
        return ExtractResultDto(
            dimension=dimension, target_name=target_name, items=items
        )

    async def batch_rewrite(
        self, chapter_ids: list[str], instruction: str
    ) -> AsyncGenerator[BatchProgressEvent, None]:
        async for event in self._batch_process(chapter_ids, instruction, "改写"):
            yield event

    async def batch_expand(
        self, chapter_ids: list[str], instruction: str
    ) -> AsyncGenerator[BatchProgressEvent, None]:
        async for event in self._batch_process(chapter_ids, instruction, "扩写"):
            yield event

    async def _batch_process(
        self, chapter_ids: list[str], instruction: str, mode: str
    ) -> AsyncGenerator[BatchProgressEvent, None]:
        if not chapter_ids:
            yield BatchProgressEvent(
                type="error", message="章节ID列表不能为空"
            )
            return

        ch_result = await self.session.execute(
            select(Chapter)
            .where(Chapter.chapter_id.in_(chapter_ids))
            .order_by(Chapter.chapter_no)
        )
        chapters = list(ch_result.scalars().all())
        total = len(chapters)
        if total == 0:
            yield BatchProgressEvent(type="error", message="未找到指定章节")
            return

        project_id = chapters[0].project_id
        timeout = get_config().batch_rewrite_timeout_seconds
        min_len = get_config().min_ai_content_length
        failed: list[int] = []
        done = 0

        yield BatchProgressEvent(
            type="start",
            message=f"开始批量{mode}，共{total}章",
            progress=0,
        )

        for batch_start in range(0, total, BATCH_LIMIT):
            batch = chapters[batch_start:batch_start + BATCH_LIMIT]
            batch_no = batch_start // BATCH_LIMIT + 1
            record = BatchOperationRecord(
                batch_id=str(uuid.uuid4()),
                project_id=project_id,
                operation_type=mode,
                target_scope=json.dumps(
                    [ch.chapter_id for ch in batch], ensure_ascii=False
                ),
                batch_no=batch_no,
                batch_limit=BATCH_LIMIT,
                process_status="处理中",
            )
            self.session.add(record)
            await self.session.flush()
            await release_write_lock(self.session)

            for ch in batch:
                try:
                    await release_write_lock(self.session)
                    ai_result = await self.gateway.call(
                        module="rewrite",
                        scene="batch",
                        params={
                            "original_content": ch.content or "",
                            "instruction": instruction,
                            "chapter_context": ch.title,
                            "mode": mode,
                        },
                        project_id=project_id,
                        timeout_seconds=timeout,
                    )
                    new_content = ai_result.get("content", "")
                    if not new_content or len(new_content) < min_len:
                        failed.append(ch.chapter_no)
                        yield BatchProgressEvent(
                            type="failed",
                            chapter_no=ch.chapter_no,
                            message="AI未返回有效内容",
                        )
                    else:
                        ch.content = new_content
                        ch.word_count = len(new_content)
                        ch.modify_status = "modified"
                        yield BatchProgressEvent(
                            type="chapter",
                            chapter_no=ch.chapter_no,
                            content=new_content,
                        )
                except Exception as e:
                    failed.append(ch.chapter_no)
                    self.logger.warning(
                        f"批量{mode}第{ch.chapter_no}章失败: {e}",
                        exc_info=True,
                    )
                    yield BatchProgressEvent(
                        type="failed",
                        chapter_no=ch.chapter_no,
                        message=f"失败: {e}",
                    )
                done += 1
                yield BatchProgressEvent(
                    type="progress",
                    progress=int(done * 100 / total),
                )

            record.process_status = "完成"
            await self.session.commit()

        yield BatchProgressEvent(
            type="done",
            message=f"批量{mode}完成，成功{total - len(failed)}章，失败{len(failed)}章",
            progress=100,
        )
        if failed:
            yield BatchProgressEvent(
                type="summary",
                message=f"失败章节: {failed}",
            )