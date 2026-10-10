"""迭代生成路由 - SSE流式进度."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.iteration_schema import IterationStartRequest
from src.db.session import get_session, session_scope
from src.services.iteration_service import IterationService
from src.services.operation_lock import get_running_op, release_op, try_set_op
from src.utils.logger import get_logger

logger = get_logger()

router = APIRouter()

_iteration_tasks: dict[str, IterationService] = {}


@router.post("/start")
async def start_iteration(req: IterationStartRequest):
    """启动迭代生成 - SSE 流式推送每轮进度."""

    async def event_generator():
        if not try_set_op(req.project_id, "iteration"):
            existing = get_running_op(req.project_id) or "未知"
            yield f"data: {json.dumps({'type': 'error', 'message': f'项目已有操作进行中（{existing}），无法启动迭代'})}\n\n"
            return
        service: IterationService | None = None
        async with session_scope() as session:
            service = IterationService(session)
            try:
                async for event in service.start_iteration(
                    req.project_id,
                    req.iteration_unit,
                    req.target_id,
                    req.total_rounds,
                ):
                    if (
                        service._iteration_id
                        and service._iteration_id not in _iteration_tasks
                    ):
                        _iteration_tasks[service._iteration_id] = service
                    yield f"data: {event.model_dump_json()}\n\n"
            except ValueError as e:
                logger.error(
                    f"SSE iteration/start 异常(ValueError): {e}", exc_info=True
                )
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            except Exception as e:
                logger.error(f"SSE iteration/start 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'迭代异常: {e}'})}\n\n"
            finally:
                if service and service._iteration_id:
                    _iteration_tasks.pop(service._iteration_id, None)
                release_op(req.project_id, "iteration")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/{iteration_id}/pause")
async def pause_iteration(
    iteration_id: str, session: AsyncSession = Depends(get_session)
):
    """暂停迭代生成."""
    service = _iteration_tasks.get(iteration_id)
    if service:
        service._paused = True
    svc = IterationService(session)
    try:
        paused = await svc.pause_iteration(iteration_id)
        return {"message": "已暂停", "paused": paused}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{iteration_id}/resume")
async def resume_iteration(iteration_id: str):
    """续传迭代生成 - SSE 流式."""

    async def event_generator():
        service: IterationService | None = None
        async with session_scope() as session:
            service = IterationService(session)
            _iteration_tasks[iteration_id] = service
            try:
                async for event in service.resume_iteration(iteration_id):
                    yield f"data: {event.model_dump_json()}\n\n"
            except ValueError as e:
                logger.error(
                    f"SSE iteration/resume 异常(ValueError): {e}", exc_info=True
                )
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            except Exception as e:
                logger.error(f"SSE iteration/resume 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'续传异常: {e}'})}\n\n"
            finally:
                _iteration_tasks.pop(iteration_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/history/{target_id}")
async def list_iterations(
    target_id: str, session: AsyncSession = Depends(get_session)
):
    """查询目标的迭代历史."""
    service = IterationService(session)
    return await service.list_iterations(target_id)


@router.post("/{iteration_id}/adopt/{round_no}")
async def adopt_iteration(
    iteration_id: str,
    round_no: int,
    session: AsyncSession = Depends(get_session),
):
    """采纳指定轮次的迭代输出为章节正文."""
    service = IterationService(session)
    try:
        return await service.adopt_iteration(iteration_id, round_no)
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg or "未找到" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=422, detail=msg)