"""章节摘要自动生成 Pydantic 模型."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChapterSummaryDto(BaseModel):
    chapter_id: str
    summary: str
    word_count: int = 0


class ChapterSummaryGenerateRequest(BaseModel):
    chapter_id: str


class ChapterSummaryBatchRequest(BaseModel):
    project_id: str
    chapter_ids: list[str] = Field(..., description="待生成摘要的章节ID列表")


class ChapterSummaryStreamChunk(BaseModel):
    type: str = Field("progress", description="chunk/done/progress")
    chapter_id: str = ""
    summary: str = ""
    message: str = ""