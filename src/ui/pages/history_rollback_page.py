"""历史回滚页 - 查看章节修改历史 + 回滚."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context


class HistoryRollbackPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._current_chapter_id: str | None = None
        self._history_records: list[dict] = []
        self._init_ui()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def clear_page(self) -> None:
        self.chapter_combo.clear()
        self.table.setRowCount(0)
        self.preview_edit.clear()
        self._current_chapter_id = None
        self._history_records = []
        self.status_label.clear()

    def has_unsaved_changes(self) -> bool:
        return False

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self.clear_page()
        if project_id:
            self._load_chapters()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("修改历史与回滚")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        nav_layout = QHBoxLayout()
        nav_layout.addWidget(QLabel("选择章节："))
        self.chapter_combo = QComboBox()
        self.chapter_combo.setMinimumWidth(400)
        self.chapter_combo.currentIndexChanged.connect(self._on_chapter_selected)
        nav_layout.addWidget(self.chapter_combo, 1)
        self.refresh_btn = QPushButton("刷新章节列表")
        self.refresh_btn.clicked.connect(self._load_chapters)
        nav_layout.addWidget(self.refresh_btn)
        layout.addLayout(nav_layout)

        layout.addWidget(QLabel("修改历史："))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["记录ID", "修改类型", "修改时间", "可回滚"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_history_selection_changed)
        layout.addWidget(self.table, 1)

        btn_layout = QHBoxLayout()
        self.rollback_btn = QPushButton("回滚到选中记录")
        self.rollback_btn.setStyleSheet("background-color: #ff9800; color: white; padding: 6px 16px; border-radius: 4px;")
        self.rollback_btn.clicked.connect(self._rollback)
        btn_layout.addStretch()
        btn_layout.addWidget(self.rollback_btn)
        layout.addLayout(btn_layout)

        layout.addWidget(QLabel("内容预览："))
        self.preview_edit = QTextEdit()
        self.preview_edit.setReadOnly(True)
        layout.addWidget(self.preview_edit, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

    def _get_project_id(self) -> str | None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return None
        return ctx.project_id

    def _load_chapters(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/writing/{pid}/chapters")
        worker.result.connect(self._on_chapters_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_chapters_loaded(self, chapters: list) -> None:
        self.chapter_combo.clear()
        self.chapter_combo.addItem("-- 选择章节 --", None)
        for c in chapters:
            label = f"第{c['volume_no']}卷第{c['chapter_no']}章 {c['title']}"
            self.chapter_combo.addItem(label, c)

    def _on_chapter_selected(self, index: int) -> None:
        if index <= 0:
            return
        info = self.chapter_combo.itemData(index)
        if not info:
            return
        self._current_chapter_id = info["chapter_id"]
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/chapters/{self._current_chapter_id}/history")
        worker.result.connect(self._on_history_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    _MODIFY_TYPE_LABEL = {
        "manual_edit": "手动/AI修改",
        "rollback": "回滚",
    }

    def _on_history_loaded(self, records: list) -> None:
        self.table.setRowCount(0)
        self._history_records = records or []
        self.preview_edit.clear()
        for r in self._history_records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            id_item = QTableWidgetItem(r.get("record_id", ""))
            # 把整条记录挂在首列，供选中时填充内容预览
            id_item.setData(Qt.ItemDataRole.UserRole, r)
            self.table.setItem(row, 0, id_item)
            modify_type = r.get("modify_type", "")
            self.table.setItem(
                row, 1,
                QTableWidgetItem(self._MODIFY_TYPE_LABEL.get(modify_type, modify_type)),
            )
            self.table.setItem(row, 2, QTableWidgetItem(str(r.get("modified_at", ""))))
            self.table.setItem(row, 3, QTableWidgetItem("是" if r.get("is_rollbackable") else "否"))
        self.status_label.setText(
            f"共 {len(self._history_records)} 条历史记录，选中一行可查看该次修改后的内容"
        )

    def _on_history_selection_changed(self) -> None:
        """选中历史记录后，在「内容预览」展示该次修改后的正文."""
        row = self.table.currentRow()
        if row < 0:
            self.preview_edit.clear()
            return
        id_item = self.table.item(row, 0)
        record = id_item.data(Qt.ItemDataRole.UserRole) if id_item else None
        if not record:
            self.preview_edit.clear()
            return
        preview = record.get("final_content_preview", "") or ""
        if not preview:
            preview = "（该条记录未保存内容预览）"
        self.preview_edit.setPlainText(preview)
        self.status_label.setText(
            f"记录 {record.get('record_id', '')} · "
            f"{self._MODIFY_TYPE_LABEL.get(record.get('modify_type', ''), '')} · "
            f"{record.get('modified_at', '')}"
        )

    def _rollback(self) -> None:
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择章节")
            return
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请选择一条历史记录")
            return
        record_id = self.table.item(row, 0).text()
        rollbackable = self.table.item(row, 3).text() == "是"
        if not rollbackable:
            QMessageBox.warning(self, "提示", "该记录不可回滚")
            return
        reply = QMessageBox.question(self, "确认", "确定回滚到该记录？")
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.post, f"/api/chapters/{self._current_chapter_id}/rollback", json={"target_record_id": record_id})
        worker.result.connect(self._on_rollback_done)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_rollback_done(self, data: dict) -> None:
        success = data.get("success", False)
        msg = data.get("message", "")
        if success:
            self.status_label.setText("回滚成功")
            revalidation = data.get("revalidation")
            if revalidation:
                items = revalidation.get("items", [])
                all_pass = revalidation.get("all_pass", False)
                if all_pass:
                    QMessageBox.information(self, "回滚成功", "回滚成功，再校验全部通过")
                else:
                    lines = ["回滚成功，但再校验发现问题："]
                    for item in items:
                        if item.get("result") == "fail":
                            lines.append(f"  [{item.get('check_type', '')}] {item.get('problem_desc', '')}")
                    QMessageBox.warning(self, "校验结果", "\n".join(lines))
            else:
                QMessageBox.information(self, "成功", "回滚成功")
        else:
            self.status_label.setText(f"回滚失败：{msg}")
            QMessageBox.warning(self, "失败", msg)

    def _on_error(self, msg: str) -> None:
        self.status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)
