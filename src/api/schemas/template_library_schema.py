"""写作模板/套路库 Pydantic 模型."""
from __future__ import annotations

from pydantic import BaseModel, Field


class WritingTemplateStage(BaseModel):
    name: str = ""
    volume: int = 0
    chapters: str = ""
    desc: str = ""


class WritingTemplateCoolRhythm(BaseModel):
    interval: int = 0
    type: str = ""
    desc: str = ""


class WritingTemplateDto(BaseModel):
    name: str
    novel_type: str
    stages: list[WritingTemplateStage] = []
    cool_rhythm: list[WritingTemplateCoolRhythm] = []
    character_config: dict = {}
    outline_skeleton: dict = {}
    is_builtin: bool = True


class TemplateLibraryListResponse(BaseModel):
    templates: list[WritingTemplateDto] = []


class TemplateLibraryDetailResponse(BaseModel):
    template: WritingTemplateDto


class TemplateLibraryApplyRequest(BaseModel):
    project_id: str = Field(..., description="项目ID")
    novel_type: str = Field(..., description="小说类型标识")

class WorldviewTemplateDto(BaseModel):
    name: str = ""
    world_type: str = ""
    power_system: str = ""
    social_structure: str = ""
    geography: str = ""
    races: list[str] = []
    core_rules: list[str] = []
    is_builtin: bool = True


class WorldviewTemplateListResponse(BaseModel):
    templates: list[WorldviewTemplateDto] = []


class WorldviewTemplateDetailResponse(BaseModel):
    template: WorldviewTemplateDto


class WorldviewTemplateApplyRequestDto(BaseModel):
    project_id: str = Field(..., description="项目ID")
    world_type: str = Field(..., description="世界观类型标识")