"""写锁持有者诊断 - 回归测试.

被测目标（``src/db/lock_diagnostics.py``）:
让 ``database is locked`` 从"只有症状"变成"直接指出肇事者"。本文件锁定它的
三个契约：

1. **能认出谁在持锁** —— 只有真正发出过 DML 的会话才被登记；
   纯 SELECT 不登记，已提交/已回滚/已关闭的不登记。
2. **能说出在哪持锁** —— 登记时抓取的调用栈要指向业务代码（哪个文件哪一行）。
3. **能提前预警** —— 看门狗在锁被长时间攥住时主动告警。

事件时机均以实测为准（SQLAlchemy 2.0.23 + aiosqlite）：
``do_orm_execute`` 捕获显式 DML，``after_flush`` 捕获 ORM 对象 flush，
空 flush / 纯读都不触发。
"""
from __future__ import annotations

import asyncio
from typing import Any, Coroutine

import pytest
from sqlalchemy import Column, Integer, String, insert, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.db import lock_diagnostics as diag
from src.db.lock_diagnostics import (
    describe_lock_context,
    held_write_transactions,
    install_lock_diagnostics,
    is_holding_write_lock,
    is_lock_error,
    long_transaction_watchdog,
    report_lock_failure,
)

# 类级别的 ORM 事件监听，装一次即全程生效
install_lock_diagnostics()


class _Base(DeclarativeBase):
    pass


class Widget(_Base):
    __tablename__ = "diag_widget"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(20))


class FakeLogger:
    """记录日志调用的假 logger（应用用的是 loguru，caplog 抓不到）."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def warning(self, msg: str, *args: Any) -> None:
        self.records.append(("warning", msg % args if args else str(msg)))

    def error(self, msg: str, *args: Any) -> None:
        self.records.append(("error", msg % args if args else str(msg)))

    def info(self, msg: str, *args: Any) -> None:
        self.records.append(("info", msg % args if args else str(msg)))

    def debug(self, msg: str, *args: Any) -> None:
        self.records.append(("debug", msg % args if args else str(msg)))

    def messages(self, level: str | None = None) -> list[str]:
        return [m for lv, m in self.records if level is None or lv == level]


async def _make_factory(
    tmp_path: Any, busy_timeout: float = 5.0
) -> async_sessionmaker:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'diag.db'}",
        connect_args={"timeout": busy_timeout},
    )
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


# --------------------------------------------------------------------------- #
# 1. 能认出谁在持锁
# --------------------------------------------------------------------------- #


def test_explicit_dml_is_registered(tmp_path: Any) -> None:
    """session.execute(update(...)) —— 只有 do_orm_execute 能捕获."""

    async def _case() -> None:
        factory = await _make_factory(tmp_path)
        async with factory() as session:
            assert is_holding_write_lock(session) is False
            await session.execute(insert(Widget).values(name="a"))
            assert is_holding_write_lock(session) is True, "显式 DML 之后应被登记"
            await session.rollback()
            assert is_holding_write_lock(session) is False, "回滚后应注销"

    _run(_case())


def test_orm_flush_is_registered(tmp_path: Any) -> None:
    """ORM 对象 flush —— 只有 after_flush 能捕获."""

    async def _case() -> None:
        factory = await _make_factory(tmp_path)
        async with factory() as session:
            session.add(Widget(name="b"))
            # autoflush=False：add 本身不写库，也就还没持锁
            assert is_holding_write_lock(session) is False
            await session.flush()
            assert is_holding_write_lock(session) is True, "flush 之后应被登记"
            await session.commit()
            assert is_holding_write_lock(session) is False, "提交后应注销"

    _run(_case())


def test_readonly_session_is_never_registered(tmp_path: Any) -> None:
    """纯 SELECT 不持锁，因此不应被登记（否则会产生大量误报）."""

    async def _case() -> None:
        factory = await _make_factory(tmp_path)
        async with factory() as session:
            await session.execute(select(Widget))
            assert is_holding_write_lock(session) is False
            await session.commit()
            assert is_holding_write_lock(session) is False

    _run(_case())


def test_object_attribute_change_without_flush_is_not_registered(tmp_path: Any) -> None:
    """autoflush=False：只改属性未 flush，实际没写库，不该报成持锁."""

    async def _case() -> None:
        factory = await _make_factory(tmp_path)
        async with factory() as session:
            session.add(Widget(name="c"))
            await session.commit()
        async with factory() as session:
            widget = (await session.execute(select(Widget))).scalar_one()
            widget.name = "changed"
            assert is_holding_write_lock(session) is False
            await session.rollback()

    _run(_case())


def test_nested_commit_keeps_registration(tmp_path: Any) -> None:
    """SAVEPOINT 提交时 after_commit 也会触发，但外层事务仍持锁.

    这是最容易写错的地方：如果注销时不复核 ``in_transaction()``，就会漏报
    —— 而这恰好是"写锁被长事务攥住"最容易发生的形式。
    """

    async def _case() -> None:
        factory = await _make_factory(tmp_path)
        async with factory() as session:
            await session.execute(insert(Widget).values(name="d"))
            async with session.begin_nested():
                session.add(Widget(name="e"))
            # begin_nested 退出时触发了 after_commit，但外层事务还开着
            assert session.in_transaction() is True
            assert is_holding_write_lock(session) is True, (
                "嵌套事务提交后外层仍持有写锁，不能被误注销"
            )
            await session.rollback()
            assert is_holding_write_lock(session) is False

    _run(_case())


def test_closed_session_is_not_reported(tmp_path: Any) -> None:
    """会话被关闭（未显式提交）后不应继续出现在诊断报告里."""

    async def _case() -> None:
        factory = await _make_factory(tmp_path)
        session = factory()
        await session.execute(insert(Widget).values(name="f"))
        assert is_holding_write_lock(session) is True
        await session.close()
        assert is_holding_write_lock(session) is False, "关闭后锁已释放，应自动清理"

    _run(_case())


# --------------------------------------------------------------------------- #
# 2. 能说出在哪持锁
# --------------------------------------------------------------------------- #


def test_origin_points_at_business_code(tmp_path: Any) -> None:
    """调用栈抓取应越过 SQLAlchemy/asyncio 内部帧，指向业务代码."""

    async def _case() -> None:
        factory = await _make_factory(tmp_path)
        async with factory() as session:
            await session.execute(update(Widget).where(Widget.id == 1).values(name="x"))
            infos = held_write_transactions()
            mine = [
                i for i in infos if "test_lock_diagnostics.py" in i.origin
            ]
            assert mine, f"未找到指向本测试文件的来源，实际: {[i.origin for i in infos]}"
            # 形如 tests/test_lock_diagnostics.py:NNN in test_origin_points_at_business_code
            assert " in " in mine[0].origin
            assert "sqlalchemy" not in mine[0].origin
            await session.rollback()

    _run(_case())


def test_describe_lock_context_names_the_culprit(tmp_path: Any) -> None:
    async def _case() -> None:
        factory = await _make_factory(tmp_path)
        async with factory() as session:
            await session.execute(insert(Widget).values(name="g"))
            report = describe_lock_context()
            assert "持有未提交的写事务" in report
            assert "test_lock_diagnostics.py" in report
            assert "release_write_lock" in report, "报告应给出修复提示"
            await session.rollback()

    _run(_case())


def test_describe_lock_context_when_no_holder() -> None:
    """没有任何持锁者时，要提示"可能是外部进程占用"，避免误导排查方向."""

    async def _case() -> None:
        report = describe_lock_context()
        assert "没有会话持有未提交的写事务" in report
        assert "外部进程" in report

    _run(_case())


# --------------------------------------------------------------------------- #
# 3. 日志级别与上下文
# --------------------------------------------------------------------------- #


def test_report_lock_failure_escalates_to_error() -> None:
    """锁冲突 → ERROR 且带上"谁攥着锁"；其它错误 → WARNING（保持原行为）."""
    import sqlite3

    from sqlalchemy.exc import OperationalError

    logger = FakeLogger()
    lock_exc = OperationalError(
        "UPDATE ai_sources ...",
        {},
        sqlite3.OperationalError("database is locked"),
    )
    report_lock_failure(logger, "AI源计数器写回", lock_exc, detail="OperationalError: ...")

    errors = logger.messages("error")
    assert len(errors) == 1
    assert "AI源计数器写回" in errors[0]
    assert "写锁冲突" in errors[0]
    assert "写事务" in errors[0], "ERROR 日志必须附带写锁持有者上下文"
    assert logger.messages("warning") == []

    other = FakeLogger()
    report_lock_failure(other, "AI源计数器写回", RuntimeError("网络抖动"))
    assert other.messages("error") == []
    assert len(other.messages("warning")) == 1
    assert "已忽略，不影响业务" in other.messages("warning")[0]


def test_is_lock_error_distinguishes_lock_from_other_operational_errors() -> None:
    import sqlite3

    from sqlalchemy.exc import OperationalError

    locked = OperationalError(
        "UPDATE t SET a=1", {}, sqlite3.OperationalError("database is locked")
    )
    other = OperationalError(
        "UPDATE t SET a=1", {}, sqlite3.OperationalError("no such table: t")
    )
    assert is_lock_error(locked) is True
    assert is_lock_error(other) is False
    assert is_lock_error(RuntimeError("database is locked")) is False


# --------------------------------------------------------------------------- #
# 4. 端到端：真实锁冲突的日志必须点名肇事代码
# --------------------------------------------------------------------------- #


async def _gateway_style_counter_writeback(
    factory: async_sessionmaker, logger: FakeLogger, attempts: int = 2
) -> bool:
    """仿 ``gateway._apply_source_updates``：独立会话写入 + 重试 + 失败上报.

    这正是用户日志里报错的那段逻辑（真实实现是 ``UPDATE ai_sources``）。
    """
    last_error: BaseException | None = None
    for _ in range(attempts):
        try:
            async with factory() as session:
                await session.execute(insert(Widget).values(name="counter"))
                await session.commit()
            return True
        except Exception as e:  # noqa: BLE001 - 与真实实现一致：吞掉后重试
            last_error = e
            await asyncio.sleep(0.02)
    assert last_error is not None
    report_lock_failure(
        logger,
        "AI源计数器写回",
        last_error,
        detail=f"{type(last_error).__name__}: {last_error}",
    )
    return False


def test_conflict_report_points_at_culprit_code(tmp_path: Any) -> None:
    """复现生产事故形状：A 会话 flush 后去调 AI，B 会话此时写入被拒.

    关键断言：那条 ERROR 日志必须直接说出**是哪个函数**攥着锁
    （A 会话的 DML 调用点），而不是只报一句 database is locked。
    这才是"以后再出现时一眼定位"的验收标准。
    """

    async def _case() -> None:
        factory = await _make_factory(tmp_path, busy_timeout=0.2)
        logger = FakeLogger()

        async def _culprit_outline_reset(session: Any) -> None:
            """模拟 OutlineService._reset_outline：先落库拿锁，再进 AI 调用."""
            await session.execute(insert(Widget).values(name="outline"))
            # ↓ 这一行等价于"攥着写锁去调 AI"，期间网关计数器写回必然失败
            assert await _gateway_style_counter_writeback(factory, logger) is False
            await session.rollback()

        async with factory() as session:
            await _culprit_outline_reset(session)

        errors = logger.messages("error")
        assert len(errors) == 1, f"锁冲突应记恰好一条 ERROR，实际: {logger.records}"
        report = errors[0]
        assert "写锁冲突" in report
        assert "已忽略，不影响业务" in report, "仍需保留原有的非致命语义"
        assert "_culprit_outline_reset" in report, (
            f"日志必须点名肇事函数，实际输出:\n{report}"
        )
        assert "test_lock_diagnostics.py" in report, (
            f"日志必须给出肇事代码位置，实际输出:\n{report}"
        )
        assert "release_write_lock" in report, "日志必须给出修复提示"

    _run(_case())


# --------------------------------------------------------------------------- #
# 5. 长事务看门狗（提前预警）
# --------------------------------------------------------------------------- #


def test_watchdog_warns_when_write_lock_held_too_long(tmp_path: Any) -> None:
    async def _case() -> None:
        factory = await _make_factory(tmp_path)
        logger = FakeLogger()
        original = diag._logger
        diag._logger = logger
        try:
            async with factory() as session:
                await session.execute(insert(Widget).values(name="h"))
                task = asyncio.create_task(
                    long_transaction_watchdog(interval_seconds=0.02, threshold_seconds=0.05)
                )
                try:
                    await asyncio.sleep(0.25)
                finally:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task

                warnings = logger.messages("warning")
                assert warnings, "持有写锁超过阈值应触发告警"
                assert "长写事务" in warnings[0]
                assert "test_lock_diagnostics.py" in warnings[0], (
                    "告警必须指出开事务的代码位置，否则无法定位"
                )
                await session.rollback()
        finally:
            diag._logger = original

    _run(_case())


def test_watchdog_is_silent_for_short_transactions(tmp_path: Any) -> None:
    """阈值内的正常写入不应产生噪音."""

    async def _case() -> None:
        factory = await _make_factory(tmp_path)
        logger = FakeLogger()
        original = diag._logger
        diag._logger = logger
        try:
            async with factory() as session:
                task = asyncio.create_task(
                    long_transaction_watchdog(interval_seconds=0.02, threshold_seconds=5.0)
                )
                try:
                    await session.execute(insert(Widget).values(name="i"))
                    await session.commit()
                    await asyncio.sleep(0.15)
                finally:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
            assert logger.messages("warning") == []
        finally:
            diag._logger = original

    _run(_case())


def test_watchdog_survives_and_can_be_cancelled() -> None:
    """看门狗自身异常不能把主流程带崩，且必须可正常取消."""

    async def _case() -> None:
        task = asyncio.create_task(
            long_transaction_watchdog(interval_seconds=0.01, threshold_seconds=0.02)
        )
        await asyncio.sleep(0.05)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    _run(_case())
