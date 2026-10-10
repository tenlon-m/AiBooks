"""主题管理器单例，协调持久化、系统检测、信号发射."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from src.ui.theme.contrast_checker import ContrastChecker
from src.ui.theme.models import ResolvedColors, ThemeConfig, ThemeId
from src.ui.theme.presets import (
    FOLLOW_SYSTEM_DARK,
    FOLLOW_SYSTEM_LIGHT,
    PRESET_MAP,
)
from src.ui.theme.system_theme_detector import SystemThemeDetector
from src.ui.theme.theme_settings_store import ThemeSettingsStore
from src.utils.logger import get_logger

logger = get_logger()

_VALID_IDS = {t.value for t in ThemeId}


class ThemeManager(QObject):
    """全局主题管理器（单例）."""

    theme_changed = Signal(dict)

    _instance: "ThemeManager | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._store = ThemeSettingsStore()
        self._config = self._store.load()
        self._detector = SystemThemeDetector(self)
        self._detector.system_theme_changed.connect(self._on_system_theme_changed)
        self._detector.start_watching()
        logger.info(
            f"ThemeManager 初始化: theme={self._config.theme_id}"
        )

    @classmethod
    def instance(cls) -> "ThemeManager":
        """获取单例."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（仅供测试使用）."""
        if cls._instance is not None:
            cls._instance._detector.stop_watching()
            cls._instance = None

    def current_theme(self) -> ThemeConfig:
        """返回当前主题配置."""
        return self._config

    def preset_themes(self):
        """返回预设主题列表."""
        from src.ui.theme.presets import PRESET_THEMES
        return PRESET_THEMES

    def resolve_colors(self, theme_id: str) -> ResolvedColors:
        """将主题标识解析为有效配色."""
        if theme_id == ThemeId.FOLLOW_SYSTEM.value:
            is_light = self._detector.is_light_mode()
            fg, bg = FOLLOW_SYSTEM_LIGHT if is_light else FOLLOW_SYSTEM_DARK
            return ResolvedColors(foreground=fg, background=bg, source="system")

        if theme_id == ThemeId.CUSTOM.value:
            return ResolvedColors(
                foreground=self._config.custom_foreground,
                background=self._config.custom_background,
                source="custom",
            )

        info = PRESET_MAP.get(theme_id)
        if info is not None:
            return ResolvedColors(
                foreground=info.foreground,
                background=info.background,
                source="preset",
            )

        logger.warning(f"未知主题标识: {theme_id}，回退跟随系统")
        is_light = self._detector.is_light_mode()
        fg, bg = FOLLOW_SYSTEM_LIGHT if is_light else FOLLOW_SYSTEM_DARK
        return ResolvedColors(foreground=fg, background=bg, source="system")

    def set_theme(self, theme_id: str) -> bool:
        """切换主题."""
        if theme_id not in _VALID_IDS:
            logger.warning(f"非法主题标识: {theme_id}")
            return False
        self._config.theme_id = theme_id
        self._store.save(self._config)
        self._emit_changed()
        logger.info(f"主题切换: {theme_id}")
        return True

    def set_custom_colors(self, foreground: str, background: str) -> bool:
        """设置自定义颜色并切换到 custom 主题."""
        if ContrastChecker.parse_hex(foreground) is None:
            logger.warning(f"非法前景色: {foreground}")
            return False
        if ContrastChecker.parse_hex(background) is None:
            logger.warning(f"非法背景色: {background}")
            return False
        self._config.custom_foreground = foreground
        self._config.custom_background = background
        self._config.theme_id = ThemeId.CUSTOM.value
        self._store.save(self._config)
        self._emit_changed()
        logger.info(f"自定义颜色设置: fg={foreground}, bg={background}")
        return True

    def reset_to_default(self) -> bool:
        """恢复默认主题（跟随系统）."""
        self._config = ThemeConfig()
        self._store.clear_custom()
        self._store.save(self._config)
        self._emit_changed()
        logger.info("主题已恢复默认")
        return True

    def _on_system_theme_changed(self, is_light: bool) -> None:
        """系统明暗变化时，若当前为跟随系统则重新发射信号."""
        if self._config.theme_id == ThemeId.FOLLOW_SYSTEM.value:
            logger.info(f"系统明暗变化: is_light={is_light}")
            self._emit_changed()

    def _emit_changed(self) -> None:
        """发射主题变更信号."""
        resolved = self.resolve_colors(self._config.theme_id)
        self.theme_changed.emit({
            "theme_id": self._config.theme_id,
            "foreground": resolved.foreground,
            "background": resolved.background,
            "source": resolved.source,
        })