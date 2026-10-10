"""章节 Pydantic 模型."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ChapterContentUpdateRequest(BaseModel):
    new_content: str
    garbled_config: dict | None = None


class ChapterContentResponse(BaseModel):
    chapter_id: str
    volume_no: int
    chapter_no: int
    title: str
    content: str
    word_count: int


class HistoryRecordDto(BaseModel):
    record_id: str
    modify_type: Literal["manual_edit", "rollback"]
    modified_at: datetime
    final_content_preview: str
    is_rollbackable: bool


class RollbackRequest(BaseModel):
    target_record_id: str


class RollbackResponse(BaseModel):
    chapter_id: str
    success: bool
    message: str

class ChapterLockRequest(BaseModel):
    is_locked: bool


class ChapterLockResponse(BaseModel):
    chapter_id: str
    is_locked: bool