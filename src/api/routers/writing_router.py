"""批量撰写路由 - 含SSE流式进度."""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Project

from src.utils.logger import get_logger
logger = get_logger()

from src.api.schemas.writing_schema import (
    ChapterDto,
    SaveWritingRequest,
    StartWritingRequest,
    WritingConsistencyResult,
    WritingRepairRequest,
)
from src.db.session import get_session, session_scope
from src.services.operation_lock import get_running_op, release_op, try_set_op
from src.services.writing_service import WritingService
from src.services.garbled_normalizer import GarbledConfig


def _parse_gc(d: dict | None) -> GarbledConfig | None:
    if d is None:
        return None
    return GarbledConfig(**d)

router = APIRouter()

_writing_tasks: dict[str, WritingService] = {}


@router.post("/start")
async def start_writing(req: StartWritingRequest, session: AsyncSession = Depends(get_session)):
    existing = get_running_op(req.project_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"项目已有操作进行中（{existing}），请等待完成后再启动")
    service = WritingService(session)
    _writing_tasks[req.project_id] = service
    return {"message": "撰写已启动", "project_id": req.project_id}


@router.post("/pause")
async def pause_writing(project_id: str, session: AsyncSession = Depends(get_session)):
    service = _writing_tasks.get(project_id)
    if service:
        service.pause()
    writing_service = WritingService(session)
    await writing_service.pause_writing(project_id)
    return {"message": "已暂停", "paused": True}


@router.post("/resume")
async def resume_writing(project_id: str, user_ideas: str = "", session: AsyncSession = Depends(get_session)):
    service = _writing_tasks.get(project_id)
    if service:
        service.resume()
    writing_service = WritingService(session)
    await writing_service.resume_writing(project_id, user_ideas)
    return {"message": "已恢复", "resumed": True}


@router.get("/{project_id}/progress")
async def writing_progress(
    project_id: str,
    style_library_id: str | None = None,
    user_ideas: str = "",
    proofread_mode: str = "off",
    proofread_sources: str | None = None,
):
    """SSE 流式推送撰写进度."""
    async def event_generator():
        from src.db.session import session_scope
        if not try_set_op(project_id, "writing"):
            existing = get_running_op(project_id) or "未知"
            yield f"data: {json.dumps({'status': 'failed', 'message': f'项目已有操作进行中（{existing}），无法启动撰写'})}\n\n"
            return
        async with session_scope() as session:
            service = WritingService(session)
            _writing_tasks[project_id] = service
            try:
                sources: dict | None = None
                if proofread_sources:
                    try:
                        sources = json.loads(proofread_sources)
                    except json.JSONDecodeError:
                        sources = None
                async for event in service.start_writing(
                    project_id, style_library_id, user_ideas=user_ideas,
                    proofread_mode=proofread_mode, proofread_sources=sources,
                ):
                    data = event.model_dump_json()
                    yield f"data: {data}\n\n"
            except ValueError as e:
                logger.error(f"SSE writing/progress 异常(ValueError): {e}", exc_info=True)
                yield f"data: {json.dumps({'status': 'failed', 'message': str(e)})}\n\n"
            except Exception as e:
                logger.error(f"SSE writing/progress 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'status': 'failed', 'message': f'撰写异常: {e}'})}\n\n"
            finally:
                _writing_tasks.pop(project_id, None)
                release_op(project_id, "writing")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.put("/{project_id}/save")
async def save_writing(
    project_id: str,
    req: SaveWritingRequest,
    session: AsyncSession = Depends(get_session),
):
    """批量保存已撰写章节内容."""
    service = WritingService(session)
    try:
        saved = await service.save_chapters_batch(project_id, req.chapters)
        return {"saved_count": saved}
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "章节不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "章节内容不能为空" in msg:
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except Exception as e:
        if "章节已锁定" in str(e):
            raise HTTPException(status_code=409, detail="章节已锁定，请先解锁")
        raise HTTPException(status_code=500, detail=f"批量保存章节失败: {e}")


@router.post("/{project_id}/check_consistency", response_model=WritingConsistencyResult)
async def check_writing_consistency(
    project_id: str,
    user_ideas: str = "",
    garbled_config: dict | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
):
    """校验已撰写章节与大纲/风格库的一致性."""
    service = WritingService(session)
    try:
        return await service.check_consistency(
            project_id, user_ideas, _parse_gc(garbled_config)
        )
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "无已撰写章节" in msg:
            raise HTTPException(status_code=422, detail=msg)
        if "大纲不存在" in msg:
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"一致性校验超时: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI校验失败: {e}")


@router.get("/{project_id}/chapters", response_model=list[ChapterDto])
async def list_chapters(project_id: str, session: AsyncSession = Depends(get_session)):
    service = WritingService(session)
    chapters = await service.list_chapters(project_id)
    project = (
        await session.execute(select(Project).where(Project.project_id == project_id))
    ).scalars().first()
    words_per_chapter = project.words_per_chapter if project else 0
    if words_per_chapter <= 0:
        logger.warning("项目 %s 的 words_per_chapter=%s，跳过字数不足判定", project_id, words_per_chapter)
    return [
        ChapterDto(
            chapter_id=c.chapter_id,
            project_id=c.project_id,
            volume_no=c.volume_no,
            chapter_no=c.chapter_no,
            title=c.title,
            content=c.content,
            word_count=c.word_count,
            gen_status=c.gen_status,
            modify_status=c.modify_status,
            summary=c.summary.summary if c.summary else None,
            words_per_chapter=words_per_chapter,
            underfilled=(
                service.is_word_underfilled(c.word_count, words_per_chapter)
                if (c.gen_status == "completed" and c.content and words_per_chapter > 0)
                else False
            ),
        )
        for c in chapters
    ]


@router.get("/{project_id}/op_status")
async def get_op_status(project_id: str):
    """查询项目当前操作状态."""
    op = get_running_op(project_id)
    return {"running_op": op, "is_busy": op is not None}

@router.post("/{project_id}/repair/stream")
async def repair_writing_stream(project_id: str, req: WritingRepairRequest):
    """撰写 AI 一键修复 - SSE 流式，逐章串行."""
    async def event_stream():
        if not try_set_op(project_id, "repair"):
            existing = get_running_op(project_id) or "未知"
            yield f"data: {json.dumps({'type': 'error', 'message': f'项目已有操作进行中（{existing}），无法启动修复'})}\n\n"
            return
        async with session_scope() as session:
            service = WritingService(session)
            try:
                async for chunk in service.repair_writing_stream(
                    project_id, req.issues, req.repair_scope,
                    _parse_gc(req.garbled_config),
                ):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                await session.rollback()
                logger.error(f"SSE writing/repair/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"
            finally:
                release_op(project_id, "repair")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ── 乱码修复配置端点 ──────────────────────────────────────────

from src.api.schemas.garbled_schema import GarbledConfigSchema, GarbledConfigSaveRequest
from src.services.garbled_config_service import GarbledConfigService


@router.get("/garbled-config/global", response_model=GarbledConfigSchema)
async def get_garbled_config_global(session: AsyncSession = Depends(get_session)):
    svc = GarbledConfigService(session)
    model = await svc.get_config("global", None)
    if model:
        return GarbledConfigSchema(
            enabled=model.enabled if model.enabled is not None else True,
            max_blank_lines=model.max_blank_lines if model.max_blank_lines is not None else 1,
            max_punct_repeat=model.max_punct_repeat if model.max_punct_repeat is not None else 2,
            max_consecutive_spaces=model.max_consecutive_spaces if model.max_consecutive_spaces is not None else 1,
            enable_fullwidth_indent=model.enable_fullwidth_indent if model.enable_fullwidth_indent is not None else True,
            enable_punct_repeat_fix=model.enable_punct_repeat_fix if model.enable_punct_repeat_fix is not None else True,
            enable_whitespace_cleanup=model.enable_whitespace_cleanup if model.enable_whitespace_cleanup is not None else True,
            enable_irreversible_clear=model.enable_irreversible_clear if model.enable_irreversible_clear is not None else True,
        )
    return GarbledConfigSchema()


@router.put("/garbled-config/global", response_model=GarbledConfigSchema)
async def put_garbled_config_global(
    req: GarbledConfigSaveRequest, session: AsyncSession = Depends(get_session),
):
    svc = GarbledConfigService(session)
    cfg = GarbledConfig(
        enabled=req.enabled if req.enabled is not None else True,
        max_blank_lines=req.max_blank_lines if req.max_blank_lines is not None else 1,
        max_punct_repeat=req.max_punct_repeat if req.max_punct_repeat is not None else 2,
        max_consecutive_spaces=req.max_consecutive_spaces if req.max_consecutive_spaces is not None else 1,
        enable_fullwidth_indent=req.enable_fullwidth_indent if req.enable_fullwidth_indent is not None else True,
        enable_punct_repeat_fix=req.enable_punct_repeat_fix if req.enable_punct_repeat_fix is not None else True,
        enable_whitespace_cleanup=req.enable_whitespace_cleanup if req.enable_whitespace_cleanup is not None else True,
        enable_irreversible_clear=req.enable_irreversible_clear if req.enable_irreversible_clear is not None else True,
    )
    await svc.save_config("global", None, cfg)
    await session.commit()
    return GarbledConfigSchema(**cfg.model_dump())


@router.get("/garbled-config/project/{project_id}", response_model=GarbledConfigSchema)
async def get_garbled_config_project(
    project_id: str, session: AsyncSession = Depends(get_session),
):
    svc = GarbledConfigService(session)
    return await svc.resolve_effective_config(project_id)


@router.put("/garbled-config/project/{project_id}", response_model=GarbledConfigSchema)
async def put_garbled_config_project(
    project_id: str,
    req: GarbledConfigSaveRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = GarbledConfigService(session)
    cfg = GarbledConfig(
        enabled=req.enabled if req.enabled is not None else True,
        max_blank_lines=req.max_blank_lines if req.max_blank_lines is not None else 1,
        max_punct_repeat=req.max_punct_repeat if req.max_punct_repeat is not None else 2,
        max_consecutive_spaces=req.max_consecutive_spaces if req.max_consecutive_spaces is not None else 1,
        enable_fullwidth_indent=req.enable_fullwidth_indent if req.enable_fullwidth_indent is not None else True,
        enable_punct_repeat_fix=req.enable_punct_repeat_fix if req.enable_punct_repeat_fix is not None else True,
        enable_whitespace_cleanup=req.enable_whitespace_cleanup if req.enable_whitespace_cleanup is not None else True,
        enable_irreversible_clear=req.enable_irreversible_clear if req.enable_irreversible_clear is not None else True,
    )
    await svc.save_config("project", project_id, cfg)
    await session.commit()
    return GarbledConfigSchema(**cfg.model_dump())

@router.post("/{project_id}/fill/stream")
async def fill_writing_stream(
    project_id: str,
    garbled_config: dict | None = Body(default=None),
):
    """批量补写字数不足章节 - SSE 流式，逐章串行."""
    async def event_stream():
        if not try_set_op(project_id, "fill"):
            existing = get_running_op(project_id) or "未知"
            yield f"data: {json.dumps({'type': 'error', 'message': f'项目已有操作进行中（{existing}），无法启动补写'})}\n\n"
            return
        async with session_scope() as session:
            service = WritingService(session)
            try:
                async for chunk in service.fill_writing_stream(
                    project_id, _parse_gc(garbled_config),
                ):
                    yield f"data: {chunk.model_dump_json()}\n\n"
            except Exception as e:
                await session.rollback()
                logger.error(f"SSE writing/fill/stream 异常: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': f'异常: {e}'})}\n\n"
            finally:
                release_op(project_id, "fill")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )