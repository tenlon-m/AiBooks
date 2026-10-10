"""快捷键管理器 - 从后端加载配置并注册 QShortcut 到目标 widget."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.utils.logger import get_logger

_MAX_RETRIES = 3
_RETRY_DELAY_MS = 2000


class ShortcutManager(QObject):
    """快捷键管理器：异步加载配置后注册 QShortcut.

    用法:
        manager = ShortcutManager(parent_widget)
        manager.register("save", on_save)
        manager.register("find", on_find)
        manager.load()  # 异步加载并应用
    """

    shortcuts_loaded = Signal(list)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent = parent
        self._handlers: dict[str, Callable[[], None]] = {}
        self._shortcuts: dict[str, QShortcut] = {}
        self._configs: dict[str, dict] = {}
        self._workers: list[ApiWorker] = []
        self._retry_count: int = 0
        self._logger = get_logger()

    def _add_worker(self, worker) -> None:
        """注册 ApiWorker 并在完成后自动清理."""
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))

    def _cleanup_worker(self, worker) -> None:
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()


    def register(self, action_name: str, handler: Callable[[], None]) -> None:
        """登记动作处理器；load() 完成后才会真正绑定 QShortcut."""
        self._handlers[action_name] = handler

    def load(self) -> None:
        """异步从后端加载快捷键配置并注册."""
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/shortcuts")
        worker.result.connect(self._on_loaded)
        worker.error.connect(self._on_load_error)
        self._add_worker(worker)
        worker.start()

    def _on_loaded(self, shortcuts: list) -> None:
        self._retry_count = 0
        self._apply_configs(shortcuts)
        self.shortcuts_loaded.emit(shortcuts)

    def _on_load_error(self, msg: str) -> None:
        self._retry_count += 1
        if self._retry_count <= _MAX_RETRIES:
            self._logger.info(f"快捷键加载第{self._retry_count}次重试（后端可能未就绪）")
            QTimer.singleShot(_RETRY_DELAY_MS, self.load)
            return
        self._logger.warning(f"加载快捷键配置失败（使用默认绑定）: {msg}")
        self._apply_configs(self._default_configs())

    @staticmethod
    def _default_configs() -> list[dict]:
        return [
            {"action_name": "save", "key_sequence": "Ctrl+S", "enabled": True},
            {"action_name": "find", "key_sequence": "Ctrl+F", "enabled": True},
            {"action_name": "replace", "key_sequence": "Ctrl+H", "enabled": True},
            {"action_name": "new_chapter", "key_sequence": "Ctrl+N", "enabled": True},
            {"action_name": "ai_chat", "key_sequence": "Ctrl+Shift+D", "enabled": True},
            {"action_name": "continue_writing", "key_sequence": "Ctrl+Shift+R", "enabled": True},
        ]

    def _apply_configs(self, shortcuts: list) -> None:
        for s in shortcuts:
            action = s.get("action_name", "")
            if action not in self._handlers:
                continue
            if not s.get("enabled", True):
                continue
            key_seq = s.get("key_sequence", "")
            if not key_seq:
                continue
            old = self._shortcuts.pop(action, None)
            if old is not None:
                old.setEnabled(False)
                old.deleteLater()
            sc = QShortcut(QKeySequence(key_seq), self._parent)
            sc.activated.connect(self._handlers[action])
            self._shortcuts[action] = sc
            self._configs[action] = s

    def get_config(self, action_name: str) -> dict | None:
        return self._configs.get(action_name)

    def reload(self) -> None:
        """重新加载配置（用于配置变更后刷新）."""
        self.load()