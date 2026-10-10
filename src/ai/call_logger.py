"""AI 调用日志 - 落库 AiCallLog 表 + loguru 文件双写."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AiCallLog
from src.utils.logger import get_logger


class CallLogger:
    """AI 调用日志记录器."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session
        self.logger = get_logger()

    async def log(
        self,
        scene: str,
        prompt: str,
        response: str,
        duration_ms: int,
        status: str = "success",
        source_id: str | None = None,
        source_name: str | None = None,
        model_name: str | None = None,
        failover_from: str | None = None,
        project_id: str | None = None,
    ) -> str:
        """记录一次 AI 调用.

        Returns:
            log_id
        """
        log_id = str(uuid.uuid4())
        log_entry = AiCallLog(
            log_id=log_id,
            project_id=project_id,
            source_id=source_id,
            source_name=source_name,
            model_name=model_name,
            scene=scene,
            prompt=prompt[:10000] if prompt else None,
            response=response[:10000] if response else None,
            duration_ms=duration_ms,
            status=status,
            failover_from=failover_from,
            called_at=datetime.now(timezone.utc),
        )
        if self.session is not None:
            self.session.add(log_entry)
            await self.session.flush()

        level = "error" if status == "failed" else "info"
        getattr(self.logger, level)(
            f"[AI调用] scene={scene} source={source_name} model={model_name} "
            f"status={status} duration={duration_ms}ms"
            + (f" failover_from={failover_from}" if failover_from else "")
        )
        return log_id

    def log_sync(
        self,
        scene: str,
        prompt: str,
        response: str,
        duration_ms: int,
        status: str = "success",
        source_id: str | None = None,
        source_name: str | None = None,
        model_name: str | None = None,
        failover_from: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """同步日志记录（仅 loguru，不落库）."""
        level = "error" if status == "failed" else "info"
        getattr(self.logger, level)(
            f"[AI调用] scene={scene} source={source_name} model={model_name} "
            f"status={status} duration={duration_ms}ms"
            + (f" failover_from={failover_from}" if failover_from else "")
        )