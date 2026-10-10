"""人物管理路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.character_schema import (
    AiExtractCharactersRequest,
    AiGenerateSupportingRequest,
    AiImportCharactersRequest,
    BatchConfirmRequest,
    BatchDeleteRequest,
    CharacterCreateRequest,
    CharacterDto,
    CharacterUpdateRequest,
    MergeResultResponse,
)
from src.db.session import get_session
from src.services.character_service import CharacterService

router = APIRouter()


@router.post("/ai_extract", response_model=MergeResultResponse)
async def ai_extract(req: AiExtractCharactersRequest, session: AsyncSession = Depends(get_session)):
    service = CharacterService(session)
    try:
        main_chars = await service.ai_extract_main(req.project_id, req.synopsis, req.worldview)
        existing = main_chars
        supporting = await service.ai_extract_supporting(req.project_id, req.synopsis, req.worldview, existing)
        new_chars = main_chars + supporting
        merge = await service.merge_characters(req.project_id, new_chars)
        return MergeResultResponse(
            added=merge.added, skipped=merge.skipped,
            added_count=merge.added_count, skipped_count=merge.skipped_count,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI提取失败: {e}")


@router.post("/ai_generate_supporting", response_model=MergeResultResponse)
async def ai_generate_supporting(req: AiGenerateSupportingRequest, session: AsyncSession = Depends(get_session)):
    service = CharacterService(session)
    try:
        chars = await service.ai_generate_supporting(
            req.project_id, req.synopsis, req.worldview, req.existing_characters, req.count
        )
        merge = await service.merge_characters(req.project_id, chars)
        return MergeResultResponse(
            added=merge.added, skipped=merge.skipped,
            added_count=merge.added_count, skipped_count=merge.skipped_count,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI生成失败: {e}")


@router.post("/ai_import", response_model=MergeResultResponse)
async def ai_import(req: AiImportCharactersRequest, session: AsyncSession = Depends(get_session)):
    service = CharacterService(session)
    try:
        chars = await service.ai_import_from_file(req.project_id, req.file_path)
        merge = await service.merge_characters(req.project_id, chars)
        return MergeResultResponse(
            added=merge.added, skipped=merge.skipped,
            added_count=merge.added_count, skipped_count=merge.skipped_count,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        msg = str(e)
        if "过大" in msg:
            raise HTTPException(status_code=413, detail=msg)
        if "不支持" in msg:
            raise HTTPException(status_code=415, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI识别导入失败: {e}")


@router.post("/batch_delete")
async def batch_delete(req: BatchDeleteRequest, session: AsyncSession = Depends(get_session)):
    service = CharacterService(session)
    try:
        deleted_count = await service.batch_delete(req.character_ids)
        return {"deleted_count": deleted_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch_confirm")
async def batch_confirm(req: BatchConfirmRequest, session: AsyncSession = Depends(get_session)):
    service = CharacterService(session)
    try:
        confirmed_count = await service.batch_confirm(req.character_ids)
        return {"confirmed_count": confirmed_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=CharacterDto)
async def create_character(req: CharacterCreateRequest, session: AsyncSession = Depends(get_session)):
    service = CharacterService(session)
    return await service.create(req.project_id, req.name, req.identity, req.intro, req.relation, req.source)


@router.get("/{project_id}", response_model=list[CharacterDto])
async def list_characters(project_id: str, session: AsyncSession = Depends(get_session)):
    service = CharacterService(session)
    return await service.list_by_project(project_id)


@router.put("/{character_id}", response_model=CharacterDto)
async def update_character(character_id: str, req: CharacterUpdateRequest, session: AsyncSession = Depends(get_session)):
    service = CharacterService(session)
    try:
        return await service.update(character_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{character_id}/confirm", response_model=CharacterDto)
async def confirm_character(character_id: str, session: AsyncSession = Depends(get_session)):
    service = CharacterService(session)
    try:
        return await service.confirm(character_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{character_id}")
async def delete_character(character_id: str, session: AsyncSession = Depends(get_session)):
    service = CharacterService(session)
    ok = await service.delete(character_id)
    if not ok:
        raise HTTPException(status_code=404, detail="人物不存在")
    return {"message": "已删除"}