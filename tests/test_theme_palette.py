"""ThemePalette 单元测试."""
from __future__ import annotations

import pytest

from src.ui.theme.theme_palette import ThemePalette, SEMANTIC_VARIANTS
from src.ui.theme.contrast_checker import ContrastChecker


class TestDerive:
    def test_light_theme(self):
        pal = ThemePalette.derive("#222222", "#FFFFFF")
        assert pal.is_light is True

    def test_parchment_is_light(self):
        pal = ThemePalette.derive("#4A3F2B", "#F5E6C8")
        assert pal.is_light is True

    def test_midnight_is_dark(self):
        pal = ThemePalette.derive("#E0E0E0", "#1F1F1F")
        assert pal.is_light is False


class TestDerivedColors:
    def test_light_surface_darker(self):
        pal = ThemePalette.derive("#222222", "#FFFFFF")
        bg_lum = ContrastChecker.relative_luminance("#FFFFFF")
        surf_lum = ContrastChecker.relative_luminance(pal.surface)
        assert surf_lum < bg_lum

    def test_dark_surface_lighter(self):
        pal = ThemePalette.derive("#E0E0E0", "#1F1F1F")
        bg_lum = ContrastChecker.relative_luminance("#1F1F1F")
        surf_lum = ContrastChecker.relative_luminance(pal.surface)
        assert surf_lum > bg_lum


class TestSemantic:
    def test_light_success(self):
        pal = ThemePalette.derive("#222222", "#FFFFFF")
        assert pal.semantic("success") == "#2E7D32"

    def test_dark_success(self):
        pal = ThemePalette.derive("#E0E0E0", "#1F1F1F")
        assert pal.semantic("success") == "#66BB6A"

    def test_all_variants_covered(self):
        for name in SEMANTIC_VARIANTS:
            pal_light = ThemePalette.derive("#222222", "#FFFFFF")
            pal_dark = ThemePalette.derive("#E0E0E0", "#1F1F1F")
            assert pal_light.semantic(name) == SEMANTIC_VARIANTS[name]["light"]
            assert pal_dark.semantic(name) == SEMANTIC_VARIANTS[name]["dark"]

    def test_unknown_name(self):
        pal = ThemePalette.derive("#222222", "#FFFFFF")
        assert pal.semantic("nonexistent") == pal.foreground


class TestButtonText:
    def test_light_button_dark_text(self):
        pal = ThemePalette.derive("#222222", "#FFFFFF")
        assert pal.button_text("#4CAF50") == "#222222"
        assert pal.button_text("#FF9800") == "#222222"

    def test_dark_button_white_text(self):
        pal = ThemePalette.derive("#222222", "#FFFFFF")
        assert pal.button_text("#9C27B0") == "#FFFFFF"
        assert pal.button_text("#1565C0") == "#FFFFFF"


class TestAccent:
    def test_light_accent(self):
        pal = ThemePalette.derive("#222222", "#FFFFFF")
        assert pal.accent == "#1565C0"

    def test_dark_accent(self):
        pal = ThemePalette.derive("#E0E0E0", "#1F1F1F")
        assert pal.accent == "#42A5F5"