"""乱码检测修复 Pydantic Schema.

对应 spec 6.5 默认值与 design 2.6 字段定义。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class GarbledConfigSchema(BaseModel):
    """乱码检测修复配置."""

    enabled: bool = True
    max_blank_lines: int = 1
    max_punct_repeat: int = 2
    max_consecutive_spaces: int = 1
    enable_fullwidth_indent: bool = True
    enable_punct_repeat_fix: bool = True
    enable_whitespace_cleanup: bool = True
    enable_irreversible_clear: bool = True


class CharacterRepairStatSchema(BaseModel):
    """字符修复统计."""

    garbled_detected: int = 0
    format_detected: int = 0
    garbled_fixed: int = 0
    format_fixed: int = 0
    remainder: int = 0
    hit_categories: list[str] = Field(default_factory=list)
    irreversible_cleared: int = 0
    details: list[dict] = Field(default_factory=list)


class GarbledDetailItemSchema(BaseModel):
    """单条修复明细."""

    category: str = ""
    position: str = ""
    action: str = ""
    irreversible: bool = False


class GarbledConfigSaveRequest(BaseModel):
    """保存乱码配置请求."""

    enabled: bool | None = None
    max_blank_lines: int | None = None
    max_punct_repeat: int | None = None
    max_consecutive_spaces: int | None = None
    enable_fullwidth_indent: bool | None = None
    enable_punct_repeat_fix: bool | None = None
    enable_whitespace_cleanup: bool | None = None
    enable_irreversible_clear: bool | None = None