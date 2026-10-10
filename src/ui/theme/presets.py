"""预设主题常量定义."""
from __future__ import annotations

from src.ui.theme.models import PresetThemeInfo, ThemeId

PRESET_THEMES: list[PresetThemeInfo] = [
    PresetThemeInfo(
        theme_id=ThemeId.FOLLOW_SYSTEM.value,
        display_name="跟随系统",
        background="",
        foreground="",
        follow_system=True,
    ),
    PresetThemeInfo(
        theme_id=ThemeId.PARCHMENT.value,
        display_name="羊皮纸",
        background="#F5E6C8",
        foreground="#4A3F2B",
    ),
    PresetThemeInfo(
        theme_id=ThemeId.MIDNIGHT.value,
        display_name="深夜",
        background="#1F1F1F",
        foreground="#E0E0E0",
    ),
    PresetThemeInfo(
        theme_id=ThemeId.PLAIN_WHITE.value,
        display_name="素白",
        background="#FFFFFF",
        foreground="#222222",
    ),
    PresetThemeInfo(
        theme_id=ThemeId.MUNG_BEAN.value,
        display_name="豆沙绿",
        background="#C7EDCC",
        foreground="#2E4D2E",
    ),
    PresetThemeInfo(
        theme_id=ThemeId.MIST_BLUE.value,
        display_name="雾蓝",
        background="#D6E4F0",
        foreground="#1A3A5C",
    ),
    PresetThemeInfo(
        theme_id=ThemeId.LIGHT_PINK.value,
        display_name="淡粉",
        background="#F5D5DC",
        foreground="#5C2A3A",
    ),
    PresetThemeInfo(
        theme_id=ThemeId.CUSTOM.value,
        display_name="自定义",
        background="",
        foreground="",
    ),
]

FOLLOW_SYSTEM_LIGHT = ("#222222", "#F5F5F5")
FOLLOW_SYSTEM_DARK = ("#E0E0E0", "#1F1F1F")

PRESET_MAP: dict[str, PresetThemeInfo] = {t.theme_id: t for t in PRESET_THEMES}