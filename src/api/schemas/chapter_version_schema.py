"""章节多版本管理 Pydantic 模型."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChapterVersionDto(BaseModel):
    version_id: str
    chapter_id: str
    version_type: Literal["auto", "manual"]
    name: str | None = None
    word_count: int
    created_at: datetime


class VersionMarkManualRequest(BaseModel):
    name: str = Field(..., description="手动版本名称")


class VersionDiffResponse(BaseModel):
    version_id_a: str
    version_id_b: str
    html_diff: str


class VersionRollbackResponse(BaseModel):
    chapter_id: str
    new_version_id: str
    word_count: int
    success: bool
    message: str


class VersionCleanupResponse(BaseModel):
    chapter_id: str
    deleted_count: int