"""ThemeManager 单元测试."""
from __future__ import annotations

import pytest

from src.ui.theme.theme_manager import ThemeManager
from src.ui.theme.models import ThemeId


class TestThemeManager:
    def test_singleton(self, qapp):
        ThemeManager.reset_instance()
        m1 = ThemeManager.instance()
        m2 = ThemeManager.instance()
        assert m1 is m2

    def test_set_theme_valid(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        assert mgr.set_theme("parchment") is True
        assert mgr.current_theme().theme_id == "parchment"

    def test_set_theme_invalid(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        original = mgr.current_theme().theme_id
        assert mgr.set_theme("nonexistent") is False
        assert mgr.current_theme().theme_id == original

    def test_set_custom_colors_valid(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        assert mgr.set_custom_colors("#333333", "#FFEEDD") is True
        assert mgr.current_theme().theme_id == ThemeId.CUSTOM.value
        assert mgr.current_theme().custom_foreground == "#333333"

    def test_set_custom_colors_invalid(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        assert mgr.set_custom_colors("bad", "#FFEEDD") is False
        assert mgr.set_custom_colors("#333333", "bad") is False

    def test_reset_to_default(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        mgr.set_theme("parchment")
        mgr.reset_to_default()
        assert mgr.current_theme().theme_id == ThemeId.FOLLOW_SYSTEM.value

    def test_resolve_colors_preset(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        resolved = mgr.resolve_colors("parchment")
        assert resolved.foreground == "#4A3F2B"
        assert resolved.background == "#F5E6C8"
        assert resolved.source == "preset"

    def test_resolve_colors_custom(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        mgr.set_custom_colors("#ABCDEF", "#123456")
        resolved = mgr.resolve_colors(ThemeId.CUSTOM.value)
        assert resolved.foreground == "#ABCDEF"
        assert resolved.background == "#123456"
        assert resolved.source == "custom"

    def test_resolve_colors_follow_system(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        resolved = mgr.resolve_colors(ThemeId.FOLLOW_SYSTEM.value)
        assert resolved.source == "system"

    def test_theme_changed_signal(self, qapp):
        ThemeManager.reset_instance()
        mgr = ThemeManager.instance()
        received = []
        mgr.theme_changed.connect(lambda d: received.append(d))
        mgr.set_theme("midnight")
        assert len(received) >= 1
        assert received[-1]["theme_id"] == "midnight"