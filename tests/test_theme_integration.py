"""主题切换端到端集成测试."""
from __future__ import annotations

import pytest

from src.ui.theme.theme_manager import ThemeManager
from src.ui.theme.theme_qss_builder import ThemeQssBuilder
from src.ui.theme.models import ThemeId


class TestThemeIntegration:
    def test_startup_default(self, qapp):
        from PySide6.QtCore import QSettings
        settings = QSettings("AiBooks", "GlobalTheme")
        settings.clear()
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        assert mgr.current_theme().theme_id == ThemeId.FOLLOW_SYSTEM.value

    def test_full_switch_flow(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        received = []
        mgr.theme_changed.connect(lambda d: received.append(d))

        mgr.set_theme("parchment")
        assert len(received) >= 1
        data = received[-1]
        assert data["theme_id"] == "parchment"
        assert data["foreground"] == "#4A3F2B"
        assert data["background"] == "#F5E6C8"

        qss = ThemeQssBuilder.build_global_qss(data["foreground"], data["background"])
        assert "#F5E6C8" in qss

    def test_custom_theme_flow(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        received = []
        mgr.theme_changed.connect(lambda d: received.append(d))

        mgr.set_custom_colors("#333333", "#FFEEDD")
        assert len(received) >= 1
        assert received[-1]["theme_id"] == ThemeId.CUSTOM.value
        assert received[-1]["foreground"] == "#333333"

    def test_reset_flow(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        mgr.set_custom_colors("#333333", "#FFEEDD")
        received = []
        mgr.theme_changed.connect(lambda d: received.append(d))
        mgr.reset_to_default()
        assert len(received) >= 1
        assert received[-1]["theme_id"] == ThemeId.FOLLOW_SYSTEM.value

    def test_all_preset_themes_switchable(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        for info in mgr.preset_themes():
            if info.theme_id == ThemeId.FOLLOW_SYSTEM.value:
                continue
            assert mgr.set_theme(info.theme_id) is True
            resolved = mgr.resolve_colors(info.theme_id)
            assert resolved.foreground != ""
            assert resolved.background != ""

    def test_qss_generated_for_all_themes(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        for info in mgr.preset_themes():
            if info.theme_id == ThemeId.FOLLOW_SYSTEM.value or info.theme_id == ThemeId.CUSTOM.value:
                continue
            resolved = mgr.resolve_colors(info.theme_id)
            qss = ThemeQssBuilder.build_global_qss(resolved.foreground, resolved.background)
            assert len(qss) > 500
            assert info.background in qss