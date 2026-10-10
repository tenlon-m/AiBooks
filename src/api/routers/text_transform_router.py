"""续写/扩写/缩写路由 - 含SSE流式."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.text_transform_schema import (
    TextTransformRequest,
    TextTransformResponse,
)
from src.db.session import get_session, session_scope
from src.services.text_transform_service import TextTransformService
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


@router.post("/{scene}", response_model=TextTransformResponse)
async def text_transform(
    scene: Literal["continue", "expand", "shrink"],
    req: TextTransformRequest,
    session: AsyncSession = Depends(get_session),
):
    """续写/扩写/缩写文本."""
    service = TextTransformService(session)
    try:
        return await service.transform(
            req.project_id, scene, req.content, req.chapter_id,
            req.direction, req.target_words, req.user_ideas,
        )
    except ValueError as e:
        msg = str(e)
        if "不足" in msg:
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"AI超时: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"文本处理失败: {e}")


@router.post("/{scene}/stream")
async def text_transform_stream(
    scene: Literal["continue", "expand", "shrink"],
    req: TextTransformRequest,
):
    """续写/扩写/缩写文本 - SSE流式."""
    async def event_stream():
        async with session_scope() as session:
            service = TextTransformService(session)
            try:
                async for chunk in service.stream_transform(
                    req.project_id, scene, req.content, req.chapter_id,
                    req.direction, req.target_words, req.user_ideas,
                ):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                logger.error(f"SSE text_transform/{scene}/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )