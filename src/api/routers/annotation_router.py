"""章节注释/批注路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.annotation_schema import (
    AnnotationCreateRequest,
    AnnotationDto,
    AnnotationListResponse,
    AnnotationUpdateRequest,
)
from src.db.session import get_session
from src.services.annotation_service import AnnotationService

router = APIRouter()


@router.post("", response_model=AnnotationDto)
async def create_annotation(
    req: AnnotationCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    service = AnnotationService(session)
    try:
        return await service.create(
            req.chapter_id,
            req.paragraph_index,
            req.content,
            req.annotation_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建批注失败: {e}")


@router.get("/{chapter_id}", response_model=AnnotationListResponse)
async def list_annotations(
    chapter_id: str,
    status: str | None = Query(None, description="状态过滤"),
    session: AsyncSession = Depends(get_session),
):
    service = AnnotationService(session)
    return await service.list_by_chapter(chapter_id, status)


@router.put("/{annotation_id}", response_model=AnnotationDto)
async def update_annotation(
    annotation_id: str,
    req: AnnotationUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    service = AnnotationService(session)
    try:
        return await service.update(annotation_id, req.content, req.status)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新批注失败: {e}")


@router.delete("/{annotation_id}")
async def delete_annotation(
    annotation_id: str,
    session: AsyncSession = Depends(get_session),
):
    service = AnnotationService(session)
    try:
        deleted = await service.delete(annotation_id)
        return {"deleted_count": deleted}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除批注失败: {e}")


@router.patch("/{annotation_id}/invalidate", response_model=AnnotationDto)
async def invalidate_annotation(
    annotation_id: str,
    session: AsyncSession = Depends(get_session),
):
    service = AnnotationService(session)
    try:
        return await service.invalidate(annotation_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"失效批注失败: {e}")