"""AI 调用重试策略 - 递增重试，429限流不重试直接故障转移，500服务端错误加长退避."""
from __future__ import annotations

import asyncio
import re
from typing import Any, Callable, Coroutine, TypeVar

from src.utils.logger import get_logger

T = TypeVar("T")


def describe_exception(exc: BaseException) -> str:
    """异常可读描述.

    部分网络异常（如 httpx 的超时/连接错误）str() 为空，只打印 {e} 会得到空白
    日志（"重试 3 次后仍失败: "），无法排障；因此必须带上异常类型名。
    """
    detail = str(exc).strip() or repr(exc)
    for sep in ("For more information check:", "See "):
        idx = detail.find(sep)
        if idx != -1:
            detail = detail[:idx].rstrip()
    return f"{type(exc).__name__}: {detail}"


def _is_rate_limited(exc: BaseException) -> bool:
    """判断是否为 429 限流错误（不重试，直接故障转移）."""
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code == 429:
        return True
    return "429" in str(exc) and "Too Many Requests" in str(exc)


def _is_server_error(exc: BaseException) -> bool:
    """判断是否为 5xx 服务端错误（需要更长退避时间）."""
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code is not None and 500 <= status_code < 600:
        return True
    return "500" in str(exc) and "Internal Server Error" in str(exc)


def _is_client_error(exc: BaseException) -> bool:
    """判断是否为 4xx 客户端错误（非 429 限流）.

    4xx 错误是请求体问题（参数不合法/模型不支持等），重试同一源无意义，
    直接跳过重试让上层故障转移。从 RuntimeError 消息中提取 ``HTTP xxx`` 状态码。
    """
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code is not None and 400 <= status_code < 500 and status_code != 429:
        return True
    match = re.search(r"HTTP (\d{3})", str(exc))
    if match:
        code = int(match.group(1))
        if 400 <= code < 500 and code != 429:
            return True
    return False


class RetryPolicy:
    """递增重试策略，单源内重试.

    - 4xx 限流(429): 不重试，直接故障转移
    - 4xx 客户端错误(400/403/404等): 不重试，直接故障转移（请求体问题换源可能解决）
    - 5xx 服务端错误: 加长退避（5s/10s/20s），给服务端恢复时间
    - 其他错误: 标准退避（1s/2s/4s）
    - 重试日志级别为 INFO（正常容错流程），仅最终失败记录 ERROR
    """

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.logger = get_logger()

    async def execute(self, func: Callable[..., Coroutine[Any, Any, T]], *args: Any, **kwargs: Any) -> T:
        """执行带重试的异步调用.

        Args:
            func: 异步函数
            args/kwargs: 函数参数

        Returns:
            函数返回值

        Raises:
            最后一次异常
        """
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exc = e
                if _is_rate_limited(e):
                    self.logger.info(
                        f"AI 源限流 (429)，跳过重试直接故障转移: {describe_exception(e)}"
                    )
                    raise e
                if _is_client_error(e):
                    self.logger.info(
                        f"AI 源返回 4xx 客户端错误，跳过重试直接故障转移: {describe_exception(e)}"
                    )
                    raise e
                if attempt < self.max_retries:
                    if _is_server_error(e):
                        delay = 5.0 * (2 ** attempt)
                    else:
                        delay = self.base_delay * (2 ** attempt)
                    self.logger.info(
                        f"第 {attempt + 1} 次调用失败，{delay:.0f}s 后重试: "
                        f"{describe_exception(e)}"
                    )
                    await asyncio.sleep(delay)
                else:
                    self.logger.error(
                        f"重试 {self.max_retries} 次后仍失败: {describe_exception(e)}"
                    )
        assert last_exc is not None
        raise last_exc