"""全局主题设置弹窗."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QFrame,
    QVBoxLayout,
    QWidget,
    QDialog,
    QColorDialog,
)

from src.ui.theme.contrast_checker import ContrastChecker
from src.ui.theme.models import ThemeId
from src.ui.theme.presets import PRESET_THEMES, PRESET_MAP
from src.ui.theme.theme_manager import ThemeManager
from src.ui.theme.theme_settings_store import ThemeSettingsStore


class ThemeSettingsDialog(QDialog):
    """全局主题设置弹窗（单例）."""

    _instance: "ThemeSettingsDialog | None" = None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("全局主题")
        self.setFixedSize(560, 540)
        self._store = ThemeSettingsStore()
        self._theme_buttons: dict[str, QPushButton] = {}
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(lambda: self._status_label.clear())

        self._init_ui()
        self._load_current_state()

        mgr = ThemeManager.instance()
        mgr.theme_changed.connect(self._on_theme_changed_external)

    # ------------------------------------------------------------------ UI

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        hint = QLabel(
            "即时预览，修改后自动保存并即时全局生效。"
            "'跟随系统'使用操作系统明暗配色。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setSpacing(8)
        for i, info in enumerate(PRESET_THEMES):
            btn = QPushButton(info.display_name)
            btn.setFixedHeight(44)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda checked, tid=info.theme_id: self._on_theme_button_clicked(tid)
            )
            self._theme_buttons[info.theme_id] = btn
            grid.addWidget(btn, i // 4, i % 4)
        layout.addLayout(grid)

        color_layout = QHBoxLayout()

        self._fg_label = QLabel("自定义文字颜色:")
        self._fg_swatch = QPushButton()
        self._fg_swatch.setFixedSize(40, 28)
        self._fg_swatch.clicked.connect(self._on_fg_swatch_clicked)
        self._fg_edit = QLineEdit()
        self._fg_edit.setPlaceholderText("#RRGGBB")
        self._fg_edit.setMaxLength(7)
        self._fg_edit.textChanged.connect(self._on_fg_edit_changed)
        fg_group = QVBoxLayout()
        fg_group.addWidget(self._fg_label)
        fg_row = QHBoxLayout()
        fg_row.addWidget(self._fg_swatch)
        fg_row.addWidget(self._fg_edit)
        fg_group.addLayout(fg_row)
        color_layout.addLayout(fg_group)

        self._bg_label = QLabel("自定义背景颜色:")
        self._bg_swatch = QPushButton()
        self._bg_swatch.setFixedSize(40, 28)
        self._bg_swatch.clicked.connect(self._on_bg_swatch_clicked)
        self._bg_edit = QLineEdit()
        self._bg_edit.setPlaceholderText("#RRGGBB")
        self._bg_edit.setMaxLength(7)
        self._bg_edit.textChanged.connect(self._on_bg_edit_changed)
        bg_group = QVBoxLayout()
        bg_group.addWidget(self._bg_label)
        bg_row = QHBoxLayout()
        bg_row.addWidget(self._bg_swatch)
        bg_row.addWidget(self._bg_edit)
        bg_group.addLayout(bg_row)
        color_layout.addLayout(bg_group)

        layout.addLayout(color_layout)

        self._preview_frame = QFrame()
        self._preview_frame.setFixedHeight(80)
        self._preview_layout = QVBoxLayout(self._preview_frame)
        self._preview_title = QLabel("全局主题预览")
        self._preview_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        self._preview_text = QLabel("窗外的风轻轻吹过，书页间的故事还在继续。")
        self._preview_layout.addWidget(self._preview_title)
        self._preview_layout.addWidget(self._preview_text)
        layout.addWidget(self._preview_frame)

        bottom_layout = QHBoxLayout()
        self._status_label = QLabel()
        bottom_layout.addWidget(self._status_label)

        bottom_layout.addStretch()

        reset_btn = QPushButton("恢复默认主题")
        reset_btn.clicked.connect(self._on_reset_clicked)
        bottom_layout.addWidget(reset_btn)

        save_btn = QPushButton("立即保存")
        save_btn.clicked.connect(self._on_save_clicked)
        bottom_layout.addWidget(save_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(close_btn)

        layout.addLayout(bottom_layout)

    # ------------------------------------------------------------------ 状态

    def _load_current_state(self) -> None:
        """初始化时加载当前主题状态."""
        mgr = ThemeManager.instance()
        config = mgr.current_theme()
        self._sync_theme_selection(config.theme_id)

        if config.theme_id == ThemeId.CUSTOM.value:
            self._set_color_edit(self._fg_edit, self._fg_swatch, config.custom_foreground)
            self._set_color_edit(self._bg_edit, self._bg_swatch, config.custom_background)
            self._set_custom_enabled(True)
        else:
            self._set_color_edit(self._fg_edit, self._fg_swatch, "#222222")
            self._set_color_edit(self._bg_edit, self._bg_swatch, "#F5F5F5")
            self._set_custom_enabled(False)

        resolved = mgr.resolve_colors(config.theme_id)
        self._update_preview(resolved.foreground, resolved.background)

    def _sync_theme_selection(self, theme_id: str) -> None:
        """同步主题按钮选中态高亮 + 主题色着色."""
        for tid, btn in self._theme_buttons.items():
            info = PRESET_MAP.get(tid)
            if info is None:
                continue
            mgr = ThemeManager.instance()
            resolved = mgr.resolve_colors(tid)
            fg = resolved.foreground or "#222222"
            bg = resolved.background or "#F5F5F5"
            if tid == theme_id:
                border = "3px solid #FF9800"
                font_w = "bold"
            else:
                border = "1px solid #ccc"
                font_w = "normal"
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: {fg}; "
                f"border: {border}; border-radius: 6px; "
                f"font-size: 13px; font-weight: {font_w}; }}"
            )

    def _set_custom_enabled(self, enabled: bool) -> None:
        """启用/禁用自定义颜色选择器."""
        self._fg_swatch.setEnabled(enabled)
        self._fg_edit.setEnabled(enabled)
        self._bg_swatch.setEnabled(enabled)
        self._bg_edit.setEnabled(enabled)

    def _set_color_edit(self, edit: QLineEdit, swatch: QPushButton, hex_color: str) -> None:
        """设置颜色输入框与色块."""
        edit.blockSignals(True)
        edit.setText(hex_color)
        edit.blockSignals(False)
        swatch.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #ccc;")

    def _update_preview(self, foreground: str, background: str) -> None:
        """更新预览区配色."""
        self._preview_frame.setStyleSheet(
            f"QFrame {{ background-color: {background}; border: 1px solid #ccc; border-radius: 6px; }}"
        )
        self._preview_title.setStyleSheet(
            f"color: {foreground}; font-size: 14px; font-weight: bold;"
        )
        self._preview_text.setStyleSheet(f"color: {foreground};")

    def _show_status(self, text: str, auto_clear: bool = True) -> None:
        """显示状态提示."""
        self._status_label.setText(text)
        if auto_clear:
            self._status_timer.start(3000)

    # ------------------------------------------------------------------ 槽

    def _on_theme_button_clicked(self, theme_id: str) -> None:
        """点击主题按钮."""
        mgr = ThemeManager.instance()
        mgr.set_theme(theme_id)
        self._sync_theme_selection(theme_id)
        self._set_custom_enabled(theme_id == ThemeId.CUSTOM.value)
        resolved = mgr.resolve_colors(theme_id)
        self._update_preview(resolved.foreground, resolved.background)
        self._show_status("设置已自动保存")

    def _on_fg_swatch_clicked(self) -> None:
        """点击前景色块."""
        color = QColorDialog.getColor(QColor(self._fg_edit.text()), self, "选择文字颜色")
        if color.isValid():
            hex_str = color.name().upper()
            self._set_color_edit(self._fg_edit, self._fg_swatch, hex_str)
            self._apply_custom_colors()

    def _on_bg_swatch_clicked(self) -> None:
        """点击背景色块."""
        color = QColorDialog.getColor(QColor(self._bg_edit.text()), self, "选择背景颜色")
        if color.isValid():
            hex_str = color.name().upper()
            self._set_color_edit(self._bg_edit, self._bg_swatch, hex_str)
            self._apply_custom_colors()

    def _on_fg_edit_changed(self, text: str) -> None:
        """前景色 HEX 输入框变化."""
        text = text.strip()
        if ContrastChecker.parse_hex(text) is not None:
            self._fg_edit.setStyleSheet("")
            self._fg_swatch.setStyleSheet(f"background-color: {text}; border: 1px solid #ccc;")
            self._apply_custom_colors()
        else:
            self._fg_edit.setStyleSheet("border: 1px solid red;")

    def _on_bg_edit_changed(self, text: str) -> None:
        """背景色 HEX 输入框变化."""
        text = text.strip()
        if ContrastChecker.parse_hex(text) is not None:
            self._bg_edit.setStyleSheet("")
            self._bg_swatch.setStyleSheet(f"background-color: {text}; border: 1px solid #ccc;")
            self._apply_custom_colors()
        else:
            self._bg_edit.setStyleSheet("border: 1px solid red;")

    def _apply_custom_colors(self) -> None:
        """应用自定义颜色（含对比度校验）."""
        fg = self._fg_edit.text().strip()
        bg = self._bg_edit.text().strip()
        if ContrastChecker.parse_hex(fg) is None or ContrastChecker.parse_hex(bg) is None:
            return

        ratio = ContrastChecker.contrast_ratio(fg, bg)
        if ratio < 3.0:
            reply = QMessageBox.warning(
                self,
                "对比度严重不足",
                f"对比度仅 {ratio:.2f}:1，文字可能无法辨识。\n建议重新选择颜色。\n\n是否继续应用？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        elif ratio < 4.5:
            QMessageBox.information(
                self,
                "对比度提示",
                f"文字与背景对比度为 {ratio:.2f}:1，建议 ≥ 4.5:1。\n可能影响阅读，已应用当前配色。",
            )

        mgr = ThemeManager.instance()
        mgr.set_custom_colors(fg, bg)
        self._sync_theme_selection(ThemeId.CUSTOM.value)
        self._update_preview(fg, bg)
        self._show_status("设置已自动保存")

    def _on_save_clicked(self) -> None:
        """立即保存按钮."""
        mgr = ThemeManager.instance()
        ok = self._store.save(mgr.current_theme())
        if ok:
            self._show_status("设置已保存", auto_clear=False)
        else:
            self._show_status("设置保存失败，请检查磁盘空间或权限", auto_clear=False)

    def _on_reset_clicked(self) -> None:
        """恢复默认主题按钮."""
        mgr = ThemeManager.instance()
        mgr.reset_to_default()
        self._sync_theme_selection(ThemeId.FOLLOW_SYSTEM.value)
        self._set_color_edit(self._fg_edit, self._fg_swatch, "#222222")
        self._set_color_edit(self._bg_edit, self._bg_swatch, "#F5F5F5")
        self._set_custom_enabled(False)
        resolved = mgr.resolve_colors(ThemeId.FOLLOW_SYSTEM.value)
        self._update_preview(resolved.foreground, resolved.background)
        self._show_status("设置已自动保存")

    def _on_theme_changed_external(self, theme_data: dict) -> None:
        """外部主题变更（如系统明暗切换）时同步弹窗 UI."""
        theme_id = theme_data.get("theme_id", "")
        self._sync_theme_selection(theme_id)
        self._set_custom_enabled(theme_id == ThemeId.CUSTOM.value)
        self._update_preview(
            theme_data.get("foreground", "#222222"),
            theme_data.get("background", "#F5F5F5"),
        )

    # ------------------------------------------------------------------ 单例

    @classmethod
    def show_instance(cls, parent: QWidget) -> None:
        """单例化显示弹窗."""
        if cls._instance is not None:
            cls._instance.raise_()
            cls._instance.activateWindow()
            return
        dlg = cls(parent)
        dlg.finished.connect(cls._clear_instance)
        cls._instance = dlg
        dlg.show()

    @classmethod
    def _clear_instance(cls) -> None:
        """清除单例引用."""
        cls._instance = None