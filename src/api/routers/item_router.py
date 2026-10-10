"""物品管理路由 - 物品清单增删改查 + 全书一致性检查."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.item_schema import (
    ItemConsistencyResponse,
    ItemCreateRequest,
    ItemDto,
    ItemUpdateRequest,
)
from src.db.session import get_session
from src.services.item_service import ItemService

router = APIRouter()


@router.get("/{project_id}", response_model=list[ItemDto])
async def list_items(
    project_id: str, session: AsyncSession = Depends(get_session)
):
    """列出项目全部物品."""
    service = ItemService(session)
    return await service.list_by_project(project_id)


@router.post("", response_model=ItemDto)
@router.post("/", response_model=ItemDto)
async def create_item(
    req: ItemCreateRequest, session: AsyncSession = Depends(get_session)
):
    """新增物品."""
    service = ItemService(session)
    try:
        return await service.create(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # 物品名在 (project_id, name) 上有唯一约束，重名会走到这里
        raise HTTPException(status_code=400, detail=f"新增物品失败: {e}")


@router.put("/{item_id}", response_model=ItemDto)
async def update_item(
    item_id: str, req: ItemUpdateRequest, session: AsyncSession = Depends(get_session)
):
    """更新物品."""
    service = ItemService(session)
    try:
        return await service.update(item_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"更新物品失败: {e}")


@router.delete("/{item_id}")
async def delete_item(item_id: str, session: AsyncSession = Depends(get_session)):
    """删除物品."""
    service = ItemService(session)
    try:
        deleted = await service.delete(item_id)
        return {"deleted_count": deleted}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"删除物品失败: {e}")


@router.get("/{project_id}/consistency", response_model=ItemConsistencyResponse)
async def check_item_consistency(
    project_id: str, session: AsyncSession = Depends(get_session)
):
    """检查物品全书一致性（同名不同类型等）."""
    service = ItemService(session)
    return ItemConsistencyResponse(problems=await service.check_consistency(project_id))
