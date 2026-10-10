"""ThemeQssBuilder 单元测试."""
from __future__ import annotations

import pytest

from src.ui.theme.theme_qss_builder import ThemeQssBuilder
from src.ui.theme.theme_palette import SEMANTIC_VARIANTS


class TestBuildGlobalQss:
    def test_generates_nonempty_string(self):
        qss = ThemeQssBuilder.build_global_qss("#222222", "#FFFFFF")
        assert isinstance(qss, str)
        assert len(qss) > 100

    def test_different_colors_different_qss(self):
        qss1 = ThemeQssBuilder.build_global_qss("#222222", "#FFFFFF")
        qss2 = ThemeQssBuilder.build_global_qss("#E0E0E0", "#1F1F1F")
        assert qss1 != qss2

    def test_contains_control_types(self):
        qss = ThemeQssBuilder.build_global_qss("#222222", "#FFFFFF")
        for control in ["QMainWindow", "QToolBar", "QStatusBar", "QMenuBar",
                        "QMenu", "QTableWidget", "QHeaderView", "QPushButton",
                        "QLineEdit", "QComboBox", "QLabel", "QScrollBar",
                        "QTabWidget", "QCheckBox", "QRadioButton", "QDialog"]:
            assert control in qss, f"QSS 缺少控件类型: {control}"

    def test_contains_semantic_variants(self):
        qss = ThemeQssBuilder.build_global_qss("#222222", "#FFFFFF")
        for name in SEMANTIC_VARIANTS:
            assert f'QPushButton[variant="{name}"]' in qss, f"QSS 缺少语义变体: {name}"

    def test_invalid_color_raises(self):
        with pytest.raises(ValueError):
            ThemeQssBuilder.build_global_qss("invalid", "#FFFFFF")
        with pytest.raises(ValueError):
            ThemeQssBuilder.build_global_qss("#222222", "bad")


class TestBuildSelectionBorderQss:
    def test_selected(self):
        qss = ThemeQssBuilder.build_selection_border_qss(True)
        assert "#FF9800" in qss
        assert "3px" in qss

    def test_not_selected(self):
        qss = ThemeQssBuilder.build_selection_border_qss(False)
        assert "#FF9800" not in qss
        assert "transparent" in qss