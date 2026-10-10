"""章节合并/拆分 Pydantic 模型."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChapterMergeRequest(BaseModel):
    chapter_ids: list[str] = Field(..., description="待合并章节ID列表，按顺序")
    new_title: str | None = Field(None, description="合并后新标题，留空由AI生成")


class ChapterMergeResponse(BaseModel):
    new_chapter_id: str
    new_title: str
    volume_no: int
    chapter_no: int
    word_count: int


class ChapterSplitRequest(BaseModel):
    chapter_id: str
    split_positions: list[int] = Field(
        ..., description="拆分位置（字符偏移列表，升序）"
    )
    new_titles: list[str] = Field(
        default_factory=list, description="拆分后各段标题，留空使用默认标题"
    )


class ChapterSplitResponse(BaseModel):
    new_chapter_ids: list[str]
    titles: list[str]