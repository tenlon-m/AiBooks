"""AI 源调用通知器 — 纯 Python 观察者模式，不依赖 Qt.

gateway 每次 AI 调用命中源后通知所有注册的 hook，
UI 层（StatusBarRuntimeWidget）注册回调后即可实时感知实际调用的 AI 源。
"""
from __future__ import annotations

import threading
from collections.abc import Callable

SourceHook = Callable[[str, str | None, str, str], None]

_hooks: list[SourceHook] = []
_lock = threading.Lock()


def register_source_hook(hook: SourceHook) -> None:
    with _lock:
        if hook not in _hooks:
            _hooks.append(hook)


def unregister_source_hook(hook: SourceHook) -> None:
    with _lock:
        if hook in _hooks:
            _hooks.remove(hook)


def notify_source_call(
    source_name: str,
    failover_from: str | None,
    module: str,
    scene: str,
) -> None:
    with _lock:
        snapshot = list(_hooks)
    for hook in snapshot:
        try:
            hook(source_name, failover_from, module, scene)
        except Exception:
            pass