"""爽点钩子路由."""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.hook_schema import (
    AiDesignHooksRequest,
    AiDesignHooksResponse,
    BatchDeleteCoolPointsRequest,
    BatchDeleteHooksRequest,
    ChapterHookDto,
    CoolPointDto,
    HookChapterGenerateRequest,
    HookConsistencyResult,
    HookDto,
    HookRepairRequest,
    SaveCoolPointsRequest,
    SaveHooksRequest,
)
from src.db.session import get_session, session_scope
from src.services.hook_service import HookService
from src.services.operation_lock import get_running_op, release_op, try_set_op
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


def _parse_gc_hook(d: dict | None):
    if d is None:
        return None
    from src.services.garbled_normalizer import GarbledConfig
    return GarbledConfig(**d)


@router.post("/ai_design", response_model=AiDesignHooksResponse)
async def ai_design_hooks(req: AiDesignHooksRequest, session: AsyncSession = Depends(get_session)):
    service = HookService(session)
    try:
        response = await service.ai_design(
            req.project_id, req.synopsis, req.worldview, req.characters, req.chapter_plan, req.user_ideas
        )
        await service.save_cool_points(req.project_id, response.cool_points)
        await service.save_hooks(req.project_id, response.hooks)
        return response
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI设计失败: {e}")


@router.get("/{project_id}/cool_points", response_model=list[CoolPointDto])
async def list_cool_points(project_id: str, session: AsyncSession = Depends(get_session)):
    service = HookService(session)
    return await service.list_cool_points(project_id)


@router.get("/{project_id}/hooks", response_model=list[HookDto])
async def list_hooks(project_id: str, session: AsyncSession = Depends(get_session)):
    service = HookService(session)
    return await service.list_hooks(project_id)


@router.post("/{project_id}/generate_chapter", response_model=ChapterHookDto)
async def generate_chapter_hook(
    project_id: str,
    req: HookChapterGenerateRequest,
    session: AsyncSession = Depends(get_session),
):
    """逐章生成爽点钩子."""
    service = HookService(session)
    try:
        return await service.generate_chapter_outline(
            project_id, req.volume_no, req.chapter_no, req.prev_context, req.user_ideas
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"AI超时: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{project_id}/progress_chapter")
async def get_chapter_progress(
    project_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取逐章生成进度."""
    service = HookService(session)
    return await service.get_generation_progress(project_id)

@router.delete("/{project_id}/cool_points")
async def batch_delete_cool_points(
    project_id: str,
    req: BatchDeleteCoolPointsRequest,
    session: AsyncSession = Depends(get_session),
):
    """批量删除爽点."""
    service = HookService(session)
    try:
        deleted = await service.delete_cool_points(project_id, req.cool_ids)
        return {"deleted_count": deleted}
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量删除爽点失败: {e}")


@router.delete("/{project_id}/hooks")
async def batch_delete_hooks(
    project_id: str,
    req: BatchDeleteHooksRequest,
    session: AsyncSession = Depends(get_session),
):
    """批量删除钩子."""
    service = HookService(session)
    try:
        deleted = await service.delete_hooks(project_id, req.hook_ids)
        return {"deleted_count": deleted}
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量删除钩子失败: {e}")


@router.put("/{project_id}/cool_points", response_model=list[CoolPointDto])
async def save_cool_points(
    project_id: str,
    req: SaveCoolPointsRequest,
    session: AsyncSession = Depends(get_session),
):
    """覆盖式保存爽点列表."""
    service = HookService(session)
    try:
        return await service.save_cool_points_batch(project_id, req.cool_points)
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存爽点失败: {e}")


@router.put("/{project_id}/hooks", response_model=list[HookDto])
async def save_hooks(
    project_id: str,
    req: SaveHooksRequest,
    session: AsyncSession = Depends(get_session),
):
    """覆盖式保存钩子列表."""
    service = HookService(session)
    try:
        return await service.save_hooks_batch(project_id, req.hooks)
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存钩子失败: {e}")


@router.post("/{project_id}/check_consistency", response_model=HookConsistencyResult)
async def check_hook_consistency(
    project_id: str,
    garbled_config: dict | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
):
    """校验爽点钩子一致性."""
    service = HookService(session)
    try:
        from src.services.garbled_normalizer import GarbledConfig
        gc = GarbledConfig(**garbled_config) if garbled_config else None
        return await service.check_consistency(project_id, gc)
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"一致性校验超时: {e}")


@router.post("/{project_id}/repair/stream")
async def repair_hook_stream(project_id: str, req: HookRepairRequest):
    """爽点钩子 AI 一键修复 - SSE 流式，逐章串行."""
    async def event_stream():
        if not try_set_op(project_id, "repair"):
            existing = get_running_op(project_id) or "未知"
            yield f"data: {json.dumps({'type': 'error', 'message': f'项目已有操作进行中（{existing}），无法启动钩子修复'})}\n\n"
            return
        async with session_scope() as session:
            service = HookService(session)
            try:
                async for chunk in service.repair_hook_stream(
                    project_id, req.issues, req.repair_scope,
                    _parse_gc_hook(req.garbled_config),
                ):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                await session.rollback()
                logger.error(f"SSE hook/repair/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"
            finally:
                release_op(project_id, "repair")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
