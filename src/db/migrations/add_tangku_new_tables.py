"""迁移脚本 - 唐库改进新增7张表.

幂等：使用 Base.metadata.create_all 仅创建不存在的表。
"""
from __future__ import annotations

from src.db.models import (
    AntiAiRewriteRecord,
    Base,
    BatchOperationRecord,
    BookTeardown,
    IterationRecord,
    ProofreadDraft,
    Script,
    StoryUnit,
)
from src.db.session import get_engine
from src.utils.logger import get_logger


async def upgrade() -> None:
    """创建唐库改进新增的7张表（幂等）."""
    logger = get_logger()
    engine = get_engine()
    tables = [
        StoryUnit.__table__,
        AntiAiRewriteRecord.__table__,
        BatchOperationRecord.__table__,
        BookTeardown.__table__,
        IterationRecord.__table__,
        Script.__table__,
        ProofreadDraft.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=tables,
                checkfirst=True,
            )
        )
    logger.info("迁移完成: add_tangku_new_tables（7张新表）")