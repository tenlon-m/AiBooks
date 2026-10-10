"""时间线管理路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.timeline_schema import (
    TimelineCreateRequest,
    TimelineNodeDto,
    TimelineReorderRequest,
    TimelineReorderResult,
    TimelineUpdateRequest,
)
from src.db.session import get_session
from src.services.timeline_service import TimelineService

router = APIRouter()


@router.post("", response_model=TimelineNodeDto)
@router.post("/", response_model=TimelineNodeDto)
async def create_timeline_node(
    req: TimelineCreateRequest, session: AsyncSession = Depends(get_session)
):
    service = TimelineService(session)
    try:
        return await service.create_node(req.project_id, req)
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建时间线节点失败: {e}")


@router.get("/{project_id}", response_model=list[TimelineNodeDto])
async def list_timeline_nodes(project_id: str, session: AsyncSession = Depends(get_session)):
    service = TimelineService(session)
    return await service.list_nodes(project_id)


@router.put("/{project_id}/{node_id}", response_model=TimelineNodeDto)
async def update_timeline_node(
    project_id: str,
    node_id: str,
    req: TimelineUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    service = TimelineService(session)
    try:
        return await service.update_node(project_id, node_id, req)
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新时间线节点失败: {e}")


@router.get("/{project_id}/conflicts")
async def check_timeline_conflicts(
    project_id: str, session: AsyncSession = Depends(get_session)
):
    """检测项目时间线的时序冲突（角色死亡后仍出现等）."""
    service = TimelineService(session)
    nodes = await service.list_nodes(project_id)
    return {"conflicts": TimelineService._detect_temporal_conflicts(nodes)}


@router.post("/{project_id}/reorder", response_model=TimelineReorderResult)
async def reorder_timeline(
    project_id: str,
    req: TimelineReorderRequest,
    session: AsyncSession = Depends(get_session),
):
    service = TimelineService(session)
    try:
        return await service.reorder(project_id, req.node_orders)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"时间线重排失败: {e}")


@router.delete("/{project_id}/{node_id}")
async def delete_timeline_node(
    project_id: str, node_id: str, session: AsyncSession = Depends(get_session)
):
    service = TimelineService(session)
    try:
        deleted = await service.delete_node(project_id, node_id)
        return {"deleted_count": deleted}
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除时间线节点失败: {e}")