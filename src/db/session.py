"""SQLAlchemy 异步引擎与会话工厂."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.app_config import AppConfig

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

# SQLite 忙等待时长（秒）：并发写入时等待锁释放而不是立刻抛 database is locked
# 健康检查等多源串行写场景下，30s 仍可能被打穿；提至 60s 与网关重试预算对齐
_SQLITE_BUSY_TIMEOUT_SECONDS = 60


def _install_sqlite_pragmas(engine: AsyncEngine) -> None:
    """为 SQLite 开启 WAL 与 busy_timeout，缓解多会话并发写导致的 database is locked."""
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        try:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_SECONDS * 1000}")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception:  # noqa: BLE001 - PRAGMA 失败不应阻断连接
            pass


def init_engine(config: AppConfig) -> None:
    global _engine, _session_factory
    is_sqlite = config.db_url.startswith("sqlite")
    connect_args: dict[str, Any] = {}
    if is_sqlite:
        # sqlite3 的 timeout 即 busy 等待秒数，默认过短会在并发写时立刻 database is locked
        connect_args["timeout"] = _SQLITE_BUSY_TIMEOUT_SECONDS

    _engine = create_async_engine(
        config.db_url,
        echo=config.db_echo,
        future=True,
        connect_args=connect_args,
    )
    if is_sqlite:
        _install_sqlite_pragmas(_engine)
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    # 装上"谁在持有写锁"的登记表。装上之后，任何 database is locked 告警都会
    # 自动带上肇事者的代码位置；长事务看门狗也依赖它（见 lock_diagnostics）。
    from src.db.lock_diagnostics import install_lock_diagnostics

    install_lock_diagnostics()


async def release_write_lock(session: AsyncSession) -> None:
    """结束当前事务，释放 SQLite 写锁。

    **必须在「每次长耗时非数据库操作（AI 网络调用）」之前调用。**

    背景（已在 SQLite WAL + aiosqlite 下实测验证）
    --------------------------------------------
    SQLite 是单写者模型，且锁是**数据库级**而非表级。SQLAlchemy 的 Session
    只要执行过任一 DML（insert / update / delete，或显式 ``flush()``），
    就会开启写事务并一直持有写锁，直到 ``commit()`` / ``rollback()``：

        写事务未提交时，另一连接的写入结果
            => OperationalError: (sqlite3.OperationalError) database is locked

    而**纯 SELECT 的只读会话不持有任何 SQLite 写锁**（实测另一连接可正常
    写入，且该会话之后自己再写也不会失败）。因此问题只来自一个源头：

        **本会话有未提交的 DML，却夹着 AI 网络调用不提交。**

    这段窗口有多长，写锁就被独占多久。期间其它写入者全部在
    ``busy_timeout``（60s）耗尽后失败：

    - 网关的 AI 源计数器写回 → 日志
      "AI源计数器写回失败（已忽略，不影响业务）: OperationalError: database is locked"
    - AI 调用日志落库
    - 前端自动保存 ``POST /api/creation/save`` → 连续失败 3 次后弹窗
      "自动保存多次失败，请检查存储空间与数据库状态"

    最典型的触发点：``OutlineService.generate_outline_batch`` 先由
    ``_reset_outline()`` 的 ``flush()`` 拿到写锁，紧接着调用
    ``AutoSupportingService.ensure_sufficient_for_outline`` 发起数十秒到
    数分钟的网关调用，直到最后才 ``commit()``。

    安全性
    ------
    会话工厂已配置 ``expire_on_commit=False``（见 ``init_engine``），提交后
    已加载的 ORM 对象仍可安全读取属性，无需重新查询；本函数也不会让 Session
    失效（下次访问会自动开启新事务）。

    - 事务内只有读操作时：本函数只是结束事务，不改变任何数据（等价于空操作）。
    - 事务内有写操作时：会把这些写提前落库，即"AI 调用失败也不会回滚这批写"。
      调用方需确认这是期望语义。

    注意：会话工厂配置了 ``autoflush=False``，所以**单纯给 ORM 属性赋值不会
    立刻写库、也就不会持锁**；只有真正发出过 DML（``await session.execute(
    insert/update/delete...)`` 或显式 ``await session.flush()``）才会持锁。
    因此本函数在"只改了对象属性"的场景下是空操作，加上它不会有副作用。
    """
    if session.in_transaction():
        await session.commit()


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("数据库引擎未初始化，请先调用 init_engine()")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("会话工厂未初始化，请先调用 init_engine()")
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """内部使用的 async context manager."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入用的异步生成器."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None