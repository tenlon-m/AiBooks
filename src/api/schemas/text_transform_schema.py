"""续写/扩写/缩写 Pydantic 模型."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TextTransformRequest(BaseModel):
    project_id: str = Field(..., description="项目ID")
    chapter_id: str = Field("", description="章节ID，可选用于读取上下文")
    content: str = Field(..., description="待处理文本")
    direction: str = Field("", description="处理方向说明")
    target_words: int = Field(0, description="目标字数，0表示不限定")
    user_ideas: str = Field("", description="作者补充说明")


class TextTransformResponse(BaseModel):
    content: str = Field(..., description="处理后的文本")
    word_count: int = Field(0, description="处理后字数")


class TextTransformStreamChunk(BaseModel):
    type: Literal["chunk", "done", "progress"] = "chunk"
    content: str = ""
    message: str = ""