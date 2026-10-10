"""人物生成进度计时器组件 - 状态栏左下角显示"[操作类型]中... MM:SS"进度提示."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QStatusBar


class CharacterProgressTimer(QObject):
    """封装 QTimer 与计时状态，驱动状态栏进度提示."""

    def __init__(self, status_bar: QStatusBar) -> None:
        super().__init__()
        self._status_bar = status_bar
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)
        self._elapsed_seconds: int = 0
        self._operation_label: str = ""

    def start(self, operation_label: str) -> None:
        self._operation_label = operation_label
        self._elapsed_seconds = 0
        self._timer.start()
        self._show_progress()

    def stop(self) -> None:
        self._timer.stop()

    def _on_tick(self) -> None:
        try:
            self._elapsed_seconds += 1
            self._show_progress()
        except Exception:
            self._timer.start()

    def _show_progress(self) -> None:
        self._status_bar.showMessage(
            f"{self._operation_label}中... {self._format_mmss(self._elapsed_seconds)}"
        )

    @staticmethod
    def _format_mmss(seconds: int) -> str:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"

    def show_complete(self, added_count: int, skipped_count: int = 0) -> None:
        self.stop()
        if skipped_count > 0:
            self._status_bar.showMessage(
                f"完成，新增{added_count}个人物，{skipped_count}人已存在跳过", 3000
            )
        else:
            self._status_bar.showMessage(f"完成，新增{added_count}个人物", 3000)

    def show_error(self, message: str) -> None:
        self.stop()
        self._status_bar.clearMessage()