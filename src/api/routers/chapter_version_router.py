"""章节多版本管理路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.chapter_version_schema import (
    ChapterVersionDto,
    VersionCleanupResponse,
    VersionDiffResponse,
    VersionMarkManualRequest,
    VersionRollbackResponse,
)
from src.db.session import get_session
from src.services._chapter_guard import ChapterLockedError
from src.services.chapter_version_service import ChapterVersionService

router = APIRouter()


@router.get("/versions/{chapter_id}", response_model=list[ChapterVersionDto])
async def list_versions(
    chapter_id: str,
    version_type: str | None = Query(None, description="auto/manual 过滤"),
    session: AsyncSession = Depends(get_session),
):
    service = ChapterVersionService(session)
    return await service.list_versions(chapter_id, version_type)


@router.post("/versions/{chapter_id}/mark", response_model=ChapterVersionDto)
async def mark_manual_version(
    chapter_id: str,
    req: VersionMarkManualRequest,
    session: AsyncSession = Depends(get_session),
):
    service = ChapterVersionService(session)
    try:
        return await service.mark_manual(chapter_id, req.name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"标记版本失败: {e}")


@router.get("/versions/diff", response_model=VersionDiffResponse)
async def diff_versions(
    version_id_a: str = Query(..., alias="version_id_a"),
    version_id_b: str = Query(..., alias="version_id_b"),
    session: AsyncSession = Depends(get_session),
):
    service = ChapterVersionService(session)
    try:
        return await service.diff(version_id_a, version_id_b)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"diff 生成失败: {e}")


@router.post("/versions/{version_id}/rollback", response_model=VersionRollbackResponse)
async def rollback_version(
    version_id: str,
    session: AsyncSession = Depends(get_session),
):
    service = ChapterVersionService(session)
    try:
        return await service.rollback(version_id)
    except ChapterLockedError:
        raise HTTPException(status_code=409, detail="章节已锁定，请先解锁")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回滚失败: {e}")


@router.delete("/versions/{chapter_id}/cleanup", response_model=VersionCleanupResponse)
async def cleanup_versions(
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
):
    service = ChapterVersionService(session)
    try:
        return await service.cleanup(chapter_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清理失败: {e}")