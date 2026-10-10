"""场景级大纲细化 Pydantic 模型."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SceneSplitRequest(BaseModel):
    project_id: str = Field(..., description="项目ID")
    chapter_id: str = Field(..., description="章节ID")
    target_words: int = Field(3000, description="目标字数")
    user_ideas: str = Field("", description="作者补充说明")


class BatchSceneSplitRequest(BaseModel):
    project_id: str = Field(..., description="项目ID")
    target_words: int = Field(3000, description="目标字数")
    user_ideas: str = Field("", description="作者补充说明")


class SceneUpdateRequest(BaseModel):
    scene_order: int | None = Field(None, description="场景序号")
    goal: str | None = Field(None, description="场景目标")
    characters: str | None = Field(None, description="出场角色")
    key_event: str | None = Field(None, description="关键事件")
    mood: str | None = Field(None, description="情绪基调")
    est_words: int | None = Field(None, description="预计字数")


class SceneDto(BaseModel):
    scene_id: str | None = None
    chapter_id: str | None = None
    scene_order: int
    goal: str
    characters: str = ""
    key_event: str
    mood: str = ""
    est_words: int = 0


class SceneSplitResponse(BaseModel):
    scenes: list[SceneDto] = []


class SceneStreamChunk(BaseModel):
    type: Literal["chunk", "done", "progress", "failed"] = "chunk"
    content: str = ""
    message: str = ""
    scene: SceneDto | None = None
    chapter_id: str | None = None
    chapter_title: str | None = None
    total: int | None = None
    current: int | None = None
    success_count: int | None = None
    failed_count: int | None = None
    failed_chapters: list[dict] | None = None