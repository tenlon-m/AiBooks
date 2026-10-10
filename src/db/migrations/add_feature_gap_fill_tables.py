"""迁移脚本 - 新增功能补全12张表 + Chapter.is_locked 字段.

幂等：使用 Base.metadata.create_all 仅创建不存在的表，ALTER TABLE 幂等检查。

历史遗留：本脚本曾包含一段直写 sqlite_schema（INSERT/DELETE 名为 '_check' 的行）
的语句，SQLite 默认禁止修改 sqlite_master，实测必然抛
"table sqlite_master may not be modified"，导致整个迁移从未成功执行过，
chapters.is_locked 列因此长期缺失（启动日志 "no such column: chapters.is_locked"
即源于此）。该段无任何实际作用，已删除。
"""
from __future__ import annotations

from sqlalchemy import text
from src.db.models import (
    Base,
    WritingChatHistory,
    ChapterVersion,
    ChapterAnnotation,
    ChapterScene,
    ChapterSummary,
    TimelineNode,
    CharacterRelationship,
    EmotionCurvePoint,
    SensitiveWord,
    NameFavorite,
    LayoutTemplate,
    ShortcutConfig,
)
from src.db.session import get_engine
from src.utils.logger import get_logger


_NEW_TABLES = [
    WritingChatHistory,
    ChapterVersion,
    ChapterAnnotation,
    ChapterScene,
    ChapterSummary,
    TimelineNode,
    CharacterRelationship,
    EmotionCurvePoint,
    SensitiveWord,
    NameFavorite,
    LayoutTemplate,
    ShortcutConfig,
]


async def upgrade() -> None:
    """创建12张新表 + 为 chapters 表添加 is_locked 字段（幂等）."""
    logger = get_logger()
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[t.__table__ for t in _NEW_TABLES],
                checkfirst=True,
            )
        )

        result = await conn.execute(text("PRAGMA table_info(chapters)"))
        rows = result.fetchall()
        if not rows:
            # chapters 表本身不存在（例如 init_schema 尚未执行）——它会由
            # metadata 创建并自带 is_locked 列，无需 ALTER；直接 ALTER 反而会
            # 抛 "no such table: chapters"。
            pass
        else:
            columns = [row[1] for row in rows]
            if "is_locked" not in columns:
                await conn.execute(
                    text("ALTER TABLE chapters ADD COLUMN is_locked BOOLEAN NOT NULL DEFAULT 0")
                )
                logger.info("已为 chapters 表添加 is_locked 字段")

    logger.info("迁移完成: add_feature_gap_fill_tables（12张新表 + is_locked字段）")