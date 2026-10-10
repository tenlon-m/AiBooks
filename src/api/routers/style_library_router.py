"""风格库路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.style_library_schema import (
    BatchDeleteStyleLibrariesRequest,
    FeedStyleRequest,
    StyleLibraryDto,
    StyleLibraryExportRequest,
    StyleLibraryImportRequest,
    StyleLibraryUpdateRequest,
)
from src.db.session import get_session
from src.services.style_library_service import StyleLibraryService

router = APIRouter()


@router.post("/feed", response_model=StyleLibraryDto)
async def feed_style(req: FeedStyleRequest, session: AsyncSession = Depends(get_session)):
    service = StyleLibraryService(session)
    try:
        return await service.feed_and_build(req.file_paths, req.naming, req.name, req.user_ideas)
    except ValueError as e:
        msg = str(e)
        if "超限" in msg:
            raise HTTPException(status_code=413, detail=msg)
        if "已存在" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"风格库建立失败: {e}")


@router.delete("/batch")
async def batch_delete_style_libraries(
    req: BatchDeleteStyleLibrariesRequest,
    session: AsyncSession = Depends(get_session),
):
    """批量删除风格库."""
    service = StyleLibraryService(session)
    try:
        deleted = await service.delete_batch(req.style_library_ids)
        return {"deleted_count": deleted}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量删除风格库失败: {e}")


@router.get("", response_model=list[StyleLibraryDto])
async def list_style_libraries(session: AsyncSession = Depends(get_session)):
    service = StyleLibraryService(session)
    return await service.list_all()


@router.get("/{style_library_id}", response_model=StyleLibraryDto)
async def get_style_library(style_library_id: str, session: AsyncSession = Depends(get_session)):
    service = StyleLibraryService(session)
    dto = await service.get(style_library_id)
    if not dto:
        raise HTTPException(status_code=404, detail="风格库不存在")
    return dto


@router.put("/{style_library_id}", response_model=StyleLibraryDto)
async def update_style_library(style_library_id: str, req: StyleLibraryUpdateRequest, session: AsyncSession = Depends(get_session)):
    service = StyleLibraryService(session)
    try:
        return await service.update(style_library_id, req)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/{style_library_id}")
async def delete_style_library(style_library_id: str, session: AsyncSession = Depends(get_session)):
    service = StyleLibraryService(session)
    try:
        ok = await service.delete(style_library_id)
        if not ok:
            raise HTTPException(status_code=404, detail="风格库不存在")
        return {"message": "已删除"}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/export")
async def export_style_library(req: StyleLibraryExportRequest, session: AsyncSession = Depends(get_session)):
    service = StyleLibraryService(session)
    try:
        path = await service.export_library(req.style_library_id, req.target_path)
        return {"file_path": path, "message": "导出成功"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/import", response_model=StyleLibraryDto)
async def import_style_library(req: StyleLibraryImportRequest, session: AsyncSession = Depends(get_session)):
    service = StyleLibraryService(session)
    try:
        return await service.import_library(req.file_path, req.conflict_strategy)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"导入失败: {e}")