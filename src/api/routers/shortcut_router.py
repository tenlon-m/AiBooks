"""快捷键配置路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.shortcut_schema import (
    ShortcutDto,
    ShortcutResetResponse,
    ShortcutUpdateRequest,
)
from src.db.session import get_session
from src.services.shortcut_service import ShortcutConflictError, ShortcutService

router = APIRouter()


@router.get("", response_model=list[ShortcutDto])
async def list_shortcuts(session: AsyncSession = Depends(get_session)):
    """列出全部快捷键配置."""
    service = ShortcutService(session)
    try:
        return await service.list_shortcuts()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取快捷键列表失败: {e}")


@router.put("/{shortcut_id}", response_model=ShortcutDto)
async def update_shortcut(
    shortcut_id: str,
    req: ShortcutUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """更新指定快捷键；冲突时返回 409."""
    service = ShortcutService(session)
    try:
        return await service.update_shortcut(shortcut_id, req)
    except ShortcutConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "conflict_action": e.conflict_action,
                "key_sequence": e.key_sequence,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新快捷键失败: {e}")


@router.post("/reset", response_model=ShortcutResetResponse)
async def reset_shortcuts(session: AsyncSession = Depends(get_session)):
    """重置全部快捷键为预设值."""
    service = ShortcutService(session)
    try:
        shortcuts = await service.reset()
        return ShortcutResetResponse(reset_count=len(shortcuts), shortcuts=shortcuts)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重置快捷键失败: {e}")