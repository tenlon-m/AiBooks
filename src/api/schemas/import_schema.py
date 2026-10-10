"""文件导入 Pydantic 模型."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ImportParseRequest(BaseModel):
    file_path: str
    category: Literal["synopsis", "worldview", "character"]


class ImportParseResponse(BaseModel):
    content: str
    char_count: int
    source_format: Literal["txt", "md", "docx", "xlsx"]