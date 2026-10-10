"""建库建表脚本 - 系统首次运行自动初始化 schema."""
from __future__ import annotations

from src.db.models import ALL_MODELS, Base
from src.db.session import get_engine
from src.utils.logger import get_logger


async def init_schema() -> None:
    """创建所有表与索引."""
    logger = get_logger()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"数据库 schema 初始化完成，共 {len(ALL_MODELS)} 张表")


async def drop_schema() -> None:
    """删除所有表（仅用于测试/重置）."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)