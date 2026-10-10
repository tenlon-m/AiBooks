"""主题调色板：派生层 + 语义色变体 + 按钮文字色."""
from __future__ import annotations

from src.ui.theme.contrast_checker import ContrastChecker


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    rgb = ContrastChecker.parse_hex(hex_color)
    return rgb if rgb is not None else (0, 0, 0)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    r = max(0, min(255, round(r)))
    g = max(0, min(255, round(g)))
    b = max(0, min(255, round(b)))
    return f"#{r:02X}{g:02X}{b:02X}"


def _darken(hex_color: str, factor: float) -> str:
    """加深颜色，factor 为降低比例 (0.0~1.0)."""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex(r * (1 - factor), g * (1 - factor), b * (1 - factor))


def _lighten(hex_color: str, factor: float) -> str:
    """提亮颜色，factor 为增加比例 (0.0~1.0)."""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex(
        r + (255 - r) * factor, g + (255 - g) * factor, b + (255 - b) * factor
    )


def _blend(fg: str, bg: str, alpha: float) -> str:
    """前景色以 alpha 不透明度叠加到背景色."""
    fr, fg_, fb = _hex_to_rgb(fg)
    br, bg_, bb = _hex_to_rgb(bg)
    return _rgb_to_hex(
        fr * alpha + br * (1 - alpha),
        fg_ * alpha + bg_ * (1 - alpha),
        fb * alpha + bb * (1 - alpha),
    )


SEMANTIC_VARIANTS: dict[str, dict[str, str]] = {
    "success":       {"light": "#2E7D32", "dark": "#66BB6A"},
    "warning":       {"light": "#E65100", "dark": "#FFB74D"},
    "danger":        {"light": "#C62828", "dark": "#EF5350"},
    "info":          {"light": "#1565C0", "dark": "#42A5F5"},
    "purple":        {"light": "#6A1B9A", "dark": "#AB47BC"},
    "cyan":          {"light": "#00838F", "dark": "#4DD0E1"},
    "deep_orange":   {"light": "#D84315", "dark": "#FF7043"},
    "selected_blue": {"light": "#1565C0", "dark": "#42A5F5"},
    "deep_purple":   {"light": "#4527A0", "dark": "#7E57C2"},
    "pink":          {"light": "#AD1457", "dark": "#EC407A"},
    "blue_grey":     {"light": "#455A64", "dark": "#78909C"},
    "teal":          {"light": "#00695C", "dark": "#4DB6AC"},
}


class ThemePalette:
    """主题调色板，从基础前景/背景色派生完整配色体系."""

    def __init__(
        self,
        foreground: str,
        background: str,
        is_light: bool,
    ) -> None:
        self.foreground = foreground
        self.background = background
        self.is_light = is_light

        if is_light:
            self.surface = _darken(background, 0.03)
            self.border = _darken(background, 0.12)
            self.hover = _darken(background, 0.05)
            self.alternate = _darken(background, 0.02)
            self.secondary_text = _blend(foreground, background, 0.75)
            self.disabled_text = _blend(foreground, background, 0.45)
            self.accent = "#1565C0"
        else:
            self.surface = _lighten(background, 0.04)
            self.border = _lighten(background, 0.15)
            self.hover = _lighten(background, 0.08)
            self.alternate = _lighten(background, 0.03)
            self.secondary_text = _blend(foreground, background, 0.70)
            self.disabled_text = _blend(foreground, background, 0.40)
            self.accent = "#42A5F5"

        self.success_bg = self.semantic("success")
        self.warning_bg = self.semantic("warning")
        self.error_text = self.semantic("danger")
        self.info_bg = self.semantic("info")

    @classmethod
    def derive(cls, foreground: str, background: str) -> "ThemePalette":
        """根据前景/背景色创建调色板，自动判定明暗."""
        lum = ContrastChecker.relative_luminance(background)
        is_light = lum > 0.179
        return cls(foreground, background, is_light)

    def semantic(self, name: str) -> str:
        """返回语义色变体（浅色主题取加深变体，深色主题取提亮变体）."""
        variant = SEMANTIC_VARIANTS.get(name)
        if variant is None:
            return self.foreground
        return variant["light"] if self.is_light else variant["dark"]

    def button_text(self, btn_bg: str) -> str:
        """按按钮背景亮度自动选择文字色."""
        lum = ContrastChecker.relative_luminance(btn_bg)
        return "#222222" if lum > 0.179 else "#FFFFFF"


def theme_color(role: str) -> str:
    """工具函数：从当前 ThemeManager 调色板取指定角色色值."""
    from src.ui.theme.theme_manager import ThemeManager

    mgr = ThemeManager.instance()
    resolved = mgr.resolve_colors(mgr.current_theme().theme_id)
    pal = ThemePalette.derive(resolved.foreground, resolved.background)
    return getattr(pal, role, pal.foreground)