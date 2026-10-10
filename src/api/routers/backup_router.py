"""备份管理路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_config
from src.db.session import get_session

router = APIRouter()


class BackupPolicyRequest(BaseModel):
    enabled: bool = True
    schedule_cron: str = "0 0 * * *"
    target_dir: str
    retain_count: int = 10
    trigger_on_exit: bool = True
    trigger_before_risky_op: bool = True


class ManualBackupRequest(BaseModel):
    project_ids: list[str] | None = None


@router.put("/policy")
async def update_backup_policy(req: BackupPolicyRequest, session: AsyncSession = Depends(get_session)):
    from src.db.models import BackupPolicy
    from sqlalchemy import select
    result = await session.execute(select(BackupPolicy).where(BackupPolicy.policy_id == "default"))
    policy = result.scalars().first()
    if policy is None:
        policy = BackupPolicy(policy_id="default", target_dir=req.target_dir)
        session.add(policy)
    policy.enabled = req.enabled
    policy.schedule_cron = req.schedule_cron
    policy.target_dir = req.target_dir
    policy.retain_count = req.retain_count
    policy.trigger_on_exit = req.trigger_on_exit
    policy.trigger_before_risky_op = req.trigger_before_risky_op
    await session.flush()
    return {"message": "备份策略已更新"}


@router.get("/policy")
async def get_backup_policy(session: AsyncSession = Depends(get_session)):
    """读取当前备份策略，供备份管理页回填表单（避免打开即默认值、保存即覆盖）。"""
    from src.db.models import BackupPolicy
    from sqlalchemy import select

    result = await session.execute(
        select(BackupPolicy).where(BackupPolicy.policy_id == "default")
    )
    policy = result.scalars().first()
    if policy is None:
        # 未持久化过策略时返回系统默认值，与 BackupPolicyRequest 默认值保持一致
        return BackupPolicyRequest(target_dir=str(get_config().backup_dir)).model_dump()
    return {
        "enabled": policy.enabled,
        "schedule_cron": policy.schedule_cron,
        "target_dir": policy.target_dir,
        "retain_count": policy.retain_count,
        "trigger_on_exit": policy.trigger_on_exit,
        "trigger_before_risky_op": policy.trigger_before_risky_op,
    }


@router.post("/trigger")
async def trigger_backup(req: ManualBackupRequest):
    from src.backup.backup_scheduler import BackupScheduler
    scheduler = BackupScheduler()
    await scheduler.trigger_manual(req.project_ids)
    return {"message": "备份已触发"}


@router.get("/list")
async def list_backups(session: AsyncSession = Depends(get_session)):
    from src.db.models import BackupRecord
    from sqlalchemy import select
    result = await session.execute(select(BackupRecord).order_by(BackupRecord.created_at.desc()))
    return [
        {
            "backup_id": r.backup_id,
            "file_path": r.file_path,
            "file_size_bytes": r.file_size_bytes,
            "triggered_by": r.triggered_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in result.scalars().all()
    ]


@router.post("/{backup_id}/restore")
async def restore_backup(backup_id: str, session: AsyncSession = Depends(get_session)):
    from src.db.models import BackupRecord
    from src.backup.backup_restore_service import BackupRestoreService
    record = await session.get(BackupRecord, backup_id)
    if not record:
        raise HTTPException(status_code=404, detail="备份不存在")
    service = BackupRestoreService(session)
    try:
        return await service.restore(record.file_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"恢复失败: {e}")


@router.delete("/{backup_id}")
async def delete_backup(backup_id: str, session: AsyncSession = Depends(get_session)):
    from src.db.models import BackupRecord
    from pathlib import Path
    record = await session.get(BackupRecord, backup_id)
    if not record:
        raise HTTPException(status_code=404, detail="备份不存在")
    try:
        p = Path(record.file_path)
        if p.exists():
            p.unlink()
    except Exception:
        pass
    await session.delete(record)
    await session.flush()
    return {"message": "已删除"}