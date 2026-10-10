"""ContrastChecker 单元测试."""
from __future__ import annotations

import pytest

from src.ui.theme.contrast_checker import ContrastChecker
from src.ui.theme.models import ContrastLevel


class TestParseHex:
    def test_valid_colors(self):
        assert ContrastChecker.parse_hex("#FFFFFF") == (255, 255, 255)
        assert ContrastChecker.parse_hex("#222222") == (0x22, 0x22, 0x22)
        assert ContrastChecker.parse_hex("#F5E6C8") == (0xF5, 0xE6, 0xC8)
        assert ContrastChecker.parse_hex("#000000") == (0, 0, 0)

    def test_invalid_colors(self):
        assert ContrastChecker.parse_hex("#ZZZZZZ") is None
        assert ContrastChecker.parse_hex("#123") is None
        assert ContrastChecker.parse_hex("FFFFFF") is None
        assert ContrastChecker.parse_hex("") is None
        assert ContrastChecker.parse_hex("#1234567") is None
        assert ContrastChecker.parse_hex(None) is None


class TestRelativeLuminance:
    def test_white(self):
        assert ContrastChecker.relative_luminance("#FFFFFF") == pytest.approx(1.0)

    def test_black(self):
        assert ContrastChecker.relative_luminance("#000000") == pytest.approx(0.0)

    def test_invalid(self):
        assert ContrastChecker.relative_luminance("invalid") == 0.0


class TestContrastRatio:
    def test_black_white(self):
        ratio = ContrastChecker.contrast_ratio("#FFFFFF", "#000000")
        assert ratio == pytest.approx(21.0, abs=0.01)

    def test_same_color(self):
        assert ContrastChecker.contrast_ratio("#888888", "#888888") == pytest.approx(1.0)

    def test_invalid(self):
        assert ContrastChecker.contrast_ratio("bad", "also_bad") == 0.0

    def test_parchment(self):
        ratio = ContrastChecker.contrast_ratio("#222222", "#F5E6C8")
        assert ratio > 8.0


class TestCheckLevel:
    def test_aa_pass(self):
        assert ContrastChecker.check_level("#FFFFFF", "#000000") == ContrastLevel.AA_PASS

    def test_large_pass(self):
        assert ContrastChecker.check_level("#888888", "#FFFFFF") == ContrastLevel.AA_FAIL_LARGE_PASS

    def test_severe_fail(self):
        assert ContrastChecker.check_level("#777777", "#888888") == ContrastLevel.SEVERE_FAIL


class TestSemanticWhiteText:
    """验证 design.md §2.4.4.3 中语义色白字对比度数据."""

    def test_success_white_text(self):
        ratio = ContrastChecker.contrast_ratio("#FFFFFF", "#4CAF50")
        assert ratio == pytest.approx(2.78, abs=0.05)

    def test_warning_white_text(self):
        ratio = ContrastChecker.contrast_ratio("#FFFFFF", "#FF9800")
        assert ratio == pytest.approx(2.16, abs=0.05)