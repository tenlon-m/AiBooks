"""AI写剧本 Pydantic 模型."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ScriptGenerateRequest(BaseModel):
    project_id: str


class ScriptEpisodeDto(BaseModel):
    script_id: str
    project_id: str
    episode_no: int
    scene_description: str
    character_dialogue: str
    created_at: datetime | None = None


class ScriptProgressEvent(BaseModel):
    type: str
    episode_no: int | None = None
    scene_description: str | None = None
    character_dialogue: str | None = None
    message: str | None = None
    progress: int | None = None


class ScriptExportRequest(BaseModel):
    project_id: str
    target_dir: str
    format: str = Field(default="txt")