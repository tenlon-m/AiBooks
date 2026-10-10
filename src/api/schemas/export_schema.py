"""导出 Pydantic 模型."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ExportRequest(BaseModel):
    project_id: str
    target_dir: str


class ExportResponse(BaseModel):
    file_path: str
    char_count: int


class ExportOptions(BaseModel):
    chapter_pagination: bool = Field(True, description="章节分页")
    include_outline: bool = Field(False, description="包含大纲")
    include_characters: bool = Field(False, description="包含角色设定")
    cover_page: bool = Field(True, description="封面页")


class MultiFormatExportRequest(BaseModel):
    project_id: str
    target_dir: str
    template_id: str | None = Field(None, description="排版模板ID")
    options: ExportOptions = Field(default_factory=ExportOptions)
