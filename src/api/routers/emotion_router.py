"""情感曲线分析路由 - 含SSE流式."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.emotion_schema import (
    EmotionAnalyzeRequest,
    EmotionCurveResponse,
)
from src.db.session import get_session, session_scope
from src.services.emotion_curve_service import EmotionCurveService
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


@router.post("/analyze/stream")
async def analyze_emotion_stream(
    req: EmotionAnalyzeRequest,
):
    """情感曲线分析 - SSE逐章流式返回."""
    async def event_stream():
        async with session_scope() as session:
            service = EmotionCurveService(session)
            try:
                async for chunk in service.analyze(req.project_id, req.chapter_ids):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                logger.error(f"SSE emotion/analyze/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/{project_id}/curve", response_model=EmotionCurveResponse)
async def get_emotion_curve(
    project_id: str, session: AsyncSession = Depends(get_session)
):
    service = EmotionCurveService(session)
    try:
        return await service.get_curve(project_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取情感曲线失败: {e}")