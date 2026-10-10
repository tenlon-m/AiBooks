"""AI调用日志查看路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AiCallLog
from src.db.session import get_session

router = APIRouter()


@router.get("/logs")
async def list_logs(
    project_id: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(AiCallLog).order_by(desc(AiCallLog.called_at)).limit(limit)
    if project_id:
        stmt = stmt.where(AiCallLog.project_id == project_id)
    result = await session.execute(stmt)
    logs = result.scalars().all()
    return [
        {
            "log_id": l.log_id,
            "project_id": l.project_id,
            "source_name": l.source_name,
            "model_name": l.model_name,
            "scene": l.scene,
            "duration_ms": l.duration_ms,
            "status": l.status,
            "called_at": l.called_at.isoformat() if l.called_at else None,
        }
        for l in logs
    ]


@router.get("/logs/{log_id}")
async def get_log(log_id: str, session: AsyncSession = Depends(get_session)):
    log = await session.get(AiCallLog, log_id)
    if not log:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="日志不存在")
    return {
        "log_id": log.log_id,
        "project_id": log.project_id,
        "source_name": log.source_name,
        "model_name": log.model_name,
        "scene": log.scene,
        "prompt": log.prompt,
        "response": log.response,
        "duration_ms": log.duration_ms,
        "status": log.status,
        "failover_from": log.failover_from,
        "called_at": log.called_at.isoformat() if log.called_at else None,
    }