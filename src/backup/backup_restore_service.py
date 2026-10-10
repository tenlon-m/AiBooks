"""备份恢复服务."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.backup.project_import_service import ProjectImportService


class BackupRestoreService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.import_service = ProjectImportService(session)

    async def restore(self, backup_path: str, conflict_strategy: str = "rename") -> dict:
        return await self.import_service.import_project(backup_path, conflict_strategy)