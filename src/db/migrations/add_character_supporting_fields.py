"""迁移脚本 - Character 表新增配角相关四字段.

新增字段：
  appearance_records TEXT          -- 出场记录 JSON
  supporting_type    VARCHAR(20)   -- 配角类型 正式配角/临时配角
  auto_gen_context   TEXT          -- 自动生成场景上下文 JSON
  future_reference   BOOLEAN       -- 后续引用标记

所有字段均 nullable，兼容已有数据。
"""
from __future__ import annotations

from sqlalchemy import text

from src.db.session import get_engine
from src.utils.logger import get_logger

_MIGRATION_SQL = [
    "ALTER TABLE characters ADD COLUMN appearance_records TEXT",
    "ALTER TABLE characters ADD COLUMN supporting_type VARCHAR(20)",
    "ALTER TABLE characters ADD COLUMN auto_gen_context TEXT",
    "ALTER TABLE characters ADD COLUMN future_reference BOOLEAN",
]

_CHECK_SQL = "PRAGMA table_info(characters)"


async def upgrade() -> None:
    """执行迁移：为 characters 表新增四个字段（幂等）."""
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
            logger.info(f"已添加字段: characters.{col_name}")
    logger.info("迁移完成: add_character_supporting_fields")