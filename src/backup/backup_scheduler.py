"""自动备份调度器 - APScheduler定时+手动+退出前+风险操作前触发."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.utils.logger import get_logger


class BackupScheduler:
    def __init__(self) -> None:
        self.logger = get_logger()
        self._scheduler = None

    async def start(self, policy: Any) -> None:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
            self._scheduler = AsyncIOScheduler()
            if policy.enabled:
                parts = policy.schedule_cron.split()
                trigger = CronTrigger(
                    minute=parts[0] if len(parts) > 0 else "0",
                    hour=parts[1] if len(parts) > 1 else "0",
                    day=parts[2] if len(parts) > 2 else "*",
                    month=parts[3] if len(parts) > 3 else "*",
                    day_of_week=parts[4] if len(parts) > 4 else "*",
                )
                self._scheduler.add_job(self._scheduled_backup, trigger, args=[policy])
            self._scheduler.start()
            self.logger.info("备份调度器已启动")
        except ImportError:
            self.logger.warning("APScheduler 未安装，自动备份不可用")

    async def _scheduled_backup(self, policy: Any) -> None:
        self.logger.info("定时备份触发")

    async def trigger_manual(self, project_ids: list[str] | None = None) -> None:
        self.logger.info(f"手动备份触发: {project_ids or '全部项目'}")

    async def trigger_on_exit(self) -> None:
        self.logger.info("退出前备份触发")

    async def trigger_before_risky(self) -> None:
        self.logger.info("风险操作前备份触发")

    async def stop(self) -> None:
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None