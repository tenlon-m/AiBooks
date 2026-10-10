"""SQLite 写锁持有者诊断 —— 让 ``database is locked`` 一眼可定位.

为什么需要它
------------
``database is locked`` 的**报错方从来不是肇事方**：真正的问题是"某个会话持有
未提交的 DML，却夹着 AI 网络调用不提交"，而受害的却是当时恰好想写入的另一个人
（网关计数器写回、AI 调用日志、前端自动保存）。

没有上下文的日志只能看到症状::

    AI源计数器写回失败（已忽略，不影响业务）: OperationalError: database is locked

要定位还得自己去翻代码猜。本模块通过在 ORM 层挂事件，维护一张
「当前谁持有未提交写事务」的登记表，于是报错时可以直接打印出肇事者::

    AI源计数器写回 命中 SQLite 写锁冲突，重试已耗尽
    当前有 1 个会话持有未提交的写事务（SQLite 写锁被独占）：
      - 已持有 184.3s | 起始于 09:24:41 | 任务=outline-生成大纲
        | 来源=src/services/outline_service.py:290 in _reset_outline
    最可疑的是持有最久的那个：src/services/outline_service.py:290 in _reset_outline
    （已 184.3s）—— 检查它是否在 AI 网络调用前漏了 release_write_lock()。

实现要点（均已实测验证，SQLAlchemy 2.0.23 + aiosqlite）
-------------------------------------------------------
标记写事务需要**两个**事件，缺一不可：

============================  ==========================================
``do_orm_execute``            捕获 ``session.execute(update/insert/delete)``
``after_flush``               捕获 ORM 对象 flush（``add`` / 属性赋值 + flush）
============================  ==========================================

- 纯 SELECT 也走 ``do_orm_execute``，但 ``is_insert/update/delete`` 全为 False，
  过滤掉即可 —— 而纯读本来也不持有任何 SQLite 写锁。
- 空 flush（没有脏对象）**不会**触发 ``after_flush``，所以只读会话
  ``commit()`` 不会留下误报。
- 清理只能依赖 ``after_commit`` / ``after_rollback`` **且必须复核
  ``session.in_transaction()``**：SAVEPOINT 提交时 ``after_commit`` 同样会触发，
  而外层事务仍在持有写锁（实测确认）。

抓调用栈必须跨 greenlet
-----------------------
SQLAlchemy 异步适配器把同步 Session 跑在 greenlet 里，``frame.f_back`` 链会在
greenlet 根帧断掉 —— ``traceback.extract_stack()`` 在事件回调里只剩 4 帧，
根本看不到业务代码（第一版就是这么写出 ``origin=unknown`` 的）。
正确做法是顺着 ``greenlet.getcurrent().parent`` 链向上走，详见 ``_iter_frames``。

登记表用 ``WeakKeyDictionary`` 以 ``Session`` 为键：会话被回收后条目自动消失，
不会造成内存泄漏。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import weakref
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.exc import OperationalError

_logger = None


def _get_logger() -> Any:
    """延迟获取应用 logger，避免 db 层在导入期依赖全局配置."""
    global _logger
    if _logger is None:
        try:
            from src.utils.logger import get_logger

            _logger = get_logger()
        except Exception:  # noqa: BLE001 - 兜底为模块 logger
            import logging

            _logger = logging.getLogger(__name__)
    return _logger


# 写事务持有超过该秒数即视为"可疑长事务"（正常业务写入都是毫秒级）
LONG_TRANSACTION_WARN_SECONDS = 20.0
# 同一个长事务最多每隔多少秒告警一次，避免刷屏
_REWARN_INTERVAL_SECONDS = 60.0
# 首次 DML 时向上回溯调用栈的帧数上限（按每个 greenlet 计）
_ORIGIN_STACK_DEPTH = 30

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 回溯来源时要跳过的库/自身路径片段（统一按 '/' 比较）
_SKIP_FRAME_PARTS = (
    "/sqlalchemy/",
    "/aiosqlite/",
    "/asyncio/",
    "/contextlib",
    "/site-packages/",
    "/src/db/lock_diagnostics.py",
    "/src/db/session.py",
)


@dataclass
class HeldWriteTransaction:
    """一个正在持有未提交写事务的会话."""

    started_monotonic: float
    started_wall: datetime
    origin: str
    task_name: str
    last_warned_monotonic: float = field(default=0.0)

    @property
    def held_seconds(self) -> float:
        return time.monotonic() - self.started_monotonic

    def describe(self) -> str:
        return (
            f"已持有 {self.held_seconds:.1f}s | 起始于 {self.started_wall:%H:%M:%S}"
            f" | 任务={self.task_name} | 来源={self.origin}"
        )


# session -> 该会话的写事务信息
_HELD: weakref.WeakKeyDictionary[Any, HeldWriteTransaction] = weakref.WeakKeyDictionary()
_installed = False


# --------------------------------------------------------------------------- #
# 安装事件监听
# --------------------------------------------------------------------------- #


def _iter_frames() -> Any:
    """按"从内到外"的顺序产出栈帧，必要时越过 greenlet 边界.

    为什么不能直接用 ``traceback.extract_stack()``
    ----------------------------------------------
    SQLAlchemy 的异步适配器把同步 Session 的实现跑在 **greenlet** 里。
    greenlet 有独立栈，``frame.f_back`` 链会在 greenlet 根帧处断掉 ——
    实测在事件回调里 ``extract_stack()`` 只剩 4 帧，**完全看不到业务代码**，
    于是只能得到 ``origin=unknown``（本模块第一版就踩了这个坑）。

    顺着 ``greenlet.getcurrent().parent`` 链向上走即可拿回主 greenlet 的栈，
    那里保留着完整的 ``await`` 调用链，业务帧（如
    ``src/services/outline_service.py:290 in _reset_outline``）就在其中。
    """
    try:
        import greenlet

        current: Any = greenlet.getcurrent()
    except Exception:  # noqa: BLE001 - 没有 greenlet 时退化为普通栈遍历
        current = None

    if current is None:
        frame: Any = sys._getframe(1)
        while frame is not None:
            yield frame
            frame = frame.f_back
        return

    seen: set[int] = set()
    depth = 0
    while current is not None and depth < 20:
        frame = current.gr_frame
        guard = 0
        while frame is not None and guard < _ORIGIN_STACK_DEPTH * 10:
            if id(frame) not in seen:
                seen.add(id(frame))
                yield frame
            frame = frame.f_back
            guard += 1
        current = current.parent
        depth += 1


def _capture_origin() -> str:
    """找出第一层"业务代码"帧，用于指出写事务是谁开的."""
    try:
        for frame in _iter_frames():
            filename = (frame.f_code.co_filename or "").replace("\\", "/")
            if not filename:
                continue
            if any(part in filename for part in _SKIP_FRAME_PARTS):
                continue
            try:
                display = os.path.relpath(filename, _PROJECT_ROOT).replace("\\", "/")
            except Exception:  # noqa: BLE001
                display = filename
            if display.startswith(".."):
                display = filename
            return f"{display}:{frame.f_lineno} in {frame.f_code.co_name}"
    except Exception:  # noqa: BLE001 - 诊断功能绝不能影响业务
        return "unknown"
    return "unknown"


def _current_task_name() -> str:
    try:
        task = asyncio.current_task()
    except Exception:  # noqa: BLE001 - 无运行中的事件循环
        return "-"
    if task is None:
        return "-"
    return task.get_name() or "-"


def _mark(session: Any) -> None:
    """把会话登记为"持有未提交写事务"。同一事务内只登记一次."""
    if session in _HELD:
        return
    now_mono = time.monotonic()
    _HELD[session] = HeldWriteTransaction(
        started_monotonic=now_mono,
        started_wall=datetime.now(),
        origin=_capture_origin(),
        task_name=_current_task_name(),
        last_warned_monotonic=0.0,
    )


def _unmark(session: Any) -> None:
    """事务真正结束时注销.

    注意 ``after_commit`` 在嵌套事务（SAVEPOINT）提交时也会触发，而外层事务
    仍在持有写锁，因此必须复核 ``in_transaction()`` 才能注销。
    """
    try:
        still_holding = session.in_transaction()
    except Exception:  # noqa: BLE001
        still_holding = False
    if not still_holding:
        _HELD.pop(session, None)


def install_lock_diagnostics() -> None:
    """安装 ORM 事件监听（幂等，可重复调用）."""
    global _installed
    if _installed:
        return

    from sqlalchemy import event
    from sqlalchemy.orm import Session

    @event.listens_for(Session, "do_orm_execute")
    def _on_orm_execute(state: Any) -> None:
        # 纯 SELECT 也走这里，靠这三个标志过滤
        if state.is_insert or state.is_update or state.is_delete:
            _mark(state.session)

    @event.listens_for(Session, "after_flush")
    def _on_after_flush(session: Any, _flush_context: Any) -> None:
        # 空 flush 不会触发本事件（实测确认），所以只读会话 commit 不会误报
        _mark(session)

    @event.listens_for(Session, "after_commit")
    def _on_after_commit(session: Any) -> None:
        _unmark(session)

    @event.listens_for(Session, "after_rollback")
    def _on_after_rollback(session: Any) -> None:
        _unmark(session)

    _installed = True


# --------------------------------------------------------------------------- #
# 查询 / 报告
# --------------------------------------------------------------------------- #


def _prune_locked() -> list[tuple[Any, HeldWriteTransaction]]:
    """清理失效条目并按持有时间排序（最久的在前）."""
    items: list[tuple[Any, HeldWriteTransaction]] = []
    for session, info in list(_HELD.items()):
        try:
            alive = session.in_transaction()
        except Exception:  # noqa: BLE001 - 会话已关闭/已失效
            alive = False
        if not alive:
            # 会话已结束（例如 close() 时隐式回滚），锁已释放，注销即可
            _HELD.pop(session, None)
            continue
        items.append((session, info))
    items.sort(key=lambda kv: kv[1].started_monotonic)
    return items


def held_write_transactions() -> list[HeldWriteTransaction]:
    """返回当前持有未提交写事务的会话信息（最久的在前）."""
    install_lock_diagnostics()
    return [info for _session, info in _prune_locked()]


def is_holding_write_lock(session: Any) -> bool:
    """指定会话当前是否持有未提交的写事务（即攥着 SQLite 写锁）.

    同时接受 ``AsyncSession`` 与其内部同步 ``Session``。
    """
    install_lock_diagnostics()
    target = getattr(session, "sync_session", session)
    if _HELD.get(target) is None:
        return False
    try:
        return bool(target.in_transaction())
    except Exception:  # noqa: BLE001 - 会话已失效
        return False


def describe_lock_context(limit: int = 5) -> str:
    """生成"当前谁攥着写锁"的可读报告，用于锁冲突告警."""
    items = held_write_transactions()
    if not items:
        return (
            "当前没有会话持有未提交的写事务（说明锁是被外部进程占用的，"
            "例如另一个 AiBooks 实例或正在运行备份/迁移脚本）"
        )

    oldest = items[0]
    lines = [
        f"当前有 {len(items)} 个会话持有未提交的写事务（SQLite 写锁被独占）："
    ]
    for info in items[:limit]:
        lines.append(f"  - {info.describe()}")
    if len(items) > limit:
        lines.append(f"  ... 另有 {len(items) - limit} 个")

    lines.append(
        f"持有最久的是：{oldest.origin}（已 {oldest.held_seconds:.1f}s）。"
        f"若它正在或即将进行 AI 网络调用，检查是否漏调 release_write_lock()；"
        f"若只是普通业务写入，则说明锁争用来自写入过于频繁。"
    )
    return "\n".join(lines)


def is_lock_error(exc: BaseException) -> bool:
    """判定是否为 SQLite 锁冲突.

    SQLAlchemy 把 ``sqlite3.OperationalError`` 包成
    ``sqlalchemy.exc.OperationalError``，原生异常挂在 ``exc.orig``。
    """
    if isinstance(exc, OperationalError):
        msg = str(exc.orig) if exc.orig is not None else str(exc)
        return "database is locked" in msg.lower()
    return False


def report_lock_failure(
    logger: Any,
    action: str,
    exc: BaseException,
    detail: str | None = None,
) -> None:
    """记录一次"重试耗尽仍失败"的写操作.

    - **锁冲突** → ERROR 级别，并附上当前写锁持有者上下文（一眼定位肇事者）；
    - **其它错误** → 保持 WARNING（这类写多是遥测，失败不影响业务）。
    """
    detail = detail or f"{type(exc).__name__}: {exc}"
    if not is_lock_error(exc):
        logger.warning(f"{action}失败（已忽略，不影响业务）: {detail}")
        return
    logger.error(
        f"{action}失败（已忽略，不影响业务）: SQLite 写锁冲突，重试已耗尽\n"
        f"{describe_lock_context()}\n"
        f"原始错误: {detail}"
    )


# --------------------------------------------------------------------------- #
# 长事务看门狗
# --------------------------------------------------------------------------- #


async def long_transaction_watchdog(
    interval_seconds: float = 5.0,
    threshold_seconds: float = LONG_TRANSACTION_WARN_SECONDS,
) -> None:
    """后台任务：任何写事务持有超过 ``threshold_seconds`` 就打 WARNING.

    这是本模块最有价值的部分：不必等别人撞锁报错，**锁被攥住的那一刻**就能在
    日志里看到肇事者，把"事后翻代码找"变成"当时就知道"。

    作为一个 ``asyncio.Task`` 长期运行，取消即退出。
    """
    install_lock_diagnostics()
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            for info in held_write_transactions():
                if info.held_seconds < threshold_seconds:
                    continue
                since_warn = info.held_seconds - info.last_warned_monotonic
                if info.last_warned_monotonic and since_warn < _REWARN_INTERVAL_SECONDS:
                    continue
                info.last_warned_monotonic = info.held_seconds
                _get_logger().warning(
                    f"检测到长写事务：SQLite 写锁已被持有 {info.held_seconds:.1f}s"
                    f"（阈值 {threshold_seconds:.0f}s），期间其它写入会撞 "
                    f"database is locked。\n  {info.describe()}"
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - 诊断任务绝不能把主流程带崩
            _get_logger().debug(f"长事务看门狗单轮异常（已忽略）: {e}")
