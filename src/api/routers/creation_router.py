"""创作参数路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.creation_schema import (
    CreationParamsRequest,
    CreationParamsResponse,
    CreationPolishRequest,
    CreationPolishResponse,
    ProjectDto,
    ProjectSaveRequest,
    ProjectSaveResponse,
    ProjectSummaryDto,
    SynopsisRequest,
    SynopsisResponse,
    WorldviewRequest,
    WorldviewResponse,
)
from src.api.utils.retry import retry_on_locked
from src.db.session import get_session
from src.services.creation_polish_service import CreationPolishService
from src.services.creation_service import CreationService

router = APIRouter()


@router.post("/params", response_model=CreationParamsResponse)
async def create_params(req: CreationParamsRequest, session: AsyncSession = Depends(get_session)):
    service = CreationService(session)
    try:
        return await service.create_project(req)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("", response_model=list[ProjectDto])
async def list_projects(session: AsyncSession = Depends(get_session)):
    service = CreationService(session)
    return await service.list_projects()


@router.get("/summaries", response_model=list[ProjectSummaryDto])
async def list_project_summaries(session: AsyncSession = Depends(get_session)):
    service = CreationService(session)
    return await service.list_project_summaries()


@router.get("/{project_id}", response_model=ProjectDto)
async def get_project(project_id: str, session: AsyncSession = Depends(get_session)):
    service = CreationService(session)
    dto = await service.get_project(project_id)
    if not dto:
        raise HTTPException(status_code=404, detail="项目不存在")
    return dto


@router.delete("/{project_id}")
async def delete_project(project_id: str, session: AsyncSession = Depends(get_session)):
    service = CreationService(session)
    try:
        ok = await service.delete_project(project_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"message": "已删除"}


@router.put("/{project_id}/synopsis", response_model=SynopsisResponse)
async def set_synopsis(project_id: str, req: SynopsisRequest, session: AsyncSession = Depends(get_session)):
    service = CreationService(session)
    try:
        return await service.set_synopsis(project_id, req.content, req.source)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{project_id}/synopsis", response_model=SynopsisResponse)
async def get_synopsis(project_id: str, session: AsyncSession = Depends(get_session)):
    service = CreationService(session)
    dto = await service.get_synopsis(project_id)
    if not dto:
        raise HTTPException(status_code=404, detail="梗概不存在")
    return dto


@router.put("/{project_id}/worldview", response_model=WorldviewResponse)
async def set_worldview(project_id: str, req: WorldviewRequest, session: AsyncSession = Depends(get_session)):
    service = CreationService(session)
    try:
        return await service.set_worldview(project_id, req.content, req.source)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{project_id}/worldview", response_model=WorldviewResponse)
async def get_worldview(project_id: str, session: AsyncSession = Depends(get_session)):
    service = CreationService(session)
    dto = await service.get_worldview(project_id)
    if not dto:
        raise HTTPException(status_code=404, detail="世界观不存在")
    return dto

@router.post("/save", response_model=ProjectSaveResponse)
@retry_on_locked(max_attempts=3, base_delay=0.5)
async def save_project(req: ProjectSaveRequest, session: AsyncSession = Depends(get_session)):
    """关键节点保存：自动重试一次 SQLite 锁冲突.

    关键节点保存通常由前端 key_node 信号触发（章节完成、大纲生成等），
    与后台写作 / 大纲批次服务可能同时写 synopses/worldview/projects，
    撞 SQLite 写锁时最多 3 次指数退避重试，避免偶发的 500 破坏用户感知。
    """
    service = CreationService(session)
    try:
        return await service.save_project(req)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

@router.post("/{project_id}/polish", response_model=CreationPolishResponse)
async def polish_creation(project_id: str, req: CreationPolishRequest, session: AsyncSession = Depends(get_session)):
    target_label = "故事梗概" if req.target == "synopsis" else "世界观"
    service = CreationPolishService(session)
    try:
        from src.services.garbled_normalizer import GarbledConfig
        gc = GarbledConfig(**req.garbled_config) if req.garbled_config else None
        return await service.polish_creation(project_id, req, gc)
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except TimeoutError:
        raise HTTPException(status_code=504, detail=f"{target_label}润色超时，请重试或检查 AI 模型配置")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"{target_label}润色失败：{e}")