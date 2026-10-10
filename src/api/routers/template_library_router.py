"""写作模板/套路库路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.template_library_schema import (
    TemplateLibraryApplyRequest,
    TemplateLibraryDetailResponse,
    TemplateLibraryListResponse,
    WorldviewTemplateApplyRequestDto,
    WorldviewTemplateListResponse,
)
from src.db.session import get_session
from src.services.template_library_service import TemplateLibraryService

router = APIRouter()


@router.get("", response_model=TemplateLibraryListResponse)
@router.get("/", response_model=TemplateLibraryListResponse)
async def list_templates(session: AsyncSession = Depends(get_session)):
    """列出所有写作模板."""
    service = TemplateLibraryService(session)
    return await service.list_templates()


@router.get("/worldview", response_model=WorldviewTemplateListResponse)
async def list_worldview_templates(session: AsyncSession = Depends(get_session)):
    """列出所有世界观模板."""
    service = TemplateLibraryService(session)
    return await service.list_worldview_templates()


@router.post("/worldview/apply")
async def apply_worldview_template(
    req: WorldviewTemplateApplyRequestDto, session: AsyncSession = Depends(get_session)
):
    """应用世界观模板到项目."""
    service = TemplateLibraryService(session)
    try:
        return await service.apply_worldview_template(req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"应用世界观模板失败: {e}")


@router.get("/{novel_type}", response_model=TemplateLibraryDetailResponse)
async def get_template(novel_type: str, session: AsyncSession = Depends(get_session)):
    """获取指定类型写作模板详情."""
    service = TemplateLibraryService(session)
    try:
        return await service.get_template(novel_type)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取模板失败: {e}")


@router.post("/apply")
async def apply_template(req: TemplateLibraryApplyRequest, session: AsyncSession = Depends(get_session)):
    """应用写作模板到项目."""
    service = TemplateLibraryService(session)
    try:
        return await service.apply_template(req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"应用模板失败: {e}")