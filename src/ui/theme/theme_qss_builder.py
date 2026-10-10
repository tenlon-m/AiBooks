"""QSS 样式表生成器，根据主题配色动态生成全局 QSS."""
from __future__ import annotations

from src.ui.theme.contrast_checker import ContrastChecker
from src.ui.theme.theme_palette import ThemePalette, SEMANTIC_VARIANTS


class ThemeQssBuilder:
    """动态生成全局 QSS 样式表（纯静态方法）."""

    @staticmethod
    def build_global_qss(
        foreground: str,
        background: str,
        accent: str = "",
    ) -> str:
        """生成完整全局 QSS."""
        if ContrastChecker.parse_hex(foreground) is None:
            raise ValueError(f"非法前景色: {foreground}")
        if ContrastChecker.parse_hex(background) is None:
            raise ValueError(f"非法背景色: {background}")

        pal = ThemePalette.derive(foreground, background)
        if not accent:
            accent = pal.accent
        btn_on_accent = pal.button_text(accent)

        parts: list[str] = []

        parts.append(f"""
            QMainWindow {{ background-color: {background}; }}
            QStackedWidget {{ background-color: {background}; }}
            QWidget {{ color: {foreground}; background-color: {background}; }}
        """)

        parts.append(f"""
            QToolBar {{
                background-color: {pal.surface};
                border-bottom: 1px solid {pal.border};
                padding: 4px;
                spacing: 2px;
            }}
            QToolBar QToolButton {{
                padding: 6px 12px;
                border-radius: 4px;
                color: {foreground};
            }}
            QToolBar QToolButton:hover {{
                background-color: {pal.hover};
            }}
            QToolBar QToolButton:pressed {{
                background-color: {pal.border};
            }}
        """)

        parts.append(f"""
            QStatusBar {{
                background-color: {pal.surface};
                border-top: 1px solid {pal.border};
                color: {foreground};
            }}
        """)

        parts.append(f"""
            QMenuBar {{
                background-color: {pal.surface};
                border-bottom: 1px solid {pal.border};
                color: {foreground};
            }}
            QMenuBar::item:selected {{
                background-color: {pal.hover};
            }}
            QMenu {{
                background-color: {pal.surface};
                border: 1px solid {pal.border};
                color: {foreground};
            }}
            QMenu::item:selected {{
                background-color: {accent};
                color: {btn_on_accent};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {pal.border};
            }}
        """)

        parts.append(f"""
            QTableWidget {{
                gridline-color: {pal.border};
                alternate-background-color: {pal.alternate};
                selection-background-color: {accent};
                selection-color: {btn_on_accent};
                border: 1px solid {pal.border};
                border-radius: 4px;
                background-color: {background};
                color: {foreground};
            }}
            QTableWidget::item {{
                padding: 4px 8px;
                border: none;
            }}
            QTableWidget::item:selected {{
                background-color: {accent};
                color: {btn_on_accent};
                font-weight: bold;
            }}
            QTableWidget::item:hover {{
                background-color: {pal.hover};
            }}
            QHeaderView::section {{
                background-color: {pal.surface};
                padding: 6px 8px;
                border: none;
                border-right: 1px solid {pal.border};
                border-bottom: 1px solid {pal.border};
                font-weight: bold;
                color: {foreground};
            }}
        """)

        parts.append(f"""
            QDialog {{
                background-color: {background};
                color: {foreground};
            }}
            QGroupBox {{
                border: 1px solid {pal.border};
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
                color: {foreground};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }}
        """)

        parts.append(f"""
            QPushButton {{
                background-color: {pal.surface};
                color: {foreground};
                border: 1px solid {pal.border};
                border-radius: 4px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{
                background-color: {pal.hover};
                border-color: {accent};
            }}
            QPushButton:pressed {{
                background-color: {pal.border};
            }}
            QPushButton:disabled {{
                color: {pal.disabled_text};
                background-color: {pal.alternate};
            }}
        """)

        parts.append(f"""
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
                background-color: {pal.surface};
                color: {foreground};
                border: 1px solid {pal.border};
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
            QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
                border-color: {accent};
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {pal.surface};
                color: {foreground};
                border: 1px solid {pal.border};
                selection-background-color: {accent};
                selection-color: {btn_on_accent};
            }}
        """)

        parts.append(f"""
            QLabel {{ color: {foreground}; }}
            QLabel[role="secondary"] {{ color: {pal.secondary_text}; }}
            QLabel[role="highlight"] {{
                background-color: {pal.surface};
                border: 1px solid {pal.border};
            }}
            QCheckBox, QRadioButton {{ color: {foreground}; }}
            QCheckBox::indicator, QRadioButton::indicator {{
                border: 1px solid {pal.border};
                width: 14px;
                height: 14px;
            }}
            QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
                background-color: {accent};
                border-color: {accent};
            }}
            QPushButton[unsaved="true"] {{
                border: 2px solid {pal.warning_bg};
            }}
        """)

        parts.append(f"""
            QTabWidget::pane {{
                border: 1px solid {pal.border};
                background-color: {background};
            }}
            QTabBar::tab {{
                background-color: {pal.surface};
                color: {foreground};
                padding: 6px 16px;
                border: 1px solid {pal.border};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
            QTabBar::tab:selected {{
                background-color: {background};
                color: {accent};
            }}
        """)

        parts.append(f"""
            QScrollBar:vertical {{
                background: {pal.surface};
                width: 10px;
                border: none;
            }}
            QScrollBar:horizontal {{
                background: {pal.surface};
                height: 10px;
                border: none;
            }}
            QScrollBar::handle {{
                background: {pal.border};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::handle:hover {{
                background: {pal.secondary_text};
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{
                border: none;
                height: 0px;
            }}
        """)

        for name, variants in SEMANTIC_VARIANTS.items():
            color = pal.semantic(name)
            text_color = pal.button_text(color)
            parts.append(
                f'QPushButton[variant="{name}"] {{'
                f" background-color: {color};"
                f" color: {text_color};"
                f" border: 1px solid {color};"
                f" border-radius: 4px;"
                f" padding: 6px 16px;"
                f" }}"
            )
            parts.append(
                f'QPushButton[variant="{name}"]:hover {{'
                f" background-color: {color};"
                f" opacity: 0.85;"
                f" }}"
            )

        return "\n".join(parts)

    @staticmethod
    def build_selection_border_qss(selected: bool) -> str:
        """生成主题按钮选中态边框样式."""
        if selected:
            return (
                "border: 3px solid #FF9800;"
                "border-radius: 6px;"
                "font-weight: bold;"
            )
        return "border: 1px solid transparent; border-radius: 6px;"


def apply_theme_variant(widget, variant: str) -> None:
    """设置控件语义变体属性并触发样式重算."""
    widget.setProperty("variant", variant)
    widget.style().unpolish(widget)
    widget.style().polish(widget)