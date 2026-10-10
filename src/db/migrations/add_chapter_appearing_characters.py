"""迁移脚本 - ChapterOutline 表新增出场人物字段.

新增字段：
  characters_appearing TEXT -- 本章出场人物（"、"分隔的名字），用于校验人物出场逻辑

字段 nullable，兼容已有数据。
"""
from __future__ import annotations

from sqlalchemy import text

from src.db.session import get_engine
from src.utils.logger import get_logger

_MIGRATION_SQL = [
    "ALTER TABLE chapter_outlines ADD COLUMN characters_appearing TEXT",
]

_CHECK_SQL = "PRAGMA table_info(chapter_outlines)"


async def upgrade() -> None:
    """为 chapter_outlines 表新增出场人物字段（幂等）."""
    logger = get_logger()
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(text(_CHECK_SQL))
        existing_cols = {row[1] for row in result.fetchall()}
        for sql in _MIGRATION_SQL:
            col_name = sql.split("ADD COLUMN ")[1].split()[0]
            if col_name in existing_cols:
                logger.debug(f"字段已存在，跳过: {col_name}")
                continue
            await conn.execute(text(sql))
            logger.info(f"已添加字段: chapter_outlines.{col_name}")
    logger.info("迁移完成: add_chapter_appearing_characters")
