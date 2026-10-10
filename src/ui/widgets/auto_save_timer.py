"""定时自动保存定时器组件 - 按配置间隔周期触发自动保存信号."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal


class AutoSaveTimer(QObject):
    """封装 QTimer 与配置状态，按间隔分钟周期 emit timeout 信号."""

    timeout = Signal()

    def __init__(self, enabled: bool = True, interval_minutes: int = 5) -> None:
        super().__init__()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timeout)
        self._enabled: bool = enabled
        self._interval_minutes: int = interval_minutes

    def start(self) -> None:
        if self._enabled and 1 <= self._interval_minutes <= 30:
            self._timer.start(self._interval_minutes * 60 * 1000)

    def stop(self) -> None:
        self._timer.stop()

    def reconfigure(self, enabled: bool, interval_minutes: int) -> None:
        self._enabled = enabled
        self._interval_minutes = interval_minutes
        self.stop()
        self.start()

    def is_active(self) -> bool:
        return self._timer.isActive()

    def _on_timeout(self) -> None:
        try:
            self.timeout.emit()
        except Exception:
            self._timer.start(self._interval_minutes * 60 * 1000)