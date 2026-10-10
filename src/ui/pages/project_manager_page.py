"""小说工程管理器初始页面 - 项目列表 + 新建/打开/备份/导出/导入/删除 + 写作模板选择."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.widgets.new_project_template_dialog import NewProjectTemplateDialog


class ProjectManagerPage(QWidget):
    request_open_project = Signal(str)

    request_create_with_template = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._init_ui()
        self._load_summaries()

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

    def has_unsaved_changes(self) -> bool:
        return False

    def refresh(self) -> None:
        self._load_summaries()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("小说工程管理器")
        title.setStyleSheet("font-size: 22px; font-weight: bold; padding: 12px;")
        layout.addWidget(title)

        hint = QLabel("请选择一个项目打开，或新建项目开始创作。")
        hint.setStyleSheet("color: #666; padding: 4px 8px;")
        layout.addWidget(hint)

        btn_layout = QHBoxLayout()
        self.create_btn = QPushButton("新建项目")
        self.create_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 8px 20px; border-radius: 4px; font-size: C14px;")
        self.create_btn.clicked.connect(self._on_create)
        self.open_btn = QPushButton("打开项目")
        self.open_btn.setStyleSheet("background-color: #2196f3; color: white; padding: 8px 20px; border-radius: 4px;")
        self.open_btn.clicked.connect(self._on_open)
        self.backup_btn = QPushButton("备份项目")
        self.backup_btn.clicked.connect(self._on_backup)
        self.export_btn = QPushButton("导出项目")
        self.export_btn.clicked.connect(self._on_export)
        self.import_btn = QPushButton("导入项目")
        self.import_btn.clicked.connect(self._on_import)
        self.delete_btn = QPushButton("删除项目")
        self.delete_btn.setStyleSheet("background-color: #f44336; color: white; padding: 8px 20px; border-radius: 4px;")
        self.delete_btn.clicked.connect(self._on_delete)
        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.clicked.connect(self._load_summaries)
        for btn in (self.create_btn, self.open_btn, self.backup_btn, self.export_btn, self.import_btn, self.delete_btn, self.refresh_btn):
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["书名", "状态", "撰写进度", "已写/总章", "创建时间", "最近更新"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._on_open)
        layout.addWidget(self.table, 1)

        self.empty_label = QLabel("暂无项目，请点击\"新建项目\"开始创作。")
        self.empty_label.setStyleSheet("color: #999; padding: 20px; font-size: 14px;")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

    def _load_summaries(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/creation/summaries")
        worker.result.connect(self._on_summaries_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_summaries_loaded(self, summaries: list) -> None:
        self.table.setRowCount(0)
        self.empty_label.setVisible(len(summaries) == 0)
        self.table.setVisible(len(summaries) > 0)
        for s in summaries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            cells = [
                s.get("book_title", ""),
                self._status_text(s.get("status", "")),
                f"{s.get('writing_progress', 0):.1f}%",
                f"{s.get('written_chapters', 0)}/{s.get('total_chapters', 0)}",
                str(s.get("created_at", "")),
                str(s.get("updated_at", "")),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, col, item)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, s.get("project_id", ""))
        self.status_label.setText(f"共 {len(summaries)} 个项目")

    @staticmethod
    def _status_text(status: str) -> str:
        return {
            "draft": "草稿",
            "writing": "撰写中",
            "completed": "已完成",
            "validated": "已校验",
            "failed": "失败",
            "paused": "已暂停",
        }.get(status, status)

    def _get_selected_project_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一个项目")
            return None
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _get_selected_project_name(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).text()

    def _on_create(self) -> None:
        """新建项目：弹出写作模板选择对话框."""
        dialog = NewProjectTemplateDialog(self)
        dialog.create_requested.connect(self._on_template_create_confirmed)
        dialog.exec()

    def _on_template_create_confirmed(self, params: dict) -> None:
        """模板对话框确认后，携带参数发射信号填充创作参数页."""
        self.request_create_with_template.emit(params)

    def _on_open(self) -> None:
        pid = self._get_selected_project_id()
        if pid:
            self.request_open_project.emit(pid)

    def _on_backup(self) -> None:
        pid = self._get_selected_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/backup/trigger", json={"project_id": pid})
        worker.result.connect(lambda _: (self.status_label.setText("备份成功"), QMessageBox.information(self, "成功", "项目备份成功")))
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_export(self) -> None:
        pid = self._get_selected_project_id()
        if not pid:
            return
        target_path, _ = QFileDialog.getSaveFileName(self, "导出项目", "", "AiBooks备份 (*.aibk)")
        if not target_path:
            return
        client = get_api_client()
        payload = {"target_path": target_path, "include_style_libraries": True, "include_ai_call_logs": False}
        worker = ApiWorker(client.post, f"/api/projects/{pid}/export", json=payload)
        worker.result.connect(lambda d: QMessageBox.information(self, "成功", f"项目已导出：{d.get('file_path', '')}"))
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_import(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "导入项目", "", "AiBooks备份 (*.aibk)")
        if not file_path:
            return
        client = get_api_client()
        self.status_label.setText("导入中...")
        worker = ApiWorker(client.post, "/api/projects/import", json={"source_path": file_path, "conflict_strategy": "rename"})
        worker.result.connect(self._on_import_done)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_import_done(self, data: dict) -> None:
        self.status_label.setText(f"项目已导入：{data.get('book_title', '')}")
        self._load_summaries()
        QMessageBox.information(self, "成功", f"项目已导入：{data.get('book_title', '')}\n请确认AI源配置可用后再开始撰写。")

    def _on_delete(self) -> None:
        pid = self._get_selected_project_id()
        if not pid:
            return
        name = self._get_selected_project_name()
        reply = QMessageBox.question(self, "确认删除", f"确定删除项目\"{name}\"？\n此操作不可恢复！")
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.delete, f"/api/creation/{pid}")
        worker.result.connect(lambda _: (self.status_label.setText("项目已删除"), self._load_summaries()))
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_error(self, msg: str) -> None:
        self.status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)