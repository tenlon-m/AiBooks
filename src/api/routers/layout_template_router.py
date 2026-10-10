"""排版模板路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.layout_template_schema import (
    LayoutTemplateCreateRequest,
    LayoutTemplateDto,
    LayoutTemplateListResponse,
)
from src.db.session import get_session
from src.services.layout_template_service import LayoutTemplateService

router = APIRouter()


@router.get("", response_model=LayoutTemplateListResponse)
@router.get("/", response_model=LayoutTemplateListResponse)
async def list_templates(
    format: str | None = Query(None, description="按格式过滤"),
    session: AsyncSession = Depends(get_session),
):
    """列出排版模板."""
    service = LayoutTemplateService(session)
    return await service.list_templates(format)


@router.get("/{template_id}", response_model=LayoutTemplateDto)
async def get_template(template_id: str, session: AsyncSession = Depends(get_session)):
    """获取排版模板详情."""
    service = LayoutTemplateService(session)
    try:
        return await service.get_template(template_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("", response_model=LayoutTemplateDto)
@router.post("/", response_model=LayoutTemplateDto)
async def create_template(
    req: LayoutTemplateCreateRequest, session: AsyncSession = Depends(get_session)
):
    """创建自定义排版模板."""
    service = LayoutTemplateService(session)
    try:
        return await service.create_template(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建失败: {e}")


@router.delete("/{template_id}")
async def delete_template(template_id: str, session: AsyncSession = Depends(get_session)):
    """删除排版模板（内置不可删）."""
    service = LayoutTemplateService(session)
    try:
        await service.delete_template(template_id)
        return {"ok": True}
    except ValueError as e:
        msg = str(e)
        if "不可删除" in msg:
            raise HTTPException(status_code=403, detail=msg)
        raise HTTPException(status_code=404, detail=msg)