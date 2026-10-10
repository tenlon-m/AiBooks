"""通用后台工作线程 - 在 QThread 中执行任意可调用对象，通过信号返回结果."""
from __future__ import annotations

import time
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

# 正在运行的 worker 全局登记表。
#
# 为什么需要这个强引用表：ApiWorker 由各页面保存在自己的 self._workers 列表里。
# 当承载它的页面/QStackedWidget/MainWindow 被析构（关闭窗口、销毁对话框）时，
# 那些列表会连同控件一起消失；若此时 QThread 仍在 run() 中——例如分批大纲的
# HTTP 超时高达 900s——C++ 侧的 QThread 析构函数就会在"运行中"执行，Qt 打印
#
#     QThread: Destroyed while thread '' is still running
#
# 并可能导致进程崩溃。用一个模块级集合兜住生命周期后，worker 只要还在跑就
# 一定存在强引用；start() 时登记、finished 时注销。
_running_workers: set["ApiWorker"] = set()


class ApiWorker(QThread):
    """在后台线程执行函数，完成后发射 result 或 error 信号.

    用法:
        worker = ApiWorker(some_func, arg1, arg2, kw1=v1)
        worker.result.connect(on_success)
        worker.error.connect(on_failure)
        worker.start()
    """

    result = Signal(object)
    error = Signal(str)

    def __init__(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs
        # 线程结束后从登记表移除并交给 Qt 回收
        self.finished.connect(self._release)

    def start(self, *args: Any, **kwargs: Any) -> None:
        # 先登记再启动：避免 start() 与 finished 之间的窗口里被 GC
        _running_workers.add(self)
        super().start(*args, **kwargs)

    def _release(self) -> None:
        """线程结束回调：注销登记并安排对象销毁."""
        _running_workers.discard(self)
        # 本槽由 finished 信号在主线程触发，此刻 run() 已返回，删除是安全的。
        # 调用方不应在 worker 结束后再访问其 Qt 方法（如 wait()/isRunning()）。
        self.deleteLater()

    def run(self) -> None:
        try:
            res = self._func(*self._args, **self._kwargs)
            self.result.emit(res)
        except Exception as e:
            self.error.emit(str(e))


def running_worker_count() -> int:
    """当前仍在运行的后台任务数."""
    from src.ui.sse_worker import _running_sse_workers
    return len(_running_workers) + len(_running_sse_workers)


def wait_for_running_workers(timeout_ms: int = 5000) -> int:
    """等待所有后台 worker 收尾，返回超时后仍在运行的数量.

    供 MainWindow.closeEvent 调用：Qt 在 QThread 运行中析构对象会打印
    "QThread: Destroyed while thread '' is still running"。

    Args:
        timeout_ms: 总等待预算（毫秒），多个 worker 共享该预算。

    Returns:
        超时后仍在运行的 worker 数量（0 表示全部已收尾）。
    """
    from src.ui.sse_worker import _running_sse_workers
    deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
    all_workers = list(_running_workers) + list(_running_sse_workers)
    for worker in all_workers:
        try:
            if hasattr(worker, "stop"):
                worker.stop()
        except Exception:
            pass
    for worker in all_workers:
        try:
            while worker.isRunning():
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if remaining_ms <= 0:
                    break
                worker.wait(min(remaining_ms, 100))
                try:
                    from PySide6.QtWidgets import QApplication
                    QApplication.processEvents()
                except Exception:
                    pass
            if not worker.isRunning():
                _running_workers.discard(worker)
                _running_sse_workers.discard(worker)
        except RuntimeError:
            _running_workers.discard(worker)
            _running_sse_workers.discard(worker)
    return len(_running_workers) + len(_running_sse_workers)
