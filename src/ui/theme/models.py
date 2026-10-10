"""主题数据模型与枚举定义."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ThemeId(str, Enum):
    """主题标识枚举，继承 str 以便 JSON/QSettings 序列化."""
    FOLLOW_SYSTEM = "follow_system"
    PARCHMENT = "parchment"
    MIDNIGHT = "midnight"
    PLAIN_WHITE = "plain_white"
    MUNG_BEAN = "mung_bean"
    MIST_BLUE = "mist_blue"
    LIGHT_PINK = "light_pink"
    CUSTOM = "custom"


class ContrastLevel(Enum):
    """WCAG 2.1 对比度等级."""
    AA_PASS = "aa_pass"
    AA_FAIL_LARGE_PASS = "aa_fail_large_pass"
    SEVERE_FAIL = "severe_fail"


@dataclass
class PresetThemeInfo:
    """预设主题元数据."""
    theme_id: str
    display_name: str
    background: str
    foreground: str
    follow_system: bool = False


@dataclass
class ThemeConfig:
    """主题配置（持久化对象）."""
    theme_id: str = ThemeId.FOLLOW_SYSTEM.value
    custom_foreground: str = "#222222"
    custom_background: str = "#F5F5F5"
    config_version: int = 2


@dataclass
class ResolvedColors:
    """解析后的有效配色."""
    foreground: str
    background: str
    source: str