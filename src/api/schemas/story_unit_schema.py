"""故事单元 Pydantic 模型 - 雪花式5级分层大纲."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StoryUnitDto(BaseModel):
    story_unit_id: str
    project_id: str
    parent_unit_id: str | None = None
    level_type: str
    unit_no: int
    unit_name: str
    synopsis: str
    chapter_count: int = 0
    gen_status: str = "未生成"
    narrative_duty: str = ""
    cascade_dirty: bool = False
    created_at: datetime | None = None


class StoryUnitTreeDto(BaseModel):
    project_id: str
    units: list[StoryUnitDto] = []


class StoryUnitUpdateRequest(BaseModel):
    unit_name: str | None = Field(default=None, max_length=50)
    synopsis: str | None = None
    narrative_duty: str | None = None


class GenerateLayerRequest(BaseModel):
    project_id: str
    parent_unit_id: str | None = None
    level_type: str