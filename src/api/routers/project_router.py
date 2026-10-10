"""项目导出/导入路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

from src.db.session import get_session
from src.backup.project_export_service import ProjectExportService
from src.backup.project_import_service import ProjectImportService

router = APIRouter()


class ProjectExportRequest(BaseModel):
    target_path: str
    include_ai_call_logs: bool = False
    include_style_libraries: bool = True


class ProjectImportRequest(BaseModel):
    source_path: str
    conflict_strategy: Literal["overwrite", "rename", "cancel"] = "rename"


@router.post("/{project_id}/export")
async def export_project(project_id: str, req: ProjectExportRequest, session: AsyncSession = Depends(get_session)):
    service = ProjectExportService(session)
    try:
        return await service.export_project(project_id, req.target_path, req.include_ai_call_logs, req.include_style_libraries)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")


@router.post("/import")
async def import_project(req: ProjectImportRequest, session: AsyncSession = Depends(get_session)):
    service = ProjectImportService(session)
    try:
        return await service.import_project(req.source_path, req.conflict_strategy)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败: {e}")