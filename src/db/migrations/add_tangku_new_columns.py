"""迁移脚本 - 现有表新增唐库改进相关字段.

新增字段：
  chapter_outlines.story_unit_id  VARCHAR(36)  -- 故事单元外键（分层大纲）
  characters.scope_type           VARCHAR(10)  -- 配角作用域类型
  characters.scope_unit_id        VARCHAR(36)  -- 配角作用域单元ID

所有字段均 nullable，兼容已有数据。
"""
from __future__ import annotations

from sqlalchemy import text

from src.db.session import get_engine
from src.utils.logger import get_logger

_MIGRATIONS = [
    ("chapter_outlines", "ALTER TABLE chapter_outlines ADD COLUMN story_unit_id VARCHAR(36)"),
    ("characters", "ALTER TABLE characters ADD COLUMN scope_type VARCHAR(10)"),
    ("characters", "ALTER TABLE characters ADD COLUMN scope_unit_id VARCHAR(36)"),
]


async def upgrade() -> None:
    """执行迁移：为现有表新增字段（幂等）."""
    logger = get_logger()
    engine = get_engine()
    async with engine.begin() as conn:
        for table_name, sql in _MIGRATIONS:
            result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
            existing_cols = {row[1] for row in result.fetchall()}
            col_name = sql.split("ADD COLUMN ")[1].split()[0]
            if col_name in existing_cols:
                logger.debug(f"字段已存在，跳过: {table_name}.{col_name}")
                continue
            await conn.execute(text(sql))
            logger.info(f"已添加字段: {table_name}.{col_name}")
    logger.info("迁移完成: add_tangku_new_columns")