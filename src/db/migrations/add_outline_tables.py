"""迁移脚本 - 新增大纲三张表（Outline/VolumeOutline/ChapterOutline）.

幂等：使用 Base.metadata.create_all 仅创建不存在的表。
"""
from __future__ import annotations

from src.db.models import Base, Outline, VolumeOutline, ChapterOutline
from src.db.session import get_engine
from src.utils.logger import get_logger


async def upgrade() -> None:
    """创建大纲三张表（幂等）."""
    logger = get_logger()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[
                    Outline.__table__,
                    VolumeOutline.__table__,
                    ChapterOutline.__table__,
                ],
                checkfirst=True,
            )
        )
    logger.info("迁移完成: add_outline_tables（outlines/volume_outlines/chapter_outlines）")