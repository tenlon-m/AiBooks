"""角色关系图谱路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.relationship_schema import (
    AutoExtractResult,
    CharacterRelationshipDto,
    RelationshipBatchSaveRequest,
    RelationshipCreateRequest,
    RelationshipGraphDto,
    RelationshipUpdateRequest,
)
from src.db.session import get_session
from src.services.relationship_graph_service import RelationshipGraphService

router = APIRouter()


@router.post("", response_model=CharacterRelationshipDto)
@router.post("/", response_model=CharacterRelationshipDto)
async def create_relationship(
    req: RelationshipCreateRequest, session: AsyncSession = Depends(get_session)
):
    service = RelationshipGraphService(session)
    try:
        return await service.create(req.project_id, req)
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建角色关系失败: {e}")


@router.get("/{project_id}", response_model=RelationshipGraphDto)
async def get_relationship_graph(
    project_id: str, session: AsyncSession = Depends(get_session)
):
    service = RelationshipGraphService(session)
    return await service.get_graph(project_id)


@router.put("/{project_id}")
async def save_relationships(
    project_id: str,
    req: RelationshipBatchSaveRequest,
    session: AsyncSession = Depends(get_session),
):
    """按全量列表批量保存关系（更新/新建/删除缺失项）."""
    service = RelationshipGraphService(session)
    try:
        return await service.save_relations(
            project_id, [r.model_dump() for r in req.relations]
        )
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量保存角色关系失败: {e}")


@router.put("/{project_id}/{relationship_id}", response_model=CharacterRelationshipDto)
async def update_relationship(
    project_id: str,
    relationship_id: str,
    req: RelationshipUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    service = RelationshipGraphService(session)
    try:
        return await service.update(project_id, relationship_id, req)
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新角色关系失败: {e}")


@router.post("/{project_id}/auto_extract", response_model=AutoExtractResult)
async def auto_extract_relationships(
    project_id: str, session: AsyncSession = Depends(get_session)
):
    service = RelationshipGraphService(session)
    try:
        return await service.auto_extract(project_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"自动提取关系失败: {e}")


@router.delete("/{project_id}/{relationship_id}")
async def delete_relationship(
    project_id: str, relationship_id: str, session: AsyncSession = Depends(get_session)
):
    service = RelationshipGraphService(session)
    try:
        deleted = await service.delete(project_id, relationship_id)
        return {"deleted_count": deleted}
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除角色关系失败: {e}")