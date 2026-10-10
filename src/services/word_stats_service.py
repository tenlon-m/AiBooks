"""字数统计可视化服务 - 按章节/分卷/日趋势/目标完成度统计."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.word_stats_schema import (
    ChapterWordStatsDto,
    DailyTrendDto,
    TargetCompletionDto,
    VolumeWordStatsDto,
    WordStatsByChapterResponse,
    WordStatsSummaryResponse,
)
from src.db.models import Chapter, Project
from src.utils.logger import get_logger


class WordStatsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    async def stats_by_chapter(self, project_id: str) -> WordStatsByChapterResponse:
        result = await self.session.execute(
            select(Chapter)
            .where(Chapter.project_id == project_id)
            .order_by(Chapter.volume_no, Chapter.chapter_no)
        )
        chapters = result.scalars().all()
        stats = [
            ChapterWordStatsDto(
                chapter_id=c.chapter_id,
                volume_no=c.volume_no,
                chapter_no=c.chapter_no,
                title=c.title,
                word_count=c.word_count,
                gen_status=c.gen_status,
            )
            for c in chapters
        ]
        total_words = sum(c.word_count for c in chapters)
        return WordStatsByChapterResponse(
            project_id=project_id,
            stats=stats,
            total_words=total_words,
            total_chapters=len(chapters),
        )

    async def summary(self, project_id: str) -> WordStatsSummaryResponse:
        project = await self.session.get(Project, project_id)
        result = await self.session.execute(
            select(Chapter)
            .where(Chapter.project_id == project_id)
            .order_by(Chapter.volume_no, Chapter.chapter_no)
        )
        chapters = result.scalars().all()

        by_volume: dict[int, list[Chapter]] = {}
        for c in chapters:
            by_volume.setdefault(c.volume_no, []).append(c)
        volume_stats = [
            VolumeWordStatsDto(
                volume_no=vno,
                chapter_count=len(chs),
                total_words=sum(c.word_count for c in chs),
                avg_words=(
                    sum(c.word_count for c in chs) / len(chs) if chs else 0.0
                ),
            )
            for vno, chs in sorted(by_volume.items())
        ]

        day_map: dict[date, int] = {}
        for c in chapters:
            day = c.last_modified_at.date() if c.last_modified_at else (
                c.created_at.date() if c.created_at else date.today()
            )
            day_map[day] = day_map.get(day, 0) + c.word_count
        daily_trend = [
            DailyTrendDto(day=day, word_count=wc)
            for day, wc in sorted(day_map.items())
        ]

        target_completion = None
        if project:
            target_total = (
                project.volume_count
                * project.chapters_per_volume
                * project.words_per_chapter
            )
            actual_total = sum(c.word_count for c in chapters)
            completion_rate = (
                actual_total / target_total if target_total > 0 else 0.0
            )
            target_completion = TargetCompletionDto(
                target_total_words=target_total,
                actual_total_words=actual_total,
                completion_rate=round(completion_rate, 4),
                remaining_words=max(0, target_total - actual_total),
            )

        return WordStatsSummaryResponse(
            project_id=project_id,
            by_volume=volume_stats,
            daily_trend=daily_trend,
            target_completion=target_completion,
        )