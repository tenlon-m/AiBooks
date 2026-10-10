"""AB稿/ABC稿多AI接力纠错路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.proofread_schema import (
    ProofreadABRequest,
    ProofreadABCRequest,
    ProofreadDraftDto,
    ProofreadResultDto,
)
from src.db.session import get_session
from src.services.proofread_service import ProofreadService
from src.utils.logger import get_logger

logger = get_logger()

router = APIRouter()


@router.post("/ab", response_model=ProofreadResultDto)
async def proofread_ab(
    req: ProofreadABRequest,
    session: AsyncSession = Depends(get_session),
):
    service = ProofreadService(session)
    try:
        return await service.proofread_ab(req.chapter_id, req.source_a, req.source_b)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"接力纠错超时: {e}")
    except Exception as e:
        logger.error(f"AB接力纠错失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"AI纠错失败: {e}")


@router.post("/abc", response_model=ProofreadResultDto)
async def proofread_abc(
    req: ProofreadABCRequest,
    session: AsyncSession = Depends(get_session),
):
    service = ProofreadService(session)
    try:
        return await service.proofread_abc(
            req.chapter_id,
            req.source_a,
            req.source_b,
            req.source_c,
            req.source_eval,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"接力纠错超时: {e}")
    except Exception as e:
        logger.error(f"ABC接力纠错失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"AI纠错失败: {e}")


@router.get("/drafts/{chapter_id}", response_model=list[ProofreadDraftDto])
async def list_drafts(
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
):
    service = ProofreadService(session)
    return await service.list_drafts(chapter_id)


@router.post("/drafts/{draft_id}/adopt")
async def adopt_draft(
    draft_id: str,
    session: AsyncSession = Depends(get_session),
):
    service = ProofreadService(session)
    try:
        return await service.adopt_draft(draft_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))