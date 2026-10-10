"""乱码修复参数配置对话框 - 全局/项目级配置读写."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context


class GarbledConfigDialog(QDialog):
    """乱码修复参数配置对话框，支持全局/项目级切换."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("乱码检测修复配置")
        self.setMinimumWidth(420)
        self._project_id: str | None = None
        ctx = get_project_context()
        if ctx.has_project():
            self._project_id = ctx.project_id

        layout = QVBoxLayout(self)

        scope_layout = QHBoxLayout()
        scope_layout.addWidget(QLabel("配置作用域："))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("全局", "global")
        if self._project_id:
            self.scope_combo.addItem("项目级", "project")
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        scope_layout.addWidget(self.scope_combo)
        scope_layout.addStretch()
        layout.addLayout(scope_layout)

        form = QFormLayout()

        self.enabled_chk = QCheckBox("启用乱码检测修复")
        self.enabled_chk.setChecked(True)
        form.addRow(self.enabled_chk)

        self.max_blank_lines_spin = QSpinBox()
        self.max_blank_lines_spin.setRange(1, 10)
        self.max_blank_lines_spin.setValue(1)
        form.addRow("最大连续空行数：", self.max_blank_lines_spin)

        self.max_punct_repeat_spin = QSpinBox()
        self.max_punct_repeat_spin.setRange(2, 10)
        self.max_punct_repeat_spin.setValue(2)
        form.addRow("最大标点重复次数：", self.max_punct_repeat_spin)

        self.max_consecutive_spaces_spin = QSpinBox()
        self.max_consecutive_spaces_spin.setRange(2, 10)
        self.max_consecutive_spaces_spin.setValue(2)
        form.addRow("最大连续空格数：", self.max_consecutive_spaces_spin)

        self.enable_fullwidth_indent_chk = QCheckBox("全角空格段首缩进")
        self.enable_fullwidth_indent_chk.setChecked(True)
        form.addRow(self.enable_fullwidth_indent_chk)

        self.enable_punct_repeat_fix_chk = QCheckBox("标点重复修复")
        self.enable_punct_repeat_fix_chk.setChecked(True)
        form.addRow(self.enable_punct_repeat_fix_chk)

        self.enable_whitespace_cleanup_chk = QCheckBox("空白清理")
        self.enable_whitespace_cleanup_chk.setChecked(True)
        form.addRow(self.enable_whitespace_cleanup_chk)

        self.enable_irreversible_clear_chk = QCheckBox("不可逆乱码清除")
        self.enable_irreversible_clear_chk.setChecked(True)
        form.addRow(self.enable_irreversible_clear_chk)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self._on_save)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self._workers: list = []
        self._load_config()

    def _current_scope(self) -> str:
        return self.scope_combo.currentData()

    def _on_scope_changed(self) -> None:
        self._load_config()

    def _load_config(self) -> None:
        scope = self._current_scope()
        path = f"/api/writing/garbled-config/{scope}"
        if scope == "project" and self._project_id:
            path = f"/api/writing/garbled-config/project/{self._project_id}"
        client = get_api_client()
        worker = ApiWorker(client.get, path)
        worker.result.connect(self._on_config_loaded)
        worker.error.connect(self._on_load_error)
        self._workers.append(worker)
        worker.start()

    def _on_config_loaded(self, data: dict) -> None:
        if not data:
            return
        self.enabled_chk.setChecked(data.get("enabled", True))
        self.max_blank_lines_spin.setValue(data.get("max_blank_lines", 1) or 1)
        self.max_punct_repeat_spin.setValue(data.get("max_punct_repeat", 2) or 2)
        self.max_consecutive_spaces_spin.setValue(data.get("max_consecutive_spaces", 2) or 2)
        self.enable_fullwidth_indent_chk.setChecked(data.get("enable_fullwidth_indent", True))
        self.enable_punct_repeat_fix_chk.setChecked(data.get("enable_punct_repeat_fix", True))
        self.enable_whitespace_cleanup_chk.setChecked(data.get("enable_whitespace_cleanup", True))
        self.enable_irreversible_clear_chk.setChecked(data.get("enable_irreversible_clear", True))

    def _on_load_error(self, msg: str) -> None:
        pass

    def _on_save(self) -> None:
        scope = self._current_scope()
        config = {
            "enabled": self.enabled_chk.isChecked(),
            "max_blank_lines": self.max_blank_lines_spin.value(),
            "max_punct_repeat": self.max_punct_repeat_spin.value(),
            "max_consecutive_spaces": self.max_consecutive_spaces_spin.value(),
            "enable_fullwidth_indent": self.enable_fullwidth_indent_chk.isChecked(),
            "enable_punct_repeat_fix": self.enable_punct_repeat_fix_chk.isChecked(),
            "enable_whitespace_cleanup": self.enable_whitespace_cleanup_chk.isChecked(),
            "enable_irreversible_clear": self.enable_irreversible_clear_chk.isChecked(),
        }
        path = f"/api/writing/garbled-config/{scope}"
        if scope == "project" and self._project_id:
            path = f"/api/writing/garbled-config/project/{self._project_id}"
        client = get_api_client()
        worker = ApiWorker(client.put, path, json=config)
        worker.result.connect(self._on_save_done)
        worker.error.connect(self._on_save_error)
        self._workers.append(worker)
        worker.start()

    def _on_save_done(self, data: dict) -> None:
        QMessageBox.information(self, "成功", "配置已保存")
        self.accept()

    def _on_save_error(self, msg: str) -> None:
        QMessageBox.critical(self, "错误", f"保存失败：{msg}")