"""章节注释/批注服务 - CRUD 与锚定失效."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.annotation_schema import (
    AnnotationDto,
    AnnotationListResponse,
)
from src.db.models import ChapterAnnotation
from src.utils.logger import get_logger


class AnnotationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    async def create(
        self,
        chapter_id: str,
        paragraph_index: int,
        content: str,
        annotation_type: str = "note",
    ) -> AnnotationDto:
        if not content.strip():
            raise ValueError("批注内容不能为空")
        now = datetime.now(timezone.utc)
        annotation = ChapterAnnotation(
            annotation_id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            paragraph_index=paragraph_index,
            content=content,
            annotation_type=annotation_type,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self.session.add(annotation)
        await self.session.commit()
        return self._to_dto(annotation)

    async def list_by_chapter(
        self, chapter_id: str, status: str | None = None
    ) -> AnnotationListResponse:
        stmt = select(ChapterAnnotation).where(
            ChapterAnnotation.chapter_id == chapter_id
        ).order_by(ChapterAnnotation.paragraph_index, ChapterAnnotation.created_at)
        if status:
            stmt = stmt.where(ChapterAnnotation.status == status)
        result = await self.session.execute(stmt)
        annotations = [self._to_dto(a) for a in result.scalars().all()]
        return AnnotationListResponse(
            annotations=annotations,
            total=len(annotations),
        )

    async def update(
        self,
        annotation_id: str,
        content: str | None = None,
        status: str | None = None,
    ) -> AnnotationDto:
        annotation = await self.session.get(ChapterAnnotation, annotation_id)
        if not annotation:
            raise ValueError(f"批注不存在: {annotation_id}")
        if content is not None:
            if not content.strip():
                raise ValueError("批注内容不能为空")
            annotation.content = content
        if status is not None:
            annotation.status = status
        annotation.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return self._to_dto(annotation)

    async def delete(self, annotation_id: str) -> int:
        annotation = await self.session.get(ChapterAnnotation, annotation_id)
        if not annotation:
            raise ValueError(f"批注不存在: {annotation_id}")
        await self.session.delete(annotation)
        await self.session.commit()
        return 1

    async def invalidate(self, annotation_id: str) -> AnnotationDto:
        annotation = await self.session.get(ChapterAnnotation, annotation_id)
        if not annotation:
            raise ValueError(f"批注不存在: {annotation_id}")
        annotation.status = "anchor_invalid"
        annotation.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return self._to_dto(annotation)

    async def invalidate_by_paragraph(
        self, chapter_id: str, paragraph_index: int
    ) -> int:
        result = await self.session.execute(
            select(ChapterAnnotation).where(
                ChapterAnnotation.chapter_id == chapter_id,
                ChapterAnnotation.paragraph_index == paragraph_index,
                ChapterAnnotation.status != "anchor_invalid",
            )
        )
        count = 0
        now = datetime.now(timezone.utc)
        for ann in result.scalars().all():
            ann.status = "anchor_invalid"
            ann.updated_at = now
            count += 1
        if count:
            await self.session.commit()
        return count

    @staticmethod
    def _to_dto(annotation: ChapterAnnotation) -> AnnotationDto:
        return AnnotationDto(
            annotation_id=annotation.annotation_id,
            chapter_id=annotation.chapter_id,
            paragraph_index=annotation.paragraph_index,
            content=annotation.content,
            annotation_type=annotation.annotation_type,
            status=annotation.status,
            created_at=annotation.created_at,
            updated_at=annotation.updated_at,
        )