"""一键拆书 Pydantic 模型."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ParsedContentDto(BaseModel):
    file_format: str
    content: str
    char_count: int


class TeardownOutlineDto(BaseModel):
    teardown_id: str
    multi_level_outline: str


class TeardownElementsDto(BaseModel):
    teardown_id: str
    characters: str | None = None
    time_places: str | None = None
    worldview: str | None = None
    special_items: str | None = None
    events: str | None = None


class CreateProjectFromTeardownRequest(BaseModel):
    teardown_id: str
    book_title: str = Field(min_length=1, max_length=50)


class BookTeardownDto(BaseModel):
    teardown_id: str
    source_file_path: str
    file_format: str
    teardown_status: str
    created_at: datetime