"""情感曲线分析服务 - SSE逐章分析紧张度与情绪波动."""
from __future__ import annotations

import uuid
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.emotion_schema import (
    EmotionCurvePointDto,
    EmotionCurveResponse,
    EmotionStreamChunk,
)
from src.config.settings import get_config
from src.db.models import Chapter, EmotionCurvePoint, Project
from src.db.session import release_write_lock
from src.utils.logger import get_logger


class EmotionCurveService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def _analyze_chapter(
        self, project_id: str, chapter: Chapter
    ) -> EmotionCurvePointDto:
        content = chapter.content or ""
        if len(content) < get_config().min_ai_content_length:
            raise ValueError(f"章节 {chapter.chapter_no} 内容不足{get_config().min_ai_content_length}字")

        await release_write_lock(self.session)
        result = await self.gateway.call_and_parse(
            module="emotion",
            scene="analyze",
            params={
                "chapter_no": chapter.chapter_no,
                "chapter_title": chapter.title,
                "chapter_content": content,
            },
            project_id=project_id,
            timeout_seconds=get_config().emotion_analyze_timeout_seconds,
        )
        parsed = result.get("parsed", {})
        tension = float(parsed.get("tension", 0.5))
        fluctuation = float(parsed.get("emotion_fluctuation", 0.5))
        tension = max(0.0, min(1.0, tension))
        fluctuation = max(0.0, min(1.0, fluctuation))

        existing = await self.session.execute(
            select(EmotionCurvePoint).where(
                EmotionCurvePoint.project_id == project_id,
                EmotionCurvePoint.chapter_id == chapter.chapter_id,
            )
        )
        entity = existing.scalars().first()
        if entity:
            entity.tension = tension
            entity.emotion_fluctuation = fluctuation
        else:
            entity = EmotionCurvePoint(
                point_id=str(uuid.uuid4()),
                project_id=project_id,
                chapter_id=chapter.chapter_id,
                chapter_no=chapter.chapter_no,
                tension=tension,
                emotion_fluctuation=fluctuation,
            )
            self.session.add(entity)
        await self.session.commit()

        return EmotionCurvePointDto(
            point_id=entity.point_id,
            project_id=project_id,
            chapter_id=chapter.chapter_id,
            chapter_no=chapter.chapter_no,
            tension=tension,
            emotion_fluctuation=fluctuation,
        )

    async def analyze(
        self, project_id: str, chapter_ids: list[str]
    ) -> AsyncGenerator[EmotionStreamChunk, None]:
        project = await self.session.get(Project, project_id)
        if not project:
            yield EmotionStreamChunk(type="done", message="项目不存在")
            return
        total = len(chapter_ids)
        for idx, cid in enumerate(chapter_ids, 1):
            yield EmotionStreamChunk(
                type="progress",
                message=f"正在分析第 {idx}/{total} 章...",
            )
            chapter = await self.session.get(Chapter, cid)
            if not chapter or chapter.project_id != project_id:
                yield EmotionStreamChunk(
                    type="done",
                    chapter_id=cid,
                    message=f"章节 {cid} 不存在",
                )
                continue
            try:
                point = await self._analyze_chapter(project_id, chapter)
                yield EmotionStreamChunk(
                    type="chunk",
                    chapter_id=cid,
                    point=point,
                )
            except ValueError as e:
                yield EmotionStreamChunk(
                    type="done",
                    chapter_id=cid,
                    message=f"章节内容不足: {e}",
                )
            except Exception as e:
                yield EmotionStreamChunk(
                    type="done",
                    chapter_id=cid,
                    message=f"AI分析异常: {e}",
                )
        yield EmotionStreamChunk(type="done", message=f"共分析 {total} 章")

    async def get_curve(self, project_id: str) -> EmotionCurveResponse:
        result = await self.session.execute(
            select(EmotionCurvePoint)
            .where(EmotionCurvePoint.project_id == project_id)
            .order_by(EmotionCurvePoint.chapter_no)
        )
        points = [
            EmotionCurvePointDto(
                point_id=p.point_id,
                project_id=p.project_id,
                chapter_id=p.chapter_id,
                chapter_no=p.chapter_no,
                tension=p.tension,
                emotion_fluctuation=p.emotion_fluctuation,
            )
            for p in result.scalars().all()
        ]
        return EmotionCurveResponse(project_id=project_id, points=points)