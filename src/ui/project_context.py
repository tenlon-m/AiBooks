"""项目上下文 - 全局共享当前项目 ID 和信息，基于 Qt 信号广播项目切换."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal


class ProjectContext(QObject):
    """全局项目上下文，供各页面共享当前项目信息.

    继承 QObject 以支持 Qt 信号广播：set_project 时自动发射 project_changed 信号，
    所有连接该信号的页面会收到通知并加载新项目数据。
    clear 不发射信号（用于删除项目后，由调用方手动调用 clear_all_pages）。
    """

    project_changed = Signal(str, dict)

    def __init__(self) -> None:
        super().__init__()
        self._project_id: str | None = None
        self._project_info: dict[str, Any] = {}

    @property
    def project_id(self) -> str | None:
        return self._project_id

    @property
    def project_info(self) -> dict[str, Any]:
        return self._project_info

    def set_project(self, project_id: str, info: dict[str, Any] | None = None) -> None:
        self._project_id = project_id
        if info is not None:
            self._project_info = info
        else:
            self._project_info = {}
        self.project_changed.emit(project_id, self._project_info)

    def clear(self) -> None:
        self._project_id = None
        self._project_info = {}

    def has_project(self) -> bool:
        return self._project_id is not None


_context: ProjectContext | None = None


def get_project_context() -> ProjectContext:
    global _context
    if _context is None:
        _context = ProjectContext()
    return _context
