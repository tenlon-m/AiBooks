"""迁移脚本 - NameFavorite 表新增 meaning 列（释义）.

新增字段：
  meaning TEXT  -- AI 生成的命名释义/理由

nullable，兼容已有数据。
"""
from __future__ import annotations

from sqlalchemy import text

from src.db.session import get_engine
from src.utils.logger import get_logger

_MIGRATION_SQL = "ALTER TABLE name_favorites ADD COLUMN meaning TEXT"

_CHECK_SQL = "PRAGMA table_info(name_favorites)"


async def upgrade() -> None:
    """执行迁移：为 name_favorites 表新增 meaning 字段（幂等）."""
    logger = get_logger()
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(text(_CHECK_SQL))
        existing_cols = {row[1] for row in result.fetchall()}
        if "meaning" in existing_cols:
            logger.debug("字段已存在，跳过: name_favorites.meaning")
            return
        await conn.execute(text(_MIGRATION_SQL))
        logger.info("已添加字段: name_favorites.meaning")
    logger.info("迁移完成: add_name_favorite_meaning")