"""AB稿/ABC稿多AI接力纠错 Pydantic 模型."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ProofreadABRequest(BaseModel):
    chapter_id: str
    source_a: str
    source_b: str


class ProofreadABCRequest(BaseModel):
    chapter_id: str
    source_a: str
    source_b: str
    source_c: str
    source_eval: str


class ProofreadDraftDto(BaseModel):
    draft_id: str
    chapter_id: str
    draft_stage: str
    ai_source_id: str
    content: str
    score: float | None = None
    adopt_status: str
    created_at: datetime


class ProofreadResultDto(BaseModel):
    chapter_id: str
    drafts: list[ProofreadDraftDto]


class EvaluateResultDto(BaseModel):
    draft_id: str
    score: float
    dimensions: dict[str, Any]
    summary: str