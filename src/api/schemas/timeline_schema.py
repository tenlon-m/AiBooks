"""时间线管理 Pydantic 模型."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TimelineNodeDto(BaseModel):
    node_id: str | None = None
    project_id: str | None = None
    event_name: str = Field(..., description="事件名称")
    time_point: str | None = Field(None, description="时间点描述")
    characters: list[str] = Field(default_factory=list, description="参与角色ID列表")
    chapter_ids: list[str] = Field(default_factory=list, description="关联章节ID列表")
    description: str | None = Field(None, description="事件描述")
    node_order: int = Field(0, description="排序序号")


class TimelineCreateRequest(BaseModel):
    project_id: str
    event_name: str
    time_point: str | None = None
    characters: list[str] = Field(default_factory=list)
    chapter_ids: list[str] = Field(default_factory=list)
    description: str | None = None
    node_order: int = 0


class TimelineUpdateRequest(BaseModel):
    event_name: str | None = None
    time_point: str | None = None
    characters: list[str] | None = None
    chapter_ids: list[str] | None = None
    description: str | None = None
    node_order: int | None = None


class TimelineReorderRequest(BaseModel):
    node_orders: list[dict] = Field(
        ..., description="排序列表，每项含 node_id 与 node_order"
    )


class TimelineReorderResult(BaseModel):
    success: bool
    conflicts: list[str] = Field(default_factory=list, description="时序冲突描述")