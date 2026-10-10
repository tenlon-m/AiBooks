"""情感曲线分析 Pydantic 模型."""
from __future__ import annotations

from pydantic import BaseModel, Field


class EmotionCurvePointDto(BaseModel):
    point_id: str | None = None
    project_id: str | None = None
    chapter_id: str
    chapter_no: int
    tension: float = Field(..., ge=0.0, le=1.0, description="紧张度 0.0-1.0")
    emotion_fluctuation: float = Field(
        ..., ge=0.0, le=1.0, description="情绪波动 0.0-1.0"
    )


class EmotionAnalyzeRequest(BaseModel):
    project_id: str
    chapter_ids: list[str] = Field(..., description="待分析章节ID列表")


class EmotionCurveResponse(BaseModel):
    project_id: str
    points: list[EmotionCurvePointDto] = Field(default_factory=list)


class EmotionStreamChunk(BaseModel):
    type: str = Field("progress", description="chunk/done/progress")
    chapter_id: str = ""
    point: EmotionCurvePointDto | None = None
    message: str = ""