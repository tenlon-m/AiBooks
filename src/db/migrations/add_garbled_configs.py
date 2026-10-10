"""迁移脚本 - 新增 garbled_configs 表（乱码检测修复配置）.

幂等：使用 Base.metadata.create_all 仅创建不存在的表。
"""
from __future__ import annotations

from src.db.models import Base, GarbledConfigModel
from src.db.session import get_engine
from src.utils.logger import get_logger


async def upgrade() -> None:
    """创建 garbled_configs 表（幂等）."""
    logger = get_logger()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[GarbledConfigModel.__table__],
                checkfirst=True,
            )
        )
    logger.info("迁移完成: add_garbled_configs（garbled_configs）")