"""配置单例加载，支持热重载."""
from __future__ import annotations

from src.config.app_config import AppConfig

_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = AppConfig()
        _config.ensure_dirs()
    return _config


def reload_config() -> AppConfig:
    global _config
    _config = AppConfig()
    _config.ensure_dirs()
    return _config