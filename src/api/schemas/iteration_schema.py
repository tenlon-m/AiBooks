"""迭代生成 Pydantic 模型."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class IterationStartRequest(BaseModel):
    project_id: str
    iteration_unit: Literal["卷", "阶段", "章"] = "章"
    target_id: str
    total_rounds: int


class IterationDto(BaseModel):
    iteration_id: str
    project_id: str
    iteration_unit: str
    target_id: str
    round_no: int
    total_rounds: int
    iteration_status: str
    created_at: datetime


class IterationProgressEvent(BaseModel):
    type: str
    round_no: int | None = None
    content: str | None = None
    message: str | None = None
    progress: int | None = None
    iteration_id: str | None = None