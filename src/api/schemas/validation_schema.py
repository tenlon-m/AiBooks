"""校验 Pydantic 模型."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ValidationItemDto(BaseModel):
    check_type: str
    result: Literal["pass", "fail"]
    problem_desc: str | None = None
    volume_no: int | None = None
    chapter_no: int | None = None


class CharacterCountIntegrityItem(ValidationItemDto):
    content_character_count: int | None = None
    confirmed_character_count: int | None = None


class FullBookValidationResponse(BaseModel):
    report_id: str
    project_id: str
    items: list[ValidationItemDto]
    ai_degree_score: Literal["excellent", "good", "medium", "poor"] = "good"
    ai_degree_problems: list[dict] = []
    validated_at: datetime


class RevalidateResponse(BaseModel):
    chapter_id: str
    items: list[ValidationItemDto]
    all_pass: bool


class AdjustNoteDto(BaseModel):
    position: str
    reason: str
    original: str | None = None
    polished: str | None = None


class PolishResponse(BaseModel):
    polished_content: str
    adjust_notes: list[AdjustNoteDto]


class PolishConfirmRequest(BaseModel):
    action: Literal["accept", "reject"]
    garbled_config: dict | None = None


class BatchRevalidateRequest(BaseModel):
    project_id: str
    chapter_ids: list[str]


class BatchRevalidateResponse(BaseModel):
    per_chapter: list[RevalidateResponse]
    global_character_change: ValidationItemDto
    global_item_change: ValidationItemDto
    global_item_consistency: ValidationItemDto

class ChapterConsistencyIssue(BaseModel):
    level: str
    type: str
    detail: str
    suggestion: str


class ChapterConsistencyResult(BaseModel):
    score: int
    summary: str
    issues: list[ChapterConsistencyIssue]
    text: str