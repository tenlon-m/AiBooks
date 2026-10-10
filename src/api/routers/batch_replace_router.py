"""批量查找替换路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.batch_replace_schema import (
    BatchReplaceExecuteRequest,
    BatchReplaceExecuteResponse,
    BatchReplacePreviewRequest,
    BatchReplacePreviewResponse,
)
from src.db.session import get_session
from src.services._chapter_guard import ChapterLockedError
from src.services.batch_replace_service import BatchReplaceService

router = APIRouter()


@router.post("/preview", response_model=BatchReplacePreviewResponse)
async def preview_replace(
    req: BatchReplacePreviewRequest,
    session: AsyncSession = Depends(get_session),
):
    service = BatchReplaceService(session)
    try:
        return await service.preview(req)
    except ValueError as e:
        msg = str(e)
        if "项目不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "正则" in msg:
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"预览失败: {e}")


@router.post("/execute", response_model=BatchReplaceExecuteResponse)
async def execute_replace(
    req: BatchReplaceExecuteRequest,
    session: AsyncSession = Depends(get_session),
):
    service = BatchReplaceService(session)
    try:
        return await service.execute(req.preview_id, req.confirmed_indices)
    except ChapterLockedError as e:
        raise HTTPException(status_code=409, detail="章节已锁定，请先解锁")
    except ValueError as e:
        msg = str(e)
        if "正则" in msg:
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"替换失败: {e}")