"""章节间衔接优化路由 - 含SSE流式."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.connection_schema import (
    ConnectionAnalyzeRequest,
    ConnectionAnalyzeResponse,
)
from src.db.session import get_session, session_scope
from src.services.connection_service import ConnectionService
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


@router.post("/analyze", response_model=ConnectionAnalyzeResponse)
async def connection_analyze(req: ConnectionAnalyzeRequest, session: AsyncSession = Depends(get_session)):
    """章节间衔接优化分析."""
    service = ConnectionService(session)
    try:
        return await service.analyze(
            req.project_id, req.prev_chapter_id, req.next_chapter_id, req.user_ideas
        )
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "不足" in msg:
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"AI超时: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"衔接分析失败: {e}")


@router.post("/analyze/stream")
async def connection_analyze_stream(req: ConnectionAnalyzeRequest):
    """章节间衔接优化分析 - SSE流式."""
    async def event_stream():
        async with session_scope() as session:
            service = ConnectionService(session)
            try:
                async for chunk in service.stream_analyze(
                    req.project_id, req.prev_chapter_id, req.next_chapter_id, req.user_ideas
                ):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                logger.error(f"SSE connection/analyze/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )