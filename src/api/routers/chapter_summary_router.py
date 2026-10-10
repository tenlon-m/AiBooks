"""章节摘要自动生成路由 - 含SSE流式."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.chapter_summary_schema import (
    ChapterSummaryBatchRequest,
    ChapterSummaryDto,
    ChapterSummaryGenerateRequest,
)
from src.db.session import get_session, session_scope
from src.services.chapter_summary_service import ChapterSummaryService
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


@router.post("/generate/stream")
async def generate_summary_stream(req: ChapterSummaryGenerateRequest):
    """单章摘要生成 - SSE流式."""
    async def event_stream():
        async with session_scope() as session:
            service = ChapterSummaryService(session)
            try:
                async for chunk in service.generate(req.chapter_id):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                await session.rollback()
                logger.error(f"SSE summary/generate/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/batch/stream")
async def batch_generate_summary_stream(req: ChapterSummaryBatchRequest):
    """批量章节摘要生成 - SSE流式，可暂停续写."""
    async def event_stream():
        async with session_scope() as session:
            service = ChapterSummaryService(session)
            try:
                async for chunk in service.batch_generate(req.project_id, req.chapter_ids):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                await session.rollback()
                logger.error(f"SSE summary/batch/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/{chapter_id}", response_model=ChapterSummaryDto | None)
async def get_chapter_summary(
    chapter_id: str, session: AsyncSession = Depends(get_session)
):
    service = ChapterSummaryService(session)
    try:
        return await service.get_summary(chapter_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取章节摘要失败: {e}")