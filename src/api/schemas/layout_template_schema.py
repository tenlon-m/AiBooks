"""排版模板 Pydantic 模型."""
from __future__ import annotations

from pydantic import BaseModel, Field


class LayoutTemplateDto(BaseModel):
    template_id: str
    name: str
    format: str
    font: str | None = None
    font_size: int | None = None
    line_spacing: float | None = None
    title_style: str | None = None
    first_indent: bool | None = True
    header: str | None = None
    footer: str | None = None
    is_builtin: bool = False


class LayoutTemplateListResponse(BaseModel):
    templates: list[LayoutTemplateDto] = []


class LayoutTemplateCreateRequest(BaseModel):
    name: str = Field(..., description="模板名称")
    format: str = Field(..., description="适用格式")
    font: str | None = Field(None, description="字体")
    font_size: int | None = Field(None, description="字号")
    line_spacing: float | None = Field(None, description="行距")
    title_style: str | None = Field(None, description="标题样式")
    first_indent: bool | None = Field(True, description="首行缩进")
    header: str | None = Field(None, description="页眉")
    footer: str | None = Field(None, description="页脚")