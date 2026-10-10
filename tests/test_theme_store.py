"""ThemeSettingsStore 单元测试."""
from __future__ import annotations

import pytest

from src.ui.theme.theme_settings_store import ThemeSettingsStore
from src.ui.theme.models import ThemeConfig, ThemeId


class TestThemeSettingsStore:
    def test_save_load_roundtrip(self, qapp):
        store = ThemeSettingsStore()
        config = ThemeConfig(theme_id="parchment", custom_foreground="#4A3F2B", custom_background="#F5E6C8")
        assert store.save(config) is True
        loaded = store.load()
        assert loaded.theme_id == "parchment"
        assert loaded.custom_foreground == "#4A3F2B"
        assert loaded.custom_background == "#F5E6C8"

    def test_default_config(self, qapp):
        store = ThemeSettingsStore()
        store.clear_custom()
        store.save(ThemeConfig())
        loaded = store.load()
        assert loaded.theme_id == ThemeId.FOLLOW_SYSTEM.value

    def test_clear_custom(self, qapp):
        store = ThemeSettingsStore()
        store.save(ThemeConfig(
            theme_id="custom",
            custom_foreground="#333333",
            custom_background="#FFEEDD",
        ))
        assert store.clear_custom() is True

    def test_legacy_follow_app_migration(self, qapp):
        from PySide6.QtCore import QSettings
        settings = QSettings("AiBooks", "GlobalTheme")
        settings.setValue("themeId", "follow_app")
        settings.setValue("configVersion", 1)
        settings.sync()

        store = ThemeSettingsStore()
        loaded = store.load()
        assert loaded.theme_id == ThemeId.FOLLOW_SYSTEM.value