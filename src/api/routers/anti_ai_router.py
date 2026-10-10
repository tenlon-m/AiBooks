"""降AI率改写路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.anti_ai_schema import (
    AntiAiHistoryResponse,
    AntiAiRewriteDto,
    AntiAiRewriteRequest,
)
from src.api.schemas.writing_schema import ChapterDto
from src.db.session import get_session, session_scope
from src.services.anti_ai_service import AntiAiService
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


@router.post("/rewrite", response_model=AntiAiRewriteDto)
async def anti_ai_rewrite(
    req: AntiAiRewriteRequest, session: AsyncSession = Depends(get_session)
):
    """改写章节以降低AI检测率."""
    service = AntiAiService(session)
    try:
        return await service.rewrite_chapter(req.chapter_id, req.strategy)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"AI超时: {e}")
    except Exception as e:
        logger.error(f"降AI率改写失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"改写失败: {e}")


@router.get("/history/{chapter_id}", response_model=AntiAiHistoryResponse)
async def anti_ai_history(
    chapter_id: str, session: AsyncSession = Depends(get_session)
):
    """列出指定章节的降AI率改写历史."""
    service = AntiAiService(session)
    try:
        rewrites = await service.list_rewrites(chapter_id)
        return AntiAiHistoryResponse(chapter_id=chapter_id, rewrites=rewrites)
    except Exception as e:
        logger.error(f"获取改写历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取历史失败: {e}")


@router.post("/{rewrite_id}/adopt", response_model=ChapterDto)
async def anti_ai_adopt(
    rewrite_id: str, session: AsyncSession = Depends(get_session)
):
    """采纳改写，回写章节正文."""
    service = AntiAiService(session)
    try:
        return await service.adopt_rewrite(rewrite_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"采纳改写失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"采纳失败: {e}")


@router.post("/{rewrite_id}/rollback")
async def anti_ai_rollback(
    rewrite_id: str, session: AsyncSession = Depends(get_session)
):
    """回退至原文."""
    service = AntiAiService(session)
    try:
        await service.rollback_rewrite(rewrite_id)
        return {"success": True, "message": "已回退至原文"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"回退改写失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"回退失败: {e}")