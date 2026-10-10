"""主题配置持久化（QSettings）."""
from __future__ import annotations

from PySide6.QtCore import QSettings

from src.ui.theme.models import ThemeConfig, ThemeId
from src.utils.logger import get_logger

logger = get_logger()

THEME_KEY = "themeId"
CUSTOM_FG_KEY = "customForeground"
CUSTOM_BG_KEY = "customBackground"
VERSION_KEY = "configVersion"
LEGACY_FOLLOW_APP_KEY = "followApp"
LEGACY_BG_IMAGE_KEY = "backgroundImage"


class ThemeSettingsStore:
    """主题配置读写，基于 QSettings("AiBooks", "GlobalTheme")."""

    def __init__(self) -> None:
        self._settings = QSettings("AiBooks", "GlobalTheme")

    def load(self) -> ThemeConfig:
        """读取主题配置，含向后兼容迁移."""
        try:
            theme_id = self._settings.value(THEME_KEY, ThemeId.FOLLOW_SYSTEM.value)
            if theme_id == "follow_app":
                theme_id = ThemeId.FOLLOW_SYSTEM.value
                logger.info("主题配置迁移: follow_app → follow_system")

            custom_fg = self._settings.value(CUSTOM_FG_KEY, "#222222")
            custom_bg = self._settings.value(CUSTOM_BG_KEY, "#F5F5F5")
            version = int(self._settings.value(VERSION_KEY, 2))

            if self._settings.contains(LEGACY_BG_IMAGE_KEY):
                logger.info("检测到旧版背景图片配置，已忽略")

            return ThemeConfig(
                theme_id=theme_id,
                custom_foreground=custom_fg,
                custom_background=custom_bg,
                config_version=version,
            )
        except Exception as e:
            logger.warning(f"读取主题配置失败，回退默认: {e}")
            return ThemeConfig()

    def save(self, config: ThemeConfig) -> bool:
        """写入主题配置."""
        try:
            self._settings.setValue(THEME_KEY, config.theme_id)
            self._settings.setValue(CUSTOM_FG_KEY, config.custom_foreground)
            self._settings.setValue(CUSTOM_BG_KEY, config.custom_background)
            self._settings.setValue(VERSION_KEY, config.config_version)
            self._settings.sync()
            if self._settings.status() != QSettings.Status.NoError:
                logger.error("主题配置写入失败: QSettings 状态异常")
                return False
            return True
        except Exception as e:
            logger.error(f"主题配置写入异常: {e}")
            return False

    def clear_custom(self) -> bool:
        """清除自定义颜色键."""
        try:
            self._settings.remove(CUSTOM_FG_KEY)
            self._settings.remove(CUSTOM_BG_KEY)
            self._settings.sync()
            return self._settings.status() == QSettings.Status.NoError
        except Exception as e:
            logger.error(f"清除自定义颜色失败: {e}")
            return False

    def save_failed(self) -> bool:
        """检查 QSettings 是否处于错误状态."""
        return self._settings.status() != QSettings.Status.NoError