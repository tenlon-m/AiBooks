"""大纲拖拽排序 Pydantic 模型."""
from __future__ import annotations

from pydantic import BaseModel, Field


class OutlineOrderItem(BaseModel):
    chapter_id: str
    volume_no: int
    chapter_no: int


class OutlineReorderRequest(BaseModel):
    project_id: str
    new_order: list[OutlineOrderItem] = Field(..., description="新顺序列表")


class OutlineReorderResponse(BaseModel):
    success: bool
    conflicts: list[str] = Field(default_factory=list, description="时间线冲突描述")