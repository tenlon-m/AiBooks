"""大纲管理路由."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.outline_schema import (
    FillAppearingRequest,
    FillAppearingResponse,
    OutlineBatchGenerateRequest,
    OutlineCheckRequest,
    OutlineConsistencyResult,
    OutlineDto,
    OutlineGenerateRequest,
    OutlineRepairRequest,
    OutlineSaveRequest,
    RepairStreamChunk,
)
from src.db.session import get_session, session_scope
from src.services.outline_service import OutlineService
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


def _parse_gc_outline(d: dict | None):
    if d is None:
        return None
    from src.services.garbled_normalizer import GarbledConfig
    return GarbledConfig(**d)


@router.post("/{project_id}/generate", response_model=OutlineDto)
async def generate_outline(
    project_id: str,
    req: OutlineGenerateRequest,
    session: AsyncSession = Depends(get_session),
):
    """AI 生成大纲."""
    service = OutlineService(session)
    try:
        return await service.generate_outline(project_id, req)
    except ValueError as e:
        msg = str(e)
        if "已存在大纲" in msg:
            raise HTTPException(status_code=409, detail=msg)
        if "结构" in msg:
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{project_id}/generate_batch", response_model=OutlineDto)
async def generate_outline_batch(
    project_id: str,
    req: OutlineBatchGenerateRequest,
    session: AsyncSession = Depends(get_session),
):
    """AI 分批生成大纲：每批若干章，返回当前已生成的大纲，可反复调用续写."""
    service = OutlineService(session)
    try:
        return await service.generate_outline_batch(project_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{project_id}/check_consistency", response_model=OutlineConsistencyResult)
async def check_outline_consistency(
    project_id: str,
    req: OutlineCheckRequest,
    session: AsyncSession = Depends(get_session),
):
    """分批校验大纲与梗概/世界观/人物设定的一致性，返回问题清单."""
    service = OutlineService(session)
    try:
        return await service.check_consistency(
            project_id, req, _parse_gc_outline(req.garbled_config),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{project_id}", response_model=OutlineDto | None)
async def get_outline(
    project_id: str,
    session: AsyncSession = Depends(get_session),
):
    """读取大纲."""
    service = OutlineService(session)
    return await service.get_outline(project_id)


@router.put("/{project_id}", response_model=OutlineDto)
async def save_outline(
    project_id: str,
    req: OutlineSaveRequest,
    session: AsyncSession = Depends(get_session),
):
    """保存大纲."""
    service = OutlineService(session)
    try:
        return await service.save_outline(project_id, req)
    except ValueError as e:
        msg = str(e)
        if "结构" in msg:
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{project_id}")
async def delete_outline(
    project_id: str,
    session: AsyncSession = Depends(get_session),
):
    """删除大纲."""
    service = OutlineService(session)
    deleted = await service.delete_outline(project_id)
    return {"deleted": deleted}

@router.post("/{project_id}/fill_appearing", response_model=FillAppearingResponse)
async def fill_appearing(
    project_id: str,
    req: FillAppearingRequest,
    session: AsyncSession = Depends(get_session),
):
    """AI 智能填充出场人物."""
    service = OutlineService(session)
    try:
        return await service.fill_appearing(project_id, req)
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{project_id}/repair/stream")
async def repair_outline_stream(project_id: str, req: OutlineRepairRequest):
    """大纲 AI 一键修复 - SSE 流式，逐章串行，可暂停续写."""
    async def event_stream():
        async with session_scope() as session:
            service = OutlineService(session)
            try:
                async for chunk in service.repair_outline_stream(
                    project_id, req.issues, req.repair_scope,
                    _parse_gc_outline(req.garbled_config),
                ):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                await session.rollback()
                logger.error(f"SSE outline/repair/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )