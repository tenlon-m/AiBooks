"""项目级操作锁 - 防止同一项目同时运行多个互斥操作.

支持的操作类型：writing / fill / repair / summary / iteration。
writing/fill/repair/iteration 互斥（都修改章节内容），summary 可与 writing 并行但不可与 fill/repair/iteration 并行。
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from typing import AsyncGenerator

_project_ops: dict[str, set[str]] = {}
_lock = threading.Lock()

_ALLOWED_PARALLEL: set[tuple[str, str]] = {
    ("summary", "writing"),
    ("writing", "summary"),
}


def _has_conflict(project_id: str, operation: str) -> str | None:
    ops = _project_ops.get(project_id, set())
    for existing in ops:
        if existing == operation:
            return existing
        if (operation, existing) not in _ALLOWED_PARALLEL:
            return existing
    return None


def get_running_op(project_id: str) -> str | None:
    """返回当前正在运行的操作类型，无则 None."""
    with _lock:
        ops = _project_ops.get(project_id)
        if not ops:
            return None
        return ", ".join(sorted(ops))


def is_project_busy(project_id: str) -> bool:
    """项目是否有互斥操作正在运行."""
    with _lock:
        return bool(_project_ops.get(project_id))


@asynccontextmanager
async def acquire_op(project_id: str, operation: str) -> AsyncGenerator[None, None]:
    """尝试获取项目操作锁，已被占用则 raise ValueError.

    互斥规则：
    - writing 与 fill/repair/summary/iteration 互斥
    - fill 与 writing/repair/summary/iteration 互斥
    - repair 与 writing/fill/summary/iteration 互斥
    - iteration 与 writing/fill/repair/summary 互斥
    - summary 与 fill/repair/iteration 互斥，但可与 writing 并行
    """
    with _lock:
        existing = _has_conflict(project_id, operation)
        if existing:
            raise ValueError(f"项目已有操作进行中（{existing}），无法启动 {operation}")
        _project_ops.setdefault(project_id, set()).add(operation)
    try:
        yield
    finally:
        with _lock:
            ops = _project_ops.get(project_id)
            if ops:
                ops.discard(operation)
                if not ops:
                    del _project_ops[project_id]


def release_op(project_id: str, operation: str) -> None:
    """显式释放操作锁（用于 SSE 流提前终止时清理）."""
    with _lock:
        ops = _project_ops.get(project_id)
        if ops:
            ops.discard(operation)
            if not ops:
                del _project_ops[project_id]


def try_set_op(project_id: str, operation: str) -> bool:
    """尝试设置操作锁，成功返回 True，冲突返回 False.

    互斥规则：
    - writing 与 fill/repair/summary/iteration 互斥
    - fill 与 writing/repair/summary/iteration 互斥
    - repair 与 writing/fill/summary/iteration 互斥
    - iteration 与 writing/fill/repair/summary 互斥
    - summary 与 fill/repair/iteration 互斥，但可与 writing 并行
    """
    with _lock:
        existing = _has_conflict(project_id, operation)
        if existing:
            return False
        _project_ops.setdefault(project_id, set()).add(operation)
        return True