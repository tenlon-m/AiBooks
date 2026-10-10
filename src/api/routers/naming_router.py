"""命名生成器路由 - 含SSE流式."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.naming_schema import (
    NamingFavoriteBatchRequest,
    NamingFavoriteDto,
    NamingFavoriteRequest,
    NamingGenerateRequest,
    NamingGenerateResponse,
)
from src.db.session import get_session, session_scope
from src.services.naming_service import NamingService
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


@router.post("/generate", response_model=NamingGenerateResponse)
async def naming_generate(req: NamingGenerateRequest, session: AsyncSession = Depends(get_session)):
    """命名生成."""
    service = NamingService(session)
    try:
        return await service.generate(
            req.project_id, req.name_type, req.count, req.context, req.user_ideas
        )
    except ValueError as e:
        msg = str(e)
        if "不足" in msg:
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"AI超时: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"命名生成失败: {e}")


@router.post("/generate/stream")
async def naming_generate_stream(req: NamingGenerateRequest):
    """命名生成 - SSE流式."""
    async def event_stream():
        async with session_scope() as session:
            service = NamingService(session)
            try:
                async for chunk in service.stream_generate(
                    req.project_id, req.name_type, req.count, req.context, req.user_ideas
                ):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                logger.error(f"SSE naming/generate/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/favorites", response_model=NamingFavoriteDto)
async def add_favorite(req: NamingFavoriteRequest, session: AsyncSession = Depends(get_session)):
    """收藏命名."""
    service = NamingService(session)
    try:
        return await service.add_favorite(req.project_id, req.name_type, req.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"收藏失败: {e}")


@router.post("/{project_id}/favorites")
async def add_favorites_batch(
    project_id: str,
    req: NamingFavoriteBatchRequest,
    session: AsyncSession = Depends(get_session),
):
    """批量收藏命名（重复项自动跳过）."""
    service = NamingService(session)
    try:
        saved = await service.add_favorites_batch(
            project_id, [f.model_dump() for f in req.favorites]
        )
        return {"saved_count": saved}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量收藏失败: {e}")


@router.get("/{project_id}/favorites", response_model=list[NamingFavoriteDto])
async def list_favorites(
    project_id: str,
    name_type: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """列出收藏命名."""
    service = NamingService(session)
    return await service.list_favorites(project_id, name_type)


@router.delete("/{project_id}/favorites/{favorite_id}")
async def remove_favorite(
    project_id: str,
    favorite_id: str,
    session: AsyncSession = Depends(get_session),
):
    """删除收藏命名."""
    service = NamingService(session)
    try:
        deleted = await service.remove_favorite(project_id, favorite_id)
        return {"deleted_count": deleted}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")

@router.post("/{project_id}/import-to-items")
async def import_to_items(
    project_id: str,
    session: AsyncSession = Depends(get_session),
):
    """将命名收藏中的物品/功法类名称导入到物品表."""
    service = NamingService(session)
    try:
        imported = await service.import_to_items(project_id)
        return {"imported_count": imported}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败: {e}")


@router.post("/{project_id}/import-to-characters")
async def import_to_characters(
    project_id: str,
    session: AsyncSession = Depends(get_session),
):
    """将命名收藏中的角色类名称导入到人物管理表."""
    service = NamingService(session)
    try:
        imported = await service.import_to_characters(project_id)
        return {"imported_count": imported}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败: {e}")


@router.post("/{project_id}/append-to-worldview")
async def append_to_worldview(
    project_id: str,
    session: AsyncSession = Depends(get_session),
):
    """将命名收藏中的地点/势力类名称追加到世界观设定."""
    service = NamingService(session)
    try:
        content = await service.append_to_worldview(project_id)
        return {"content": content}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"追加失败: {e}")