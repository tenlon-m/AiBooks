"""降AI率改写 Pydantic 模型."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AntiAiRewriteRequest(BaseModel):
    chapter_id: str = Field(..., description="章节ID")
    strategy: str = Field("全部", description="改写策略：句式变换/同义替换/口语化/全部")


class AntiAiRewriteDto(BaseModel):
    rewrite_id: str
    chapter_id: str
    rewritten_content: str
    strategy: str
    adopt_status: str
    created_at: str


class AntiAiHistoryResponse(BaseModel):
    chapter_id: str
    rewrites: list[AntiAiRewriteDto] = []