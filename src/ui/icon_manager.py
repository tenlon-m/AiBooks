"""图标管理与加载.

提供资源路径解析与应用图标加载功能，支持开发模式与 PyInstaller 打包模式。
图标加载失败时自动降级为默认图标，不中断应用启动。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.utils.logger import get_logger

logger = get_logger()


def resource_path(relative_path: str) -> Path:
    """解析资源文件的绝对路径.

    开发模式下基于当前工作目录拼接；PyInstaller 打包模式下基于 sys._MEIPASS 拼接。
    纯路径拼接，不校验文件存在性，不抛异常。

    Args:
        relative_path: 相对路径字符串，如 "src/resources/app.ico"

    Returns:
        解析后的绝对 Path 对象
    """
    base = getattr(sys, "_MEIPASS", None)
    if base is not None:
        return Path(base) / relative_path
    return Path(__file__).resolve().parents[2] / relative_path


class IconManager:
    """应用图标加载器，全部方法为静态方法."""

    ICON_RELATIVE_PATH = "src/resources/app.ico"

    @staticmethod
    def _load_icon() -> QIcon | None:
        """加载图标文件，返回 QIcon 或 None（加载失败时）."""
        path = resource_path(IconManager.ICON_RELATIVE_PATH)
        if not path.exists():
            logger.warning(f"图标文件不存在: {path}")
            return None
        icon = QIcon(str(path))
        if icon.isNull():
            logger.error(f"图标文件损坏或格式无效: {path}")
            return None
        return icon

    @staticmethod
    def load_and_set_icon(app: QApplication) -> bool:
        """加载图标并设置到 QApplication，返回是否成功.

        加载失败时自动降级，不抛异常，不中断应用启动。
        """
        start = time.perf_counter()
        try:
            icon = IconManager._load_icon()
            if icon is None:
                return False
            app.setWindowIcon(icon)
            elapsed_ms = (time.perf_counter() - start) * 1000
            if elapsed_ms > 200:
                logger.warning(f"图标加载耗时 {elapsed_ms:.1f}ms，超过 200ms 阈值")
            logger.info(
                f"应用图标加载成功: {resource_path(IconManager.ICON_RELATIVE_PATH)} ({elapsed_ms:.1f}ms)"
            )
            return True
        except Exception as e:
            logger.error(f"图标加载异常: {e}", exc_info=True)
            return False