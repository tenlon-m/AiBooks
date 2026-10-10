"""系统明暗模式检测（Windows 注册表）."""
from __future__ import annotations

import platform

from PySide6.QtCore import QObject, QTimer, Signal

from src.utils.logger import get_logger

logger = get_logger()

_IS_WINDOWS = platform.system() == "Windows"


class SystemThemeDetector(QObject):
    """检测操作系统明暗模式，QTimer 轮询注册表."""

    system_theme_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._is_light: bool = True
        self._timer: QTimer | None = None

    def is_light_mode(self) -> bool:
        """返回 True=浅色模式，False=深色模式."""
        if not _IS_WINDOWS:
            return True
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return bool(value)
        except Exception as e:
            logger.warning(f"读取系统明暗模式失败，回退浅色: {e}")
            return True

    def start_watching(self) -> None:
        """启动定时轮询（2 秒间隔）."""
        if self._timer is not None:
            return
        self._is_light = self.is_light_mode()
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def stop_watching(self) -> None:
        """停止轮询."""
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

    def _poll(self) -> None:
        """轮询检测系统明暗变化."""
        current = self.is_light_mode()
        if current != self._is_light:
            self._is_light = current
            self.system_theme_changed.emit(current)