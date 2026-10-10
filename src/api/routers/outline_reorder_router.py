"""大纲拖拽排序路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.outline_reorder_schema import (
    OutlineReorderRequest,
    OutlineReorderResponse,
)
from src.db.session import get_session
from src.services.outline_reorder_service import OutlineReorderService

router = APIRouter()


@router.post("/reorder", response_model=OutlineReorderResponse)
async def reorder_outline(
    req: OutlineReorderRequest,
    session: AsyncSession = Depends(get_session),
):
    service = OutlineReorderService(session)
    try:
        return await service.reorder(req.project_id, req.new_order)
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"排序失败: {e}")