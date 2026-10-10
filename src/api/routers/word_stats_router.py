"""字数统计可视化路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.word_stats_schema import (
    WordStatsByChapterResponse,
    WordStatsSummaryResponse,
)
from src.db.session import get_session
from src.services.word_stats_service import WordStatsService

router = APIRouter()


@router.get("/{project_id}/by_chapter", response_model=WordStatsByChapterResponse)
async def stats_by_chapter(
    project_id: str, session: AsyncSession = Depends(get_session)
):
    service = WordStatsService(session)
    try:
        return await service.stats_by_chapter(project_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"字数统计失败: {e}")


@router.get("/{project_id}/summary", response_model=WordStatsSummaryResponse)
async def stats_summary(project_id: str, session: AsyncSession = Depends(get_session)):
    service = WordStatsService(session)
    try:
        return await service.summary(project_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"字数统计汇总失败: {e}")