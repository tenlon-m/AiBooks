"""add_feature_gap_fill_tables 迁移回归测试.

背景（本迁移曾有两处问题，均已修复）：

1. **从未被接线**：``src/app.py`` 的启动序列漏掉了它，老库的 ``chapters``
   表因此缺 ``is_locked`` 列，所有章节查询报
   ``no such column: chapters.is_locked``。
2. **脚本本身必然失败**：旧版包含直写 ``sqlite_schema`` 的语句，SQLite 默认
   禁止修改 sqlite_master，实测 100% 抛
   ``table sqlite_master may not be modified``。

本文件锁定三件事：
- 旧结构库（缺 is_locked）按完整启动序列迁移后，列补齐、老数据无损；
- 12 张功能表被创建；
- 迁移幂等：对已升级库重复执行无副作用，对空库（chapters 不存在）不炸。
"""
from __future__ import annotations

import asyncio
from typing import Any, Coroutine

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config.app_config import AppConfig
from src.db import session as db_session
from src.db.migrations.add_feature_gap_fill_tables import (
    _NEW_TABLES,
    upgrade as upgrade_gap_fill,
)

_EXPECTED_TABLES = [t.__tablename__ for t in _NEW_TABLES]


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


async def _init_engine_at(db_path: Any) -> None:
    """把全局引擎指向临时库（复制 app.init_app 的做法）."""
    await db_session.close_engine()
    db_session.init_engine(
        AppConfig(
            data_dir=db_path.parent,
            log_dir=db_path.parent / "logs",
            db_url=f"sqlite+aiosqlite:///{db_path}",
        )
    )


async def _make_old_schema(db_path: Any) -> None:
    """构造旧结构库：只有不含 is_locked 的 chapters 表 + 一行老数据."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE chapters ("
            " chapter_id VARCHAR(36) PRIMARY KEY,"
            " project_id VARCHAR(36) NOT NULL,"
            " volume_no INTEGER NOT NULL,"
            " chapter_no INTEGER NOT NULL,"
            " title VARCHAR(200),"
            " content TEXT,"
            " word_count INTEGER NOT NULL,"
            " gen_status VARCHAR(20) NOT NULL,"
            " modify_status VARCHAR(20) NOT NULL,"
            " last_modified_at DATETIME,"
            " created_at DATETIME)"
        ))
        await conn.execute(text(
            "INSERT INTO chapters VALUES ('c1','p1',1,1,'旧章节','旧内容',10,"
            "'completed','none','2026-01-01 00:00:00','2026-01-01 00:00:00')"
        ))
    await engine.dispose()


async def _columns(table: str) -> list[str]:
    from src.db.session import get_engine

    async with get_engine().connect() as conn:
        res = await conn.execute(text(f"PRAGMA table_info({table})"))
        return [r[1] for r in res.fetchall()]


async def _tables() -> list[str]:
    from src.db.session import get_engine

    async with get_engine().connect() as conn:
        res = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
        return [r[0] for r in res.fetchall()]


@pytest.fixture(autouse=True)
def _restore_engine() -> Any:
    """确保每个测试结束后把全局引擎恢复为未初始化状态，避免污染其它测试."""
    yield
    asyncio.run(db_session.close_engine())


# --------------------------------------------------------------------------- #
# 核心场景：老库升级
# --------------------------------------------------------------------------- #


def test_old_schema_gets_is_locked_and_data_survives(tmp_path: Any) -> None:
    """复现用户的事故场景：旧结构库迁移后列补齐、老数据无损."""

    async def _case() -> None:
        db_path = tmp_path / "old.db"
        await _make_old_schema(db_path)
        await _init_engine_at(db_path)

        assert "is_locked" not in await _columns("chapters")

        await upgrade_gap_fill()

        cols = await _columns("chapters")
        assert "is_locked" in cols, "迁移后必须补上 is_locked 列"

        from src.db.session import get_engine

        async with get_engine().connect() as conn:
            row = (await conn.execute(text(
                "SELECT chapter_id, title, content, is_locked "
                "FROM chapters WHERE chapter_id = 'c1'"
            ))).fetchone()
        assert row is not None
        assert row[1] == "旧章节"
        assert row[2] == "旧内容"
        assert row[3] in (0, False), "老数据行的 is_locked 应为默认值 False"

    _run(_case())


def test_creates_all_twelve_new_tables(tmp_path: Any) -> None:
    """12 张功能表必须被创建（锁定表清单，防止将来悄悄缩水）."""

    async def _case() -> None:
        db_path = tmp_path / "new.db"
        await _init_engine_at(db_path)

        await upgrade_gap_fill()

        tables = await _tables()
        missing = [t for t in _EXPECTED_TABLES if t not in tables]
        assert missing == [], f"缺少功能表: {missing}"

    _run(_case())


# --------------------------------------------------------------------------- #
# 幂等性
# --------------------------------------------------------------------------- #


def test_upgrade_is_idempotent_on_upgraded_db(tmp_path: Any) -> None:
    """已升级的库重复执行迁移不得有任何副作用（启动流程每次都会跑）."""

    async def _case() -> None:
        db_path = tmp_path / "old.db"
        await _make_old_schema(db_path)
        await _init_engine_at(db_path)

        await upgrade_gap_fill()
        before_cols = await _columns("chapters")
        before_tables = await _tables()

        # 第二次执行：不应抛错、不应改变结构
        await upgrade_gap_fill()

        assert await _columns("chapters") == before_cols
        assert await _tables() == before_tables

    _run(_case())


def test_upgrade_tolerates_missing_chapters_table(tmp_path: Any) -> None:
    """chapters 表不存在时（如 init_schema 未先行）不应抛 no such table.

    旧版实现在这种情况下会直接 ``ALTER TABLE chapters`` 报错。
    """

    async def _case() -> None:
        db_path = tmp_path / "empty.db"
        await _init_engine_at(db_path)

        # 空库：chapters 表不存在
        assert "chapters" not in await _tables()
        await upgrade_gap_fill()  # 不应抛 "no such table: chapters"

    _run(_case())


# --------------------------------------------------------------------------- #
# 端到端：完整启动序列后 list_chapters 可用
# --------------------------------------------------------------------------- #


def test_full_startup_sequence_restores_chapter_queries(tmp_path: Any) -> None:
    """按 app.init_app 的迁移顺序跑完，list_chapters 的 SELECT 不再报缺列."""

    async def _case() -> None:
        from src.db.migrations.init_schema import init_schema

        db_path = tmp_path / "old.db"
        await _make_old_schema(db_path)
        await _init_engine_at(db_path)

        # init_schema 的 create_all(checkfirst) 不会动已存在的 chapters 表
        await init_schema()
        assert "is_locked" not in await _columns("chapters"), (
            "前提校验：create_all 不给已存在的表补列（这正是事故根因）"
        )

        await upgrade_gap_fill()
        assert "is_locked" in await _columns("chapters")

        # 与 writing_service.list_chapters 相同形状的 ORM 查询必须能执行
        from src.db.models import Chapter
        from src.db.session import get_session_factory

        async with get_session_factory()() as session:
            result = await session.execute(
                __import__("sqlalchemy").select(Chapter)
                .where(Chapter.project_id == "p1")
            )
            rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].is_locked is False

    _run(_case())
