"""批量查找替换 Pydantic 模型."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BatchReplacePreviewRequest(BaseModel):
    project_id: str
    find: str = Field(..., description="查找文本或正则表达式")
    replace: str = Field("", description="替换文本")
    scope: Literal["whole_book", "chapters"] = Field(
        "whole_book", description="替换范围：全书或指定章节"
    )
    chapter_ids: list[str] = Field(default_factory=list, description="scope=chapters 时指定章节ID")
    mode: Literal["plain", "regex"] = Field("plain", description="匹配模式")
    case_sensitive: bool = Field(True, description="大小写敏感")


class MatchPreviewItem(BaseModel):
    chapter_id: str
    chapter_title: str
    paragraph_index: int
    offset: int
    context: str
    match_text: str


class BatchReplacePreviewResponse(BaseModel):
    preview_id: str
    matches: list[MatchPreviewItem]
    total: int
    truncated: bool = Field(False, description="是否超过上限被截断")


class BatchReplaceExecuteRequest(BaseModel):
    preview_id: str
    confirmed_indices: list[int] = Field(
        default_factory=list, description="确认执行的匹配下标列表，空表示全部"
    )


class BatchReplaceExecuteResponse(BaseModel):
    replaced_count: int
    chapter_ids: list[str]