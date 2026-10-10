"""阅读模式控制器 - 字体/行距/背景色调整 + 隐藏编辑工具栏."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.config.settings import get_config
from src.ui.widgets.reading_mode_view import ReadingModeView


class ReadingModeController(QWidget):
    """阅读模式控制器：字体大小/行距/背景色调整 + ReadingModeView.

    style_changed(dict) 信号在样式参数变化时触发，
    用于联动隐藏编辑工具栏等外部行为。
    exit_reading() 信号在用户点击"退出阅读"时触发。
    """

    style_changed = Signal(dict)
    exit_reading = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("字体："))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(12, 36)
        cfg = get_config()
        self.font_size_spin.setValue(cfg.reading_mode_default_font_size)
        self.font_size_spin.valueChanged.connect(self._on_font_changed)
        ctrl_layout.addWidget(self.font_size_spin)

        ctrl_layout.addWidget(QLabel("行距："))
        self.line_spacing_spin = QDoubleSpinBox()
        self.line_spacing_spin.setRange(1.0, 3.0)
        self.line_spacing_spin.setSingleStep(0.1)
        self.line_spacing_spin.setValue(cfg.reading_mode_default_line_spacing)
        self.line_spacing_spin.valueChanged.connect(self._on_spacing_changed)
        ctrl_layout.addWidget(self.line_spacing_spin)

        ctrl_layout.addWidget(QLabel("背景："))
        self.bg_combo = QComboBox()
        for name in ReadingModeView.PRESET_BACKGROUNDS:
            self.bg_combo.addItem(name, ReadingModeView.PRESET_BACKGROUNDS[name])
        self.bg_combo.currentIndexChanged.connect(self._on_bg_changed)
        ctrl_layout.addWidget(self.bg_combo)

        ctrl_layout.addStretch()
        self.exit_btn = QPushButton("退出阅读")
        self.exit_btn.setStyleSheet(
            "background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self.exit_btn.clicked.connect(self.exit_reading.emit)
        ctrl_layout.addWidget(self.exit_btn)

        layout.addLayout(ctrl_layout)

        self.view = ReadingModeView()
        self.view.style_changed.connect(self.style_changed.emit)
        layout.addWidget(self.view, 1)

    def set_content(self, text: str) -> None:
        self.view.set_content(text)

    def _on_font_changed(self, size: int) -> None:
        self.view.set_font_size(size)

    def _on_spacing_changed(self, spacing: float) -> None:
        self.view.set_line_spacing(spacing)

    def _on_bg_changed(self, _idx: int) -> None:
        color = self.bg_combo.currentData()
        if color:
            self.view.set_background(color)

    def current_style(self) -> dict:
        return self.view.current_style()