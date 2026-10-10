"""项目级操作锁 - 防止同一项目同时运行多个互斥操作.

支持的操作类型：writing / fill / repair / summary。
writing/fill/repair 互斥（都修改章节内容），summary 可与 writing 并行但不可与 fill/repair 并行。
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

_project_ops: dict[str, str] = {}
_lock = asyncio.Lock()


def get_running_op(project_id: str) -> str | None:
    """返回当前正在运行的操作类型，无则 None."""
    return _project_ops.get(project_id)


def is_project_busy(project_id: str) -> bool:
    """项目是否有互斥操作正在运行."""
    return project_id in _project_ops


@asynccontextmanager
async def acquire_op(project_id: str, operation: str) -> AsyncGenerator[None, None]:
    """尝试获取项目操作锁，已被占用则 raise ValueError.

    互斥规则：
    - writing 与 fill/repair/summary 互斥
    - fill 与 writing/repair/summary 互斥
    - repair 与 writing/fill/summary 互斥
    - summary 与 fill/repair 互斥，但可与 writing 并行
    """
    async with _lock:
        existing = _project_ops.get(project_id)
        if existing:
            if operation == "summary" and existing == "writing":
                pass
            elif operation == "writing" and existing == "summary":
                pass
            else:
                raise ValueError(f"项目已有操作进行中（{existing}），无法启动 {operation}")
        _project_ops[project_id] = operation
    try:
        yield
    finally:
        async with _lock:
            if _project_ops.get(project_id) == operation:
                del _project_ops[project_id]


def release_op(project_id: str, operation: str) -> None:
    """显式释放操作锁（用于 SSE 流提前终止时清理）."""
    if _project_ops.get(project_id) == operation:
        del _project_ops[project_id]

def try_set_op(project_id: str, operation: str) -> bool:
    """尝试设置操作锁，成功返回 True，冲突返回 False.

    互斥规则：
    - writing 与 fill/repair/summary 互斥
    - fill 与 writing/repair/summary 互斥
    - repair 与 writing/fill/summary 互斥
    - summary 与 fill/repair 互斥，但可与 writing 并行
    """
    existing = _project_ops.get(project_id)
    if existing:
        if operation == "summary" and existing == "writing":
            _project_ops[project_id] = operation
            return True
        elif operation == "writing" and existing == "summary":
            _project_ops[project_id] = operation
            return True
        return False
    _project_ops[project_id] = operation
    return True