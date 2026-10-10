"""一键拆书路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.book_teardown_schema import (
    BookTeardownDto,
    CreateProjectFromTeardownRequest,
    TeardownElementsDto,
    TeardownOutlineDto,
)
from src.db.models import BookTeardown
from src.db.session import get_session
from src.services.book_teardown_service import BookTeardownService

router = APIRouter()


class _UploadRequest(BaseModel):
    file_path: str


@router.post("/upload", response_model=BookTeardownDto)
async def upload(req: _UploadRequest, session: AsyncSession = Depends(get_session)):
    service = BookTeardownService(session)
    try:
        await service.upload_and_parse(req.file_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    record = await session.get(BookTeardown, service._last_teardown_id)
    return BookTeardownDto(
        teardown_id=record.teardown_id,
        source_file_path=record.source_file_path,
        file_format=record.file_format,
        teardown_status=record.teardown_status,
        created_at=record.created_at,
    )


@router.post("/{teardown_id}/teardown-outline", response_model=TeardownOutlineDto)
async def teardown_outline(teardown_id: str, session: AsyncSession = Depends(get_session)):
    service = BookTeardownService(session)
    try:
        return await service.teardown_outline(teardown_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{teardown_id}/extract-elements", response_model=TeardownElementsDto)
async def extract_elements(teardown_id: str, session: AsyncSession = Depends(get_session)):
    service = BookTeardownService(session)
    try:
        return await service.extract_elements(teardown_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{teardown_id}/create-project")
async def create_project(
    teardown_id: str,
    req: CreateProjectFromTeardownRequest,
    session: AsyncSession = Depends(get_session),
):
    service = BookTeardownService(session)
    try:
        return await service.create_project_from_teardown(teardown_id, req.book_title)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))