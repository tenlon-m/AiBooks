"""AI 源配置路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.ai_source_schema import (
    ActiveAiSourceResponse,
    AiSourceCreateRequest,
    AiSourceDto,
    AiSourceTestResponse,
    AiSourceUpdateRequest,
    OllamaModelsResponse,
    RoutingPolicyDto,
    RoutingPolicyRequest,
)
from src.db.session import get_session
from src.services.ai_source_service import AiSourceService
from src.services.ollama_service import OllamaService
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger()


@router.post("/ai_sources", response_model=AiSourceDto)
async def create_ai_source(req: AiSourceCreateRequest, session: AsyncSession = Depends(get_session)):
    service = AiSourceService(session)
    try:
        return await service.create(req)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/ai_sources", response_model=list[AiSourceDto])
async def list_ai_sources(session: AsyncSession = Depends(get_session)):
    service = AiSourceService(session)
    return await service.list_all()


@router.put("/ai_sources/{source_id}", response_model=AiSourceDto)
async def update_ai_source(source_id: str, req: AiSourceUpdateRequest, session: AsyncSession = Depends(get_session)):
    service = AiSourceService(session)
    try:
        return await service.update(source_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/ai_sources/{source_id}")
async def delete_ai_source(source_id: str, session: AsyncSession = Depends(get_session)):
    service = AiSourceService(session)
    try:
        ok = await service.delete(source_id)
        if not ok:
            raise HTTPException(status_code=404, detail="AI源不存在")
        return {"message": "已删除"}
    except ValueError as e:
        raise HTTPException(status_code=412, detail=str(e))


@router.post("/ai_sources/{source_id}/test", response_model=AiSourceTestResponse)
async def test_ai_source(source_id: str, session: AsyncSession = Depends(get_session)):
    service = AiSourceService(session)
    try:
        result = await service.test_connection(source_id)
        return AiSourceTestResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/ai_sources/{source_id}/key")
async def get_ai_source_key(source_id: str, session: AsyncSession = Depends(get_session)):
    service = AiSourceService(session)
    try:
        key = await service.get_decrypted_key(source_id)
        return {"api_key": key}
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=500, detail=msg)


@router.get("/routing_policy", response_model=RoutingPolicyDto)
async def get_routing_policy(session: AsyncSession = Depends(get_session)):
    service = AiSourceService(session)
    return await service.get_routing_policy()


@router.get("/ollama/models", response_model=OllamaModelsResponse)
async def list_ollama_models(endpoint: str = "http://localhost:11434/v1"):
    service = OllamaService()
    result = await service.list_models(endpoint)
    return OllamaModelsResponse(**result)


@router.put("/routing_policy", response_model=RoutingPolicyDto)
async def update_routing_policy(req: RoutingPolicyRequest, session: AsyncSession = Depends(get_session)):
    service = AiSourceService(session)
    return await service.update_routing_policy(req)

@router.get("/ai_source/active", response_model=ActiveAiSourceResponse)
async def get_active_ai_source(session: AsyncSession = Depends(get_session)):
    service = AiSourceService(session)
    result = await service.get_active_source_display()
    return ActiveAiSourceResponse(**result)

@router.get("/ai_sources/export")
async def export_ai_sources(session: AsyncSession = Depends(get_session)):
    service = AiSourceService(session)
    try:
        return await service.export_all_sources()
    except Exception as e:
        logger.error(f"导出 AI 源配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")


@router.post("/ai_sources/import")
async def import_ai_sources(data: dict, session: AsyncSession = Depends(get_session)):
    service = AiSourceService(session)
    try:
        return await service.import_sources(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"导入数据格式错误: {e}")
    except Exception as e:
        logger.error(f"导入 AI 源配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导入失败: {e}")