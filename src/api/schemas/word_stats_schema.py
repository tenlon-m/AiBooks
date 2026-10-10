"""字数统计可视化 Pydantic 模型."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class ChapterWordStatsDto(BaseModel):
    chapter_id: str
    volume_no: int
    chapter_no: int
    title: str
    word_count: int
    gen_status: str


class WordStatsByChapterResponse(BaseModel):
    project_id: str
    stats: list[ChapterWordStatsDto] = Field(default_factory=list)
    total_words: int = 0
    total_chapters: int = 0


class VolumeWordStatsDto(BaseModel):
    volume_no: int
    chapter_count: int
    total_words: int
    avg_words: float


class DailyTrendDto(BaseModel):
    day: date
    word_count: int


class TargetCompletionDto(BaseModel):
    target_total_words: int
    actual_total_words: int
    completion_rate: float
    remaining_words: int


class WordStatsSummaryResponse(BaseModel):
    project_id: str
    by_volume: list[VolumeWordStatsDto] = Field(default_factory=list)
    daily_trend: list[DailyTrendDto] = Field(default_factory=list)
    target_completion: TargetCompletionDto | None = None