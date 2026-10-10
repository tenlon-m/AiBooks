"""批量提取/改写 Pydantic 模型."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExtractRequest(BaseModel):
    project_id: str = Field(..., description="项目ID")
    dimension: Literal["角色", "地点"] = Field(..., description="提取维度：角色/地点")
    target_name: str = Field(..., description="目标名称")


class ExtractItemDto(BaseModel):
    chapter_no: int
    excerpt: str


class ExtractResultDto(BaseModel):
    dimension: str
    target_name: str
    items: list[ExtractItemDto] = Field(default_factory=list)
    message: str | None = None


class BatchRewriteRequest(BaseModel):
    chapter_ids: list[str] = Field(..., description="待处理章节ID列表")
    instruction: str = Field(..., description="改写/扩写指令")


class BatchProgressEvent(BaseModel):
    type: str
    chapter_no: int | None = None
    content: str | None = None
    message: str | None = None
    progress: int | None = None