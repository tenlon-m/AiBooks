"""爽点钩子 Pydantic 模型."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CoolPointDto(BaseModel):
    cool_id: str | None = None
    project_id: str | None = None
    volume_no: int
    chapter_no: int
    cool_type: str
    content_desc: str
    source: Literal["ai_design", "manual"] = "ai_design"


class HookDto(BaseModel):
    hook_id: str | None = None
    project_id: str | None = None
    volume_no: int
    chapter_no: int
    hook_content: str
    recycle_volume_no: int
    recycle_chapter_no: int
    recycle_status: Literal["pending", "recycled", "unrecycled"] = "pending"
    source: Literal["ai_design", "manual"] = "ai_design"


class ChapterPlanItem(BaseModel):
    volume_no: int
    chapter_no: int


class AiDesignHooksRequest(BaseModel):
    project_id: str
    synopsis: str
    worldview: str
    characters: list[dict]
    chapter_plan: list[ChapterPlanItem]
    user_ideas: str = ""


class AiDesignHooksResponse(BaseModel):
    cool_points: list[CoolPointDto]
    hooks: list[HookDto]
    missing_chapters: list[list[int]] = []
    failed_chapters: list[list[int]] = []


class CoolPointCreateRequest(BaseModel):
    project_id: str
    volume_no: int
    chapter_no: int
    cool_type: str
    content_desc: str


class HookCreateRequest(BaseModel):
    project_id: str
    volume_no: int
    chapter_no: int
    hook_content: str
    recycle_volume_no: int
    recycle_chapter_no: int

class HookChapterGenerateRequest(BaseModel):
    volume_no: int
    chapter_no: int
    prev_context: dict | None = None
    user_ideas: str = ""


class ChapterHookDto(BaseModel):
    volume_no: int
    chapter_no: int
    cool_points: list[CoolPointDto] = []
    hooks: list[HookDto] = []

class BatchDeleteCoolPointsRequest(BaseModel):
    cool_ids: list[str]


class BatchDeleteHooksRequest(BaseModel):
    hook_ids: list[str]


class SaveCoolPointsRequest(BaseModel):
    cool_points: list[CoolPointDto]


class SaveHooksRequest(BaseModel):
    hooks: list[HookDto]


class HookConsistencyIssue(BaseModel):
    level: str
    volume_no: int
    chapter_no: int
    type: str
    detail: str
    suggestion: str


class HookConsistencyResult(BaseModel):
    score: int
    summary: str
    issues: list[HookConsistencyIssue]
    text: str

class HookRepairRequest(BaseModel):
    issues: list[HookConsistencyIssue]
    repair_scope: Literal["all", "severe", "general"] = "all"
    garbled_config: dict | None = None


class HookRepairStreamChunk(BaseModel):
    type: str
    volume_no: int | None = None
    chapter_no: int | None = None
    done: int | None = None
    total: int | None = None
    status: str | None = None
    fail_reason: str | None = None
    message: str | None = None
    success: int | None = None
    failed: int | None = None
    skipped: int | None = None
    cool_points_new: list[dict] | None = None
    hooks_new: list[dict] | None = None
    auto_fixed: bool | None = None
    char_repair_stat: dict | None = None