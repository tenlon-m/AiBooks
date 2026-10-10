"""物品 Pydantic 模型."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ItemDto(BaseModel):
    item_id: str | None = None
    project_id: str | None = None
    name: str = Field(min_length=1, max_length=30)
    item_type: str
    key_attrs: str | None = None
    owner_character: str | None = None
    first_appear_volume: int = 1
    first_appear_chapter: int = 1


class ItemExtractRequest(BaseModel):
    project_id: str
    chapter_content: str
    volume_no: int
    chapter_no: int


class ItemCreateRequest(BaseModel):
    project_id: str = Field(..., description="项目ID")
    name: str = Field(..., min_length=1, max_length=30)
    item_type: str = Field(..., min_length=1, max_length=50, description="物品类型，如 武器/丹药/功法")
    key_attrs: str | None = None
    owner_character: str | None = None
    first_appear_volume: int = Field(1, ge=1)
    first_appear_chapter: int = Field(1, ge=1)


class ItemUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=30)
    item_type: str | None = Field(None, min_length=1, max_length=50)
    key_attrs: str | None = None
    owner_character: str | None = None
    first_appear_volume: int | None = Field(None, ge=1)
    first_appear_chapter: int | None = Field(None, ge=1)


class ItemConsistencyResponse(BaseModel):
    problems: list[str] = Field(default_factory=list)