"""校验路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.validation_schema import (
    BatchRevalidateRequest,
    BatchRevalidateResponse,
    FullBookValidationResponse,
)
from src.db.session import get_session
from src.services.validation_service import ValidationService

router = APIRouter()


@router.post("/full_book", response_model=FullBookValidationResponse)
async def validate_full_book(project_id: str, user_ideas: str = "", session: AsyncSession = Depends(get_session)):
    service = ValidationService(session)
    try:
        return await service.validate_full_book(project_id, user_ideas)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"校验失败: {e}")


@router.post("/batch_revalidate", response_model=BatchRevalidateResponse)
async def batch_revalidate(req: BatchRevalidateRequest, session: AsyncSession = Depends(get_session)):
    from src.services.edit_polish_service import EditPolishService
    if len(req.chapter_ids) > 50:
        raise HTTPException(status_code=422, detail="批量再校验最多50章")
    service = EditPolishService(session)
    try:
        return await service.batch_revalidate(req.project_id, req.chapter_ids)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"批量再校验失败: {e}")


@router.get("/{project_id}/results")
async def list_validation_results(
    project_id: str, session: AsyncSession = Depends(get_session)
):
    """列出项目最近一次全书校验结果（校验报告页刷新用）."""
    service = ValidationService(session)
    try:
        return await service.list_latest_results(project_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询校验结果失败: {e}")