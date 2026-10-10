"""后台 worker 生命周期 - 回归测试.

缺陷现场
--------
AI 生成大纲时报错后，控制台出现::

    QThread: Destroyed while thread '' is still running

原因：``ApiWorker``（QThread）由各页面存在 ``self._workers`` 列表里。当页面或
MainWindow 被析构时该列表随之消失；若此时线程仍在 ``run()`` 中（分批大纲的
HTTP 超时高达 900s），C++ 侧 QThread 析构函数就会在"运行中"执行。

修复：
1. ``api_worker`` 维护模块级强引用登记表——只要还在跑就一定不会被回收；
2. ``MainWindow.closeEvent`` 先等待后台任务收尾再让 Qt 销毁窗口。
"""
from __future__ import annotations

import gc
import threading

import pytest

from src.ui.api_worker import ApiWorker, running_worker_count, wait_for_running_workers

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qt_app():
    """worker 需要 QCoreApplication 才能正常启动线程."""
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def _make_gated_worker() -> tuple[ApiWorker, threading.Event, threading.Event]:
    """构造一个可控的 worker：进入 run() 后阻塞，直到 release 被 set."""
    started = threading.Event()
    release = threading.Event()

    def _slow() -> str:
        started.set()
        release.wait(10)
        return "done"

    return ApiWorker(_slow), started, release


def test_running_worker_is_strongly_referenced_by_registry(qt_app) -> None:
    """正在运行的 worker 被登记表兜住：丢弃调用方引用也不会被 GC 销毁."""
    worker, started, release = _make_gated_worker()
    try:
        worker.start()
        assert started.wait(5), "worker 未能在 5s 内启动"
        assert running_worker_count() == 1

        # 模拟"页面被析构、self._workers 列表消失"
        del worker
        gc.collect()

        # 关键断言：即使丢掉了所有调用方引用，线程仍在运行且对象仍存活
        assert running_worker_count() == 1
    finally:
        release.set()

    assert wait_for_running_workers(5000) == 0
    assert running_worker_count() == 0


def test_wait_for_running_workers_reports_remaining(qt_app) -> None:
    """超时后仍未结束的 worker 会被如实计入返回值（供关闭窗口时提示用户）."""
    worker, started, release = _make_gated_worker()
    try:
        worker.start()
        assert started.wait(5)
        # 只给极短预算，worker 仍在阻塞 → 应报告还剩 1 个
        assert wait_for_running_workers(50) == 1
    finally:
        release.set()

    assert wait_for_running_workers(5000) == 0


def test_worker_result_signal_and_registry_cleanup(qt_app) -> None:
    """正常结束的 worker 会发射 result，并自动注销登记."""
    payloads: list[object] = []
    worker = ApiWorker(lambda: {"ok": True})
    worker.result.connect(payloads.append)
    worker.start()

    assert wait_for_running_workers(5000) == 0
    assert running_worker_count() == 0

    # result 是跨线程信号，需要跑一次事件循环才能送达
    from PySide6.QtCore import QCoreApplication

    for _ in range(20):
        QCoreApplication.processEvents()
        if payloads:
            break
    assert payloads == [{"ok": True}]


def test_worker_error_signal_on_exception(qt_app) -> None:
    """worker 内部异常会转成 error 信号，而不是让线程静默崩溃."""
    errors: list[str] = []

    def _boom() -> None:
        raise ValueError("模拟失败")

    worker = ApiWorker(_boom)
    worker.error.connect(errors.append)
    worker.start()

    assert wait_for_running_workers(5000) == 0

    from PySide6.QtCore import QCoreApplication

    for _ in range(20):
        QCoreApplication.processEvents()
        if errors:
            break
    assert errors == ["模拟失败"]
