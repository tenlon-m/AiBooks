"""章节修改路由."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.chapter_schema import (
    ChapterContentResponse,
    ChapterContentUpdateRequest,
    ChapterLockRequest,
    ChapterLockResponse,
    HistoryRecordDto,
    RollbackRequest,
    RollbackResponse,
)
from src.api.schemas.validation_schema import (
    ChapterConsistencyResult,
    PolishConfirmRequest,
    PolishResponse,
    RevalidateResponse,
)
from src.db.models import Chapter
from src.db.session import get_session
from src.services.edit_polish_service import EditPolishService
from src.services.garbled_normalizer import GarbledConfig


def _parse_gc(d: dict | None) -> GarbledConfig | None:
    if d is None:
        return None
    return GarbledConfig(**d)


router = APIRouter()


@router.put("/{chapter_id}/content", response_model=ChapterContentResponse)
async def update_content(chapter_id: str, req: ChapterContentUpdateRequest, session: AsyncSession = Depends(get_session)):
    service = EditPolishService(session)
    try:
        chapter = await service.update_chapter_content(
            chapter_id, req.new_content, _parse_gc(req.garbled_config),
        )
        return ChapterContentResponse(
            chapter_id=chapter.chapter_id,
            volume_no=chapter.volume_no,
            chapter_no=chapter.chapter_no,
            title=chapter.title,
            content=chapter.content,
            word_count=chapter.word_count,
        )
    except ValueError as e:
        msg = str(e)
        if "生成中" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except Exception as e:
        if "章节已锁定" in str(e):
            raise HTTPException(status_code=409, detail="章节已锁定，请先解锁")
        raise


@router.get("/{chapter_id}/content", response_model=ChapterContentResponse)
async def get_content(chapter_id: str, session: AsyncSession = Depends(get_session)):
    chapter = await session.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return ChapterContentResponse(
        chapter_id=chapter.chapter_id,
        volume_no=chapter.volume_no,
        chapter_no=chapter.chapter_no,
        title=chapter.title,
        content=chapter.content or "",
        word_count=chapter.word_count,
    )


@router.post("/{chapter_id}/revalidate", response_model=RevalidateResponse)
async def revalidate(chapter_id: str, session: AsyncSession = Depends(get_session)):
    service = EditPolishService(session)
    try:
        return await service.revalidate_chapter(chapter_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"再校验失败: {e}")


@router.post("/{chapter_id}/polish", response_model=PolishResponse)
async def polish(
    chapter_id: str,
    user_ideas: str = "",
    garbled_config: dict | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
):
    service = EditPolishService(session)
    try:
        return await service.polish_chapter(
            chapter_id, user_ideas, _parse_gc(garbled_config),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"润色失败: {e}")


@router.post("/{chapter_id}/check_consistency", response_model=ChapterConsistencyResult)
async def check_chapter_consistency(
    chapter_id: str,
    user_ideas: str = "",
    garbled_config: dict | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
):
    """校验单章内容与大纲/风格库的一致性."""
    service = EditPolishService(session)
    try:
        return await service.check_chapter_consistency(
            chapter_id, user_ideas, _parse_gc(garbled_config),
        )
    except ValueError as e:
        msg = str(e)
        if "章节不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "大纲不存在" in msg:
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=f"一致性校验超时: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI校验失败: {e}")


@router.post("/{chapter_id}/polish/confirm", response_model=ChapterContentResponse)
async def confirm_polish(chapter_id: str, req: PolishConfirmRequest, session: AsyncSession = Depends(get_session)):
    service = EditPolishService(session)
    try:
        chapter = await service.confirm_polish(
            chapter_id, req.action, _parse_gc(req.garbled_config),
        )
        return ChapterContentResponse(
            chapter_id=chapter.chapter_id,
            volume_no=chapter.volume_no,
            chapter_no=chapter.chapter_no,
            title=chapter.title,
            content=chapter.content or "",
            word_count=chapter.word_count,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        if "章节已锁定" in str(e):
            raise HTTPException(status_code=409, detail="章节已锁定，请先解锁")
        raise


@router.get("/{chapter_id}/history", response_model=list[HistoryRecordDto])
async def list_history(chapter_id: str, session: AsyncSession = Depends(get_session)):
    service = EditPolishService(session)
    return await service.list_history(chapter_id)


@router.post("/{chapter_id}/rollback", response_model=RollbackResponse)
async def rollback(chapter_id: str, req: RollbackRequest, session: AsyncSession = Depends(get_session)):
    service = EditPolishService(session)
    try:
        return await service.rollback_chapter(chapter_id, req.target_record_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        if "章节已锁定" in str(e):
            raise HTTPException(status_code=409, detail="章节已锁定，请先解锁")
        raise

@router.patch("/{chapter_id}/lock", response_model=ChapterLockResponse)
async def lock_chapter(
    chapter_id: str,
    req: ChapterLockRequest,
    session: AsyncSession = Depends(get_session),
):
    """锁定/解锁章节，返回新状态."""
    chapter = await session.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    chapter.is_locked = req.is_locked
    await session.commit()
    return ChapterLockResponse(
        chapter_id=chapter.chapter_id,
        is_locked=chapter.is_locked,
    )


@router.get("/{chapter_id}/lock", response_model=ChapterLockResponse)
async def get_chapter_lock(
    chapter_id: str, session: AsyncSession = Depends(get_session)
):
    """查询章节锁定状态.

    前端 chapter_edit_page 在选中章节时会调用本端点同步锁定状态；
    历史上只有 PATCH 没有 GET，前端拿到 405，导致「锁定状态永远显示为
    未锁定」——锁过的章节重新选中后编辑器不再只读。
    """
    chapter = await session.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return ChapterLockResponse(
        chapter_id=chapter.chapter_id,
        is_locked=chapter.is_locked,
    )