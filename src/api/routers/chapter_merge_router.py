"""章节合并/拆分路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.chapter_merge_schema import (
    ChapterMergeRequest,
    ChapterMergeResponse,
    ChapterSplitRequest,
    ChapterSplitResponse,
)
from src.db.session import get_session
from src.services._chapter_guard import ChapterLockedError
from src.services.chapter_merge_service import ChapterMergeService

router = APIRouter()


@router.post("/merge", response_model=ChapterMergeResponse)
async def merge_chapters(
    req: ChapterMergeRequest,
    session: AsyncSession = Depends(get_session),
):
    service = ChapterMergeService(session)
    try:
        return await service.merge(req.chapter_ids, req.new_title)
    except ChapterLockedError:
        raise HTTPException(status_code=409, detail="章节已锁定，请先解锁")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"合并失败: {e}")


@router.post("/split", response_model=ChapterSplitResponse)
async def split_chapter(
    req: ChapterSplitRequest,
    session: AsyncSession = Depends(get_session),
):
    service = ChapterMergeService(session)
    try:
        return await service.split(req.chapter_id, req.split_positions, req.new_titles)
    except ChapterLockedError:
        raise HTTPException(status_code=409, detail="章节已锁定，请先解锁")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"拆分失败: {e}")