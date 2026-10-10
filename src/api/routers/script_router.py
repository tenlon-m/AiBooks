"""AI写剧本路由."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.script_schema import (
    ScriptEpisodeDto,
    ScriptExportRequest,
    ScriptGenerateRequest,
)
from src.db.session import get_session, session_scope
from src.services.script_service import ScriptService
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


@router.post("/generate")
async def generate_script(req: ScriptGenerateRequest):
    async def event_stream():
        async with session_scope() as session:
            service = ScriptService(session)
            try:
                async for event in service.generate_script(req.project_id):
                    yield f"data: {event.model_dump_json()}\n\n"
            except Exception as e:
                await session.rollback()
                logger.error(f"SSE script/generate 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/episodes/{project_id}", response_model=list[ScriptEpisodeDto])
async def list_episodes(
    project_id: str,
    session: AsyncSession = Depends(get_session),
):
    service = ScriptService(session)
    return await service.list_episodes(project_id)


@router.post("/export")
async def export_script(
    req: ScriptExportRequest,
    session: AsyncSession = Depends(get_session),
):
    service = ScriptService(session)
    try:
        return await service.export_script(req.project_id, req.target_dir, req.format)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))