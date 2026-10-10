"""大纲管理 Pydantic 模型."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChapterOutlineDto(BaseModel):
    chapter_id: str = ""
    chapter_no: int
    chapter_name: str = Field(min_length=1, max_length=50)
    synopsis_points: str
    characters_appearing: str = ""
    gen_source: str = "AI生成"
    scene_count: int = 0


class VolumeOutlineDto(BaseModel):
    volume_no: int
    volume_name: str = Field(min_length=1, max_length=50)
    chapters: list[ChapterOutlineDto] = []


class OutlineDto(BaseModel):
    outline_id: str | None = None
    project_id: str
    gen_status: str = "未生成"
    source: str = "AI生成"
    generated_at: datetime | None = None
    volumes: list[VolumeOutlineDto] = []


class OutlineGenerateRequest(BaseModel):
    force_overwrite: bool = False
    user_ideas: str = Field(default="", description="用户对大纲的思路与想法，AI生成时参考")


class OutlineBatchGenerateRequest(BaseModel):
    """分批生成大纲请求 - 每次仅生成一批（若干章），避免单次调用超时."""

    volume_no: int = Field(ge=1, description="本批章节所属卷号")
    chapter_start: int = Field(ge=1, description="本批起始章号（含）")
    chapter_count: int = Field(ge=1, le=50, description="本批生成章节数")
    reset: bool = Field(default=False, description="是否清空已有大纲后重新生成（首批使用）")
    user_ideas: str = Field(default="", description="用户对大纲的思路与想法，AI生成时参考")


class OutlineCheckRequest(BaseModel):
    """大纲一致性校验请求 - 与分批生成对齐，逐批校验避免单次输入过长."""

    volume_no: int = Field(ge=1, description="待校验章节所属卷号")
    chapter_start: int = Field(ge=1, description="待校验起始章号（含）")
    chapter_count: int = Field(ge=1, le=50, description="待校验章节数")
    garbled_config: dict | None = None


class OutlineConsistencyIssue(BaseModel):
    """一致性校验发现的单个问题."""

    level: str = Field(default="", description="严重程度：严重/一般/轻微")
    chapter_no: int = Field(default=0, description="关联章号，0 表示整批")
    type: str = Field(default="", description="问题类型")
    detail: str = Field(default="", description="问题描述")
    suggestion: str = Field(default="", description="修改建议")


class OutlineConsistencyResult(BaseModel):
    """单批一致性校验结果."""

    score: int = Field(default=0, description="本批一致性评分 0-100")
    summary: str = Field(default="", description="总体评价")
    issues: list[OutlineConsistencyIssue] = Field(default_factory=list)
    checked_chapter_count: int = Field(default=0, description="本批已校验章节数")


class ChapterOutlineSaveItem(BaseModel):
    chapter_no: int
    chapter_name: str = Field(min_length=1, max_length=50)
    synopsis_points: str
    characters_appearing: str = ""


class VolumeOutlineSaveItem(BaseModel):
    volume_no: int
    volume_name: str = Field(min_length=1, max_length=50)
    chapters: list[ChapterOutlineSaveItem] = []


class OutlineSaveRequest(BaseModel):
    volumes: list[VolumeOutlineSaveItem] = []


class ChapterDraft(BaseModel):
    chapter_no: int
    chapter_name: str = ""
    synopsis_points: str = ""
    characters_appearing: str = ""


class VolumeDraft(BaseModel):
    volume_no: int
    volume_name: str = ""
    chapters: list[ChapterDraft] = []


class FillAppearingRequest(BaseModel):
    volume_no: int | None = None
    chapter_start: int | None = None
    chapter_count: int | None = None


class FillAppearingResultItem(BaseModel):
    chapter_no: int
    matched: list[str] = []
    pending: list[str] = []
    skipped: bool = False
    fail_reason: str | None = None


class FillAppearingResponse(BaseModel):
    results: list[FillAppearingResultItem] = []
    summary: str = ""


class AdjustNote(BaseModel):
    position: str
    reason: str
    original: str | None = None
    polished: str | None = None


class OutlineRepairRequest(BaseModel):
    issues: list[OutlineConsistencyIssue]
    repair_scope: Literal["all", "severe", "general"] = "all"
    garbled_config: dict | None = None


class RepairStreamChunk(BaseModel):
    type: str
    chapter_no: int | None = None
    volume_no: int | None = None
    synopsis_points_new: str | None = None
    characters_appearing_new: str | None = None
    adjust_notes: list[AdjustNote] | None = None
    status: str | None = None
    fail_reason: str | None = None
    message: str | None = None
    success: int | None = None
    failed: int | None = None
    skipped: int | None = None
    done: int | None = None
    total: int | None = None
    char_repair_stat: dict | None = None


class OutlineDraft(BaseModel):
    volumes: list[VolumeDraft] = []


class VolumeBatchDraft(BaseModel):
    """单批生成结果 - 一批章节仅属于一个卷."""

    volume_no: int
    volume_name: str = ""
    chapters: list[ChapterDraft] = []