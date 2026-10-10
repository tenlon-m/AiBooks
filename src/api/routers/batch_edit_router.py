"""批量提取/改写路由 - 含SSE流式进度."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.batch_edit_schema import (
    BatchRewriteRequest,
    ExtractRequest,
    ExtractResultDto,
)
from src.db.session import get_session, session_scope
from src.services.batch_edit_service import BatchEditService
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


@router.post("/extract", response_model=ExtractResultDto)
async def batch_extract(
    req: ExtractRequest, session: AsyncSession = Depends(get_session)
):
    """批量提取 - 按角色/地点检索相关章节片段."""
    service = BatchEditService(session)
    try:
        if req.dimension == "角色":
            return await service.extract_by_character(
                req.project_id, req.target_name
            )
        return await service.extract_by_place(req.project_id, req.target_name)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"AI超时: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"批量提取失败: {e}")


@router.post("/rewrite")
async def batch_rewrite(req: BatchRewriteRequest):
    """批量改写 - SSE流式进度."""
    async def event_stream():
        async with session_scope() as session:
            service = BatchEditService(session)
            try:
                async for event in service.batch_rewrite(
                    req.chapter_ids, req.instruction
                ):
                    yield f"data: {event.model_dump_json()}\n\n"
            except Exception as e:
                logger.error(
                    f"SSE batch-edit/rewrite 异常: {e}", exc_info=True
                )
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/expand")
async def batch_expand(req: BatchRewriteRequest):
    """批量扩写 - SSE流式进度."""
    async def event_stream():
        async with session_scope() as session:
            service = BatchEditService(session)
            try:
                async for event in service.batch_expand(
                    req.chapter_ids, req.instruction
                ):
                    yield f"data: {event.model_dump_json()}\n\n"
            except Exception as e:
                logger.error(
                    f"SSE batch-edit/expand 异常: {e}", exc_info=True
                )
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )