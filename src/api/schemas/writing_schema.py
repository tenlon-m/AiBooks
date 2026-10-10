"""批量撰写 Pydantic 模型."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class StartWritingRequest(BaseModel):
    project_id: str
    style_library_id: str | None = None
    user_ideas: str = ""
    garbled_config: dict | None = None
    proofread_mode: str = "off"
    proofread_sources: dict | None = None


class ChapterSaveItem(BaseModel):
    chapter_id: str
    new_content: str


class SaveWritingRequest(BaseModel):
    chapters: list[ChapterSaveItem]


class WritingConsistencyIssue(BaseModel):
    level: str
    volume_no: int
    chapter_no: int
    type: str
    detail: str
    suggestion: str


class WritingConsistencyResult(BaseModel):
    score: int
    summary: str
    issues: list[WritingConsistencyIssue]
    text: str


class WritingRepairRequest(BaseModel):
    issues: list[WritingConsistencyIssue]
    repair_scope: str = "all"
    garbled_config: dict | None = None


class WritingRepairStreamChunk(BaseModel):
    type: Literal["progress", "chapter_done", "chapter_skip", "completed", "error"]
    volume_no: int = 0
    chapter_no: int = 0
    done: int = 0
    total: int = 0
    status: str = ""
    fail_reason: str = ""
    success: int = 0
    failed: int = 0
    skipped: int = 0
    message: str = ""
    char_repair_stat: dict | None = None
    char_repair_details: list | None = None


class WritingFillStreamChunk(BaseModel):
    type: Literal["progress", "chapter_done", "chapter_skip", "completed", "error"]
    volume_no: int = 0
    chapter_no: int = 0
    done: int = 0
    total: int = 0
    status: str = ""
    word_count_before: int = 0
    word_count_after: int = 0
    retries: int = 0
    fail_reason: str = ""
    success: int = 0
    skipped: int = 0
    still_underfilled: int = 0
    message: str = ""
    char_repair_stat: dict | None = None


class WritingProgressEvent(BaseModel):
    current_volume: int
    current_chapter: int
    total_chapters: int
    status: Literal["writing", "paused", "completed", "failed"]
    completed_ratio: float
    message: str = ""


class ChapterDto(BaseModel):
    chapter_id: str
    project_id: str
    volume_no: int
    chapter_no: int
    title: str
    content: str | None = None
    word_count: int
    gen_status: str
    modify_status: str
    summary: str | None = None
    words_per_chapter: int = 0
    underfilled: bool = False