"""章节间衔接优化 Pydantic 模型."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConnectionAnalyzeRequest(BaseModel):
    project_id: str = Field(..., description="项目ID")
    prev_chapter_id: str = Field(..., description="前一章节ID")
    next_chapter_id: str = Field(..., description="后一章节ID")
    user_ideas: str = Field("", description="作者补充说明")


class ConnectionIssue(BaseModel):
    type: str
    detail: str
    suggestion: str


class ConnectionAnalyzeResponse(BaseModel):
    score: int = Field(..., description="衔接分数0-100")
    issues: list[ConnectionIssue] = []
    transition: str = Field("", description="衔接过渡段落")
    summary: str = Field("", description="总体评价")


class ConnectionStreamChunk(BaseModel):
    type: Literal["chunk", "done", "progress"] = "chunk"
    content: str = ""
    message: str = ""