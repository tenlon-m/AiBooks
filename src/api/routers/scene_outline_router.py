"""场景级大纲细化路由 - 含SSE流式与批量细化."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.scene_outline_schema import (
    BatchSceneSplitRequest,
    SceneDto,
    SceneSplitRequest,
    SceneSplitResponse,
    SceneUpdateRequest,
)
from src.db.session import get_session, session_scope
from src.services.scene_outline_service import SceneOutlineService
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


@router.post("/split", response_model=SceneSplitResponse)
async def scene_split(req: SceneSplitRequest, session: AsyncSession = Depends(get_session)):
    """场景级大纲细化."""
    service = SceneOutlineService(session)
    try:
        return await service.split(req.project_id, req.chapter_id, req.target_words, req.user_ideas)
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
        raise HTTPException(status_code=502, detail=f"场景细化失败: {e}")


@router.post("/split/stream")
async def scene_split_stream(req: SceneSplitRequest):
    """场景级大纲细化 - SSE流式."""
    async def event_stream():
        from src.db.session import session_scope
        async with session_scope() as session:
            service = SceneOutlineService(session)
            try:
                async for chunk in service.stream_split(
                    req.project_id, req.chapter_id, req.target_words, req.user_ideas
                ):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                await session.rollback()
                logger.error(f"SSE scene/split/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/batch/stream")
async def batch_scene_split_stream(req: BatchSceneSplitRequest):
    """批量场景级大纲细化 - SSE流式，逐章串行，可暂停续写."""
    async def event_stream():
        async with session_scope() as session:
            service = SceneOutlineService(session)
            try:
                async for chunk in service.batch_stream_split(
                    req.project_id, req.target_words, req.user_ideas
                ):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                await session.rollback()
                logger.error(f"SSE scene/batch/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/{chapter_id}/scenes", response_model=list[SceneDto])
async def list_scenes(chapter_id: str, session: AsyncSession = Depends(get_session)):
    """列出章节已有场景."""
    service = SceneOutlineService(session)
    return await service.list_scenes(chapter_id)


@router.put("/{scene_id}", response_model=SceneDto)
async def update_scene(
    scene_id: str,
    req: SceneUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """更新单个场景."""
    service = SceneOutlineService(session)
    try:
        return await service.update_scene(scene_id, req)
    except ValueError as e:
        msg = str(e)
        if "场景不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新场景失败: {e}")


@router.delete("/{scene_id}")
async def delete_scene(scene_id: str, session: AsyncSession = Depends(get_session)):
    """删除单个场景."""
    service = SceneOutlineService(session)
    try:
        deleted = await service.delete_scene(scene_id)
        return {"deleted_count": deleted}
    except ValueError as e:
        msg = str(e)
        if "场景不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除场景失败: {e}")