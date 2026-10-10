"""异步任务调度与线程桥接 - QThread + asyncio 事件循环."""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Coroutine

from src.utils.logger import get_logger


class AsyncBridge:
    """在独立线程中运行 asyncio 事件循环，供 UI 提交协程.

    使用方式：
        bridge = AsyncBridge()
        bridge.start()
        result = bridge.run_async(some_coroutine())
        bridge.stop()
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._logger = get_logger()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="aibooks-async")
            self._thread.start()
            while self._loop is None:
                pass
            self._logger.info("AsyncBridge 事件循环已启动")

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def stop(self) -> None:
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                elapsed = 0.0
                while self._thread.is_alive() and elapsed < 5.0:
                    self._thread.join(timeout=0.1)
                    if self._thread.is_alive():
                        elapsed += 0.1
                        try:
                            from PySide6.QtWidgets import QApplication

                            QApplication.processEvents()
                        except Exception:
                            pass
            self._loop = None
            self._thread = None

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("AsyncBridge 未启动")
        return self._loop

    def run_async(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """在事件循环中运行协程并同步等待结果（阻塞调用线程）."""
        if self._loop is None:
            raise RuntimeError("AsyncBridge 未启动")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def submit_async(self, coro: Coroutine[Any, Any, Any], callback: Callable[[Any], None] | None = None) -> None:
        """提交协程到事件循环，可选回调（非阻塞）."""
        if self._loop is None:
            raise RuntimeError("AsyncBridge 未启动")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        if callback is not None:
            future.add_done_callback(lambda f: callback(f.result()))


_bridge: AsyncBridge | None = None


def get_bridge() -> AsyncBridge:
    global _bridge
    if _bridge is None:
        _bridge = AsyncBridge()
        _bridge.start()
    return _bridge


def stop_bridge() -> None:
    global _bridge
    if _bridge is not None:
        _bridge.stop()
        _bridge = None