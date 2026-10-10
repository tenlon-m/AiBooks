"""API 层通用工具 - 端点级重试/容错.

提供 SQLAlchemy / aiosqlite 锁冲突重试装饰器，作用于 FastAPI endpoint 函数。
仅识别 SQLite "database is locked" 类错误，其它 OperationalError 不在重试范围。
"""
from __future__ import annotations

import asyncio
import functools
import inspect
from typing import Any, Awaitable, Callable, TypeVar

from src.db.lock_diagnostics import describe_lock_context, is_lock_error
from src.utils.logger import get_logger

_logger = get_logger()

T = TypeVar("T")


def _copy_typed_signature(wrapper: Callable, func: Callable) -> None:
    """把原始函数的签名（注解已解析为实际类型）设到 wrapper 上.

    `@functools.wraps` 复制了 `__wrapped__`，`inspect.signature` 能返回原始签名，
    但在 `from __future__ import annotations`（PEP 563）下注解是字符串。
    FastAPI 的 `get_typed_signature` 用 `wrapper.__globals__` 解析字符串注解，
    而 `wrapper.__globals__` 是本模块的命名空间，不包含 endpoint 所在模块的
    Pydantic 模型类 → 注解无法解析 → FastAPI 把 Pydantic 模型参数误判为
    query 参数 → 422 ``loc: ['query', 'req']``。

    这里用原始函数的 `__globals__` 预先解析注解为实际类型，再设 `__signature__`，
    FastAPI 看到 `__signature__` 后直接使用，注解已是实际类型无需再解析。
    """
    sig = inspect.signature(func)
    globalns = getattr(func, "__globals__", {})
    typed_params = []
    for param in sig.parameters.values():
        ann = param.annotation
        if isinstance(ann, str):
            try:
                ann = eval(ann, globalns)
            except Exception:
                pass
        typed_params.append(
            inspect.Parameter(
                name=param.name,
                kind=param.kind,
                default=param.default,
                annotation=ann,
            )
        )
    wrapper.__signature__ = inspect.Signature(typed_params)


def retry_on_locked(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    backoff_factor: float = 2.0,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """SQLite 锁冲突自动重试装饰器.

    适用于 FastAPI endpoint 函数。当捕获到 sqlite3 "database is locked" 时，
    按指数退避（base_delay * backoff_factor ** attempt）重试，
    超出 max_attempts 后抛出最后一次的异常。

    Args:
        max_attempts: 最大尝试次数（含首次），默认 3。
        base_delay: 首次重试前的等待秒数，默认 0.5。
        backoff_factor: 退避倍数，默认 2.0 → 0.5s / 1s / 2s。

    Notes:
        - 仅识别 "database is locked"，其它 OperationalError 不重试。
        - 不会破坏 endpoint 的参数签名/返回值，仅在外层包一层 try/except。
        - 与 db/session.py 的 busy_timeout=60s 互补：单次 endpoint
          内 60s 内仍未拿到锁时，靠此装饰器再叠加 3 次重试，容忍 ~6 分钟窗口。
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exc: BaseException | None = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    if not is_lock_error(exc):
                        raise
                    last_exc = exc
                    if attempt + 1 >= max_attempts:
                        # 重试已耗尽：说明锁被别人长时间独占。ERROR 级别 + 付上
                        # "当前谁攥着写锁"，直接指出肇事代码位置，免去事后翻代码。
                        _logger.error(
                            "endpoint %s 重试 %d 次后仍 database is locked，放弃重试\n%s",
                            getattr(func, "__name__", repr(func)),
                            max_attempts,
                            describe_lock_context(),
                        )
                        raise
                    delay = base_delay * (backoff_factor ** attempt)
                    _logger.info(
                        "endpoint %s 第 %d 次遭遇锁冲突，%.2fs 后重试: %s",
                        getattr(func, "__name__", repr(func)),
                        attempt + 1,
                        delay,
                        str(exc.orig if exc.orig else exc),
                    )
                    await asyncio.sleep(delay)
            # 理论不可达；保险起见
            assert last_exc is not None
            raise last_exc

        _copy_typed_signature(wrapper, func)
        return wrapper

    return decorator