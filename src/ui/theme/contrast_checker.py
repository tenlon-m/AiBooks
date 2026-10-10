"""WCAG 2.1 对比度计算工具."""
from __future__ import annotations

from src.ui.theme.models import ContrastLevel


class ContrastChecker:
    """对比度计算与校验（纯静态方法）."""

    @staticmethod
    def parse_hex(hex_color: str) -> tuple[int, int, int] | None:
        """解析 #RRGGBB 为 RGB 三元组，非法返回 None."""
        if not isinstance(hex_color, str):
            return None
        s = hex_color.strip()
        if not s.startswith("#") or len(s) != 7:
            return None
        try:
            r = int(s[1:3], 16)
            g = int(s[3:5], 16)
            b = int(s[5:7], 16)
        except ValueError:
            return None
        return (r, g, b)

    @staticmethod
    def relative_luminance(hex_color: str) -> float:
        """按 WCAG 2.1 公式计算相对亮度 [0.0, 1.0]."""
        rgb = ContrastChecker.parse_hex(hex_color)
        if rgb is None:
            return 0.0

        def _linearize(c: float) -> float:
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        r = _linearize(rgb[0] / 255.0)
        g = _linearize(rgb[1] / 255.0)
        b = _linearize(rgb[2] / 255.0)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    @staticmethod
    def contrast_ratio(fg: str, bg: str) -> float:
        """计算对比度比值 [1.0, 21.0]，非法颜色返回 0.0."""
        l_fg = ContrastChecker.relative_luminance(fg)
        l_bg = ContrastChecker.relative_luminance(bg)
        if l_fg == 0.0 and l_bg == 0.0:
            return 0.0
        l1 = max(l_fg, l_bg)
        l2 = min(l_fg, l_bg)
        return (l1 + 0.05) / (l2 + 0.05)

    @staticmethod
    def check_level(fg: str, bg: str) -> ContrastLevel:
        """判定对比度等级."""
        ratio = ContrastChecker.contrast_ratio(fg, bg)
        if ratio >= 4.5:
            return ContrastLevel.AA_PASS
        if ratio >= 3.0:
            return ContrastLevel.AA_FAIL_LARGE_PASS
        return ContrastLevel.SEVERE_FAIL