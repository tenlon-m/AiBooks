"""章节注释/批注 Pydantic 模型."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AnnotationCreateRequest(BaseModel):
    chapter_id: str
    paragraph_index: int = Field(..., ge=0, description="段落索引")
    content: str = Field(..., description="批注内容")
    annotation_type: Literal["note", "question", "todo", "issue"] = Field(
        "note", description="批注类型"
    )


class AnnotationUpdateRequest(BaseModel):
    content: str | None = None
    status: Literal["pending", "processed", "anchor_invalid"] | None = None


class AnnotationDto(BaseModel):
    annotation_id: str
    chapter_id: str
    paragraph_index: int
    content: str
    annotation_type: str
    status: str
    created_at: datetime
    updated_at: datetime


class AnnotationListResponse(BaseModel):
    annotations: list[AnnotationDto]
    total: int