"""AI对话式写作辅助路由 - 含SSE流式."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.writing_chat_schema import (
    WritingChatRequest,
    WritingChatResponse,
)
from src.db.session import get_session, session_scope
from src.services.writing_chat_service import WritingChatService
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


@router.get("/{chapter_id}/history", response_model=list[dict])
async def get_writing_chat_history(
    chapter_id: str, limit: int = 100, session: AsyncSession = Depends(get_session)
):
    """列出章节的 AI 对话历史（按时间正序）."""
    service = WritingChatService(session)
    return await service.list_history(chapter_id, limit=limit)


@router.post("/chat", response_model=WritingChatResponse)
async def writing_chat(req: WritingChatRequest, session: AsyncSession = Depends(get_session)):
    """AI对话式写作辅助."""
    service = WritingChatService(session)
    try:
        return await service.chat(
            req.project_id, req.chapter_id, req.message, req.context_mode, req.user_ideas
        )
    except ValueError as e:
        msg = str(e)
        if "章节不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "不足" in msg:
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"AI超时: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI对话失败: {e}")


@router.post("/chat/stream")
async def writing_chat_stream(req: WritingChatRequest):
    """AI对话式写作辅助 - SSE流式."""
    async def event_stream():
        async with session_scope() as session:
            service = WritingChatService(session)
            try:
                async for chunk in service.stream_chat(
                    req.project_id, req.chapter_id, req.message, req.context_mode, req.user_ideas
                ):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                logger.error(f"SSE writing_chat/chat/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )