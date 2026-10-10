"""快捷键配置页 - 列表/修改/重置，遵循统一页面范式.

布局：标题 → 思路输入栏 → 状态标签 → 内容区(QTableWidget) → 底部按钮栏 → 进度标签
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker


class _ShortcutEditDialog(QDialog):
    """快捷键编辑对话框：捕获按键序列 + 启用开关."""

    def __init__(
        self,
        action_label: str,
        current_seq: str,
        enabled: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"修改快捷键 - {action_label}")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"操作：{action_label}"))
        layout.addWidget(QLabel("请按下新的快捷键组合："))
        self.seq_edit = QKeySequenceEdit()
        self.seq_edit.setKeySequence(QKeySequence(current_seq))
        layout.addWidget(self.seq_edit)

        self.enabled_check = QCheckBox("启用此快捷键")
        self.enabled_check.setChecked(enabled)
        layout.addWidget(self.enabled_check)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def key_sequence(self) -> str:
        return self.seq_edit.keySequence().toString()

    def enabled(self) -> bool:
        return self.enabled_check.isChecked()


class ShortcutConfigPage(QWidget):
    """快捷键配置页."""

    shortcut_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._has_unsaved_changes: bool = False
        self._init_ui()

    def _add_worker(self, worker) -> None:
        """注册 ApiWorker 并在完成后自动清理."""
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))

    def _cleanup_worker(self, worker) -> None:
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()


    def clear_page(self) -> None:
        self.table.setRowCount(0)
        self.status_label.clear()
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _mark_unsaved(self) -> None:
        self._has_unsaved_changes = True
        self.save_btn.setStyleSheet("border: 2px solid #ff9800;")

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("快捷键配置")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        ideas_label = QLabel(
            "快捷键配置思路与想法（可选）：在此输入你对快捷键布局的偏好，便于后续 AI 辅助推荐"
        )
        ideas_label.setStyleSheet("color: #555; padding: 4px 8px;")
        layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText(
            "例如：保存用 Ctrl+S，查找用 Ctrl+F，AI 对话用 Ctrl+Shift+D……"
        )
        self._ideas_input.setMaximumHeight(80)
        self._ideas_input.setStyleSheet("padding: 4px;")
        layout.addWidget(self._ideas_input)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["操作", "快捷键", "启用", "内置"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table, 1)

        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.clicked.connect(self._load_shortcuts)
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self._save_changes)
        self.reset_btn = QPushButton("重置为预设")
        self.reset_btn.setStyleSheet(
            "background-color: #ff9800; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self.reset_btn.clicked.connect(self._reset_shortcuts)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.reset_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._progress_label)

        self._load_shortcuts()

    def _load_shortcuts(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/shortcuts")
        worker.result.connect(self._on_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_loaded(self, shortcuts: list) -> None:
        self.table.setRowCount(0)
        for s in shortcuts:
            row = self.table.rowCount()
            self.table.insertRow(row)
            label_item = QTableWidgetItem(s.get("action_label", ""))
            label_item.setData(Qt.ItemDataRole.UserRole, s.get("shortcut_id"))
            self.table.setItem(row, 0, label_item)
            self.table.setItem(row, 1, QTableWidgetItem(s.get("key_sequence", "")))
            self.table.setItem(
                row, 2, QTableWidgetItem("是" if s.get("enabled") else "否")
            )
            self.table.setItem(
                row, 3, QTableWidgetItem("是" if s.get("is_builtin") else "否")
            )
        self.status_label.setText(f"共 {len(shortcuts)} 个快捷键配置")
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        if col != 1 and col != 2:
            return
        label_item = self.table.item(row, 0)
        if not label_item:
            return
        shortcut_id = label_item.data(Qt.ItemDataRole.UserRole)
        action_label = label_item.text()
        current_seq = (
            self.table.item(row, 1).text() if self.table.item(row, 1) else ""
        )
        enabled_text = (
            self.table.item(row, 2).text() if self.table.item(row, 2) else "是"
        )
        enabled = enabled_text == "是"

        dialog = _ShortcutEditDialog(action_label, current_seq, enabled, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_seq = dialog.key_sequence()
        new_enabled = dialog.enabled()
        if not new_seq:
            QMessageBox.warning(self, "提示", "快捷键不能为空")
            return
        self._update_shortcut(shortcut_id, new_seq, new_enabled, row)

    def _update_shortcut(
        self, shortcut_id: str, key_sequence: str, enabled: bool, row: int
    ) -> None:
        client = get_api_client()
        payload = {"key_sequence": key_sequence, "enabled": enabled}
        worker = ApiWorker(
            client.put, f"/api/shortcuts/{shortcut_id}", json=payload
        )
        worker.result.connect(lambda d: self._on_update_done(d, row))
        worker.error.connect(lambda msg: self._on_update_error(msg, row))
        self._add_worker(worker)
        worker.start()

    def _on_update_done(self, data: dict, row: int) -> None:
        self.table.setItem(row, 1, QTableWidgetItem(data.get("key_sequence", "")))
        self.table.setItem(
            row, 2, QTableWidgetItem("是" if data.get("enabled") else "否")
        )
        self.status_label.setText(f"已更新：{data.get('action_label', '')}")
        self._mark_unsaved()
        self.shortcut_changed.emit()

    def _on_update_error(self, msg: str, row: int) -> None:
        if "API 409" in msg:
            QMessageBox.warning(
                self, "快捷键冲突", f"快捷键冲突：{msg}\n请使用其他按键组合"
            )
        else:
            QMessageBox.critical(self, "错误", f"更新失败：{msg}")
        self.status_label.setText(f"更新失败：{msg}")

    def _reset_shortcuts(self) -> None:
        reply = QMessageBox.question(
            self,
            "确认",
            "确定要重置全部快捷键为预设值吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/shortcuts/reset")
        worker.result.connect(self._on_reset_done)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_reset_done(self, data: dict) -> None:
        count = data.get("reset_count", 0)
        self.status_label.setText(f"已重置 {count} 个快捷键为预设值")
        self._on_loaded(data.get("shortcuts", []))
        self.shortcut_changed.emit()

    def _save_changes(self) -> None:
        """快捷键在双击编辑时已即时落库（PUT /api/shortcuts/{id}），无需再提交。

        此处不做空操作假装保存，而是明确告知用户实际行为，避免误以为修改未生效。
        """
        had_pending = self._has_unsaved_changes
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")
        self._progress_label.clear()
        if had_pending:
            # 兜底：若将来改为批量暂存，这里能挡住静默丢改动
            self._has_unsaved_changes = True
            QMessageBox.warning(self, "提示", "存在未保存的修改，请双击对应行重新确认")
            return
        self.status_label.setText(
            "快捷键在双击编辑时已即时保存，无需再点保存；如需恢复默认请点「重置为预设」"
        )
        QMessageBox.information(
            self, "无需保存",
            "快捷键修改在双击编辑、弹出框确认后会立即写入数据库，\n"
            "不存在「待保存」的改动。\n\n"
            "若要把全部快捷键恢复为默认值，请点击「重置为预设」。",
        )

    def _on_error(self, msg: str) -> None:
        self.status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)