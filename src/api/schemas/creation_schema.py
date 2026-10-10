"""创作参数 Pydantic 模型."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CreationParamsRequest(BaseModel):
    book_title: str = Field(min_length=1, max_length=50)
    volume_count: int = Field(ge=1, le=20)
    chapters_per_volume: int = Field(ge=1, le=100)
    words_per_chapter: int = Field(ge=500, le=10000)


class CreationParamsResponse(BaseModel):
    project_id: str
    book_title: str
    volume_count: int
    chapters_per_volume: int
    words_per_chapter: int
    created_at: datetime


class SynopsisRequest(BaseModel):
    content: str = Field(min_length=50)
    source: Literal["manual_input", "file_import"] = "manual_input"


class WorldviewRequest(BaseModel):
    content: str = Field(min_length=50)
    source: Literal["manual_input", "file_import"] = "manual_input"


class SynopsisResponse(BaseModel):
    project_id: str
    content: str
    source: str
    updated_at: datetime


class WorldviewResponse(BaseModel):
    project_id: str
    content: str
    source: str
    updated_at: datetime


class ProjectDto(BaseModel):
    project_id: str
    book_title: str
    volume_count: int
    chapters_per_volume: int
    words_per_chapter: int
    style_library_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    has_synopsis: bool = False
    has_worldview: bool = False

class ProjectSummaryDto(BaseModel):
    project_id: str
    book_title: str
    status: str
    created_at: datetime
    updated_at: datetime
    total_chapters: int = 0
    written_chapters: int = 0
    writing_progress: float = 0.0

class ProjectSaveRequest(BaseModel):
    project_id: str | None = None
    book_title: str = Field(min_length=1, max_length=50)
    volume_count: int = Field(ge=1, le=20)
    chapters_per_volume: int = Field(ge=1, le=100)
    words_per_chapter: int = Field(ge=500, le=10000)
    synopsis: str | None = None
    worldview: str | None = None


class ProjectSaveResponse(BaseModel):
    project_id: str
    book_title: str
    is_new: bool
    message: str
    has_synopsis: bool = False
    has_worldview: bool = False

class CreationPolishRequest(BaseModel):
    target: Literal["synopsis", "worldview"]
    raw_ideas: str = Field(min_length=10, description="用户输入的简单思路，≥10字")
    book_title: str = ""
    volume_count: int = Field(ge=1, le=20)
    chapters_per_volume: int = Field(ge=1, le=100)
    words_per_chapter: int = Field(ge=500, le=10000)
    synopsis: str = ""
    worldview: str = ""
    garbled_config: dict | None = None


class CreationPolishResponse(BaseModel):
    target: Literal["synopsis", "worldview"]
    polished_content: str
    source: str = "ai_polish"