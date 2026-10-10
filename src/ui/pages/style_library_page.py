"""风格库管理页 - 投喂建立/列表/编辑/删除/导出/导入."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
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
from src.ui.widgets.style_library_edit_dialog import StyleLibraryEditDialog


class StyleLibraryPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._file_paths: list[str] = []
        self._has_unsaved_changes: bool = False
        # 「编辑选中」先把详情异步取回来，再开编辑框，避免在UI线程发同步HTTP
        self._pending_edit_lib_id: str = ""
        self._pending_edit_name: str = ""
        self._init_ui()
        self._load_list()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

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
        self._file_paths = []
        self.files_label.setText("已选文件：无")
        self.name_input.clear()
        self.detail_edit.clear()
        self.status_label.clear()
        self._ideas_input.clear()
        self._progress_label.clear()
        self._has_unsaved_changes = False
        self.feed_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;")

    def has_unsaved_changes(self) -> bool:

        return self._has_unsaved_changes

    def _mark_unsaved(self) -> None:
        self._has_unsaved_changes = True
        self.feed_btn.setStyleSheet("border: 2px solid #ff9800;")

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self._ideas_input.clear()
        self._load_list()

    def _get_project_id(self) -> str | None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return None
        return ctx.project_id

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("风格库管理")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        ideas_label = QLabel("风格库思路与想法（可选）：在此输入你对风格库的思路和想法，投喂建立时会充分参考")
        ideas_label.setStyleSheet("color: #555; padding: 4px 8px;")
        layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText("例如：以武侠风格为主，注重动作描写和江湖氛围……")
        self._ideas_input.setMaximumHeight(80)
        self._ideas_input.setStyleSheet("padding: 4px;")
        layout.addWidget(self._ideas_input)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

        feed_layout = QHBoxLayout()
        feed_layout.addWidget(QLabel("风格库名称："))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("输入风格库名称")
        feed_layout.addWidget(self.name_input)
        self.select_files_btn = QPushButton("选择语料文件")
        self.select_files_btn.clicked.connect(self._select_files)
        feed_layout.addWidget(self.select_files_btn)
        feed_layout.addStretch()
        layout.addLayout(feed_layout)

        self.files_label = QLabel("已选文件：无")
        self.files_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.files_label)

        layout.addWidget(QLabel("风格库列表："))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "名称", "命名来源", "构建方式", "特征数"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)
        layout.addWidget(self.table, 1)

        layout.addWidget(QLabel("特征详情："))
        self.detail_edit = QTextEdit()
        self.detail_edit.setReadOnly(True)
        layout.addWidget(self.detail_edit, 1)

        btn_layout = QHBoxLayout()
        self.feed_btn = QPushButton("投喂建立")
        self.feed_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;")
        self.feed_btn.clicked.connect(self._feed_style)
        self.view_btn = QPushButton("查看详情")
        self.view_btn.clicked.connect(self._view_detail)
        self.import_btn = QPushButton("导入风格库")
        self.import_btn.clicked.connect(self._import_library)
        self.export_btn = QPushButton("导出")
        self.export_btn.clicked.connect(self._export_library)
        self.edit_btn = QPushButton("编辑选中")
        self.edit_btn.clicked.connect(self._edit_selected)
        self.batch_delete_btn = QPushButton("批量删除")
        self.batch_delete_btn.setStyleSheet("background-color: #f44336; color: white; padding: 6px 16px; border-radius: 4px;")
        self.batch_delete_btn.clicked.connect(self._batch_delete)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._load_list)
        btn_layout.addWidget(self.feed_btn)
        btn_layout.addWidget(self.view_btn)
        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(self.export_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.batch_delete_btn)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._progress_label)

    def _select_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择语料文件", "", "文本文件 (*.txt *.md);;所有文件 (*)"
        )
        if paths:
            self._file_paths = paths
            self.files_label.setText(f"已选文件：{len(paths)} 个")

    def _feed_style(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入风格库名称")
            return
        if not self._file_paths:
            QMessageBox.warning(self, "提示", "请选择语料文件")
            return
        payload = {
            "file_paths": self._file_paths,
            "naming": "custom",
            "name": name,
            "user_ideas": self._ideas_input.toPlainText().strip(),
        }
        client = get_api_client()
        self.status_label.setText("投喂建立中...")
        self._progress_label.setText("投喂建立中...")
        self.feed_btn.setEnabled(False)
        worker = ApiWorker(client.post, "/api/style-libraries/feed", json=payload)
        worker.result.connect(self._on_feed_done)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_feed_done(self, data: dict) -> None:
        self.feed_btn.setEnabled(True)
        self.status_label.setText(f"风格库已建立：{data.get('name', '')}")
        self._progress_label.clear()
        self._has_unsaved_changes = False
        self.feed_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;")
        self._load_list()
        QMessageBox.information(self, "成功", f"风格库已建立：{data.get('name', '')}")

    def _load_list(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/style-libraries")
        worker.result.connect(self._on_list_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_list_loaded(self, libraries: list) -> None:
        self.table.setRowCount(0)
        for lib in libraries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            id_item = QTableWidgetItem(lib.get("style_library_id", "") or "")
            id_item.setData(Qt.ItemDataRole.UserRole, lib.get("style_library_id"))
            self.table.setItem(row, 0, id_item)
            self.table.setItem(row, 1, QTableWidgetItem(lib.get("name", "")))
            self.table.setItem(row, 2, QTableWidgetItem(lib.get("naming_source", "")))
            self.table.setItem(row, 3, QTableWidgetItem(lib.get("build_method", "")))
            self.table.setItem(row, 4, QTableWidgetItem(str(len(lib.get("features", [])))))

    def _get_selected_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请选择一行")
            return None
        item = self.table.item(row, 0)
        return item.text() if item else None

    def _view_detail(self) -> None:
        lib_id = self._get_selected_id()
        if not lib_id:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/style-libraries/{lib_id}")
        worker.result.connect(self._on_view_detail_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_view_detail_loaded(self, data: dict) -> None:
        features = data.get("features", [])
        lines = [f"风格库：{data.get('name', '')}", f"构建方式：{data.get('build_method', '')}", "", "特征列表："]
        for f in features:
            lines.append(f"  [{f.get('dimension', '')}] {f.get('description', '')} (来源: {f.get('source', '')})")
        corpus = data.get("corpus_info", [])
        if corpus:
            lines.append("")
            lines.append("语料信息：")
            for c in corpus:
                lines.append(f"  {c.get('file_name', '')} - {c.get('char_count', 0)} 字")
        self.detail_edit.setPlainText("\n".join(lines))

    def _export_library(self) -> None:
        lib_id = self._get_selected_id()
        if not lib_id:
            return
        target_path, _ = QFileDialog.getSaveFileName(self, "导出风格库", "", "JSON文件 (*.json)")
        if not target_path:
            return
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/style-libraries/export", json={"style_library_id": lib_id, "target_path": target_path})
        worker.result.connect(lambda d: QMessageBox.information(self, "成功", f"已导出到：{d.get('file_path', '')}"))
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _import_library(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "选择风格库文件", "", "JSON文件 (*.json);;所有文件 (*)")
        if not file_path:
            return
        client = get_api_client()
        self.status_label.setText("导入中...")
        self._progress_label.setText("导入中...")
        worker = ApiWorker(client.post, "/api/style-libraries/import", json={"file_path": file_path})
        worker.result.connect(self._on_import_done)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_import_done(self, data: dict) -> None:
        self.status_label.setText(f"风格库已导入：{data.get('name', '')}")
        self._progress_label.clear()
        self._load_list()
        QMessageBox.information(self, "成功", f"风格库已导入：{data.get('name', '')}")

    def _batch_delete(self) -> None:
        # 风格库是全局资源（列表接口不带 project 参数），不应强制要求先选项目
        selected_rows = set(item.row() for item in self.table.selectedItems())
        lib_ids: list[str] = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item:
                lib_id = item.data(Qt.ItemDataRole.UserRole) or item.text()
                if lib_id:
                    lib_ids.append(lib_id)
        lib_ids = list(dict.fromkeys(lib_ids))
        if not lib_ids:
            QMessageBox.warning(self, "提示", "请先选中要删除的风格库")
            return
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确认删除选中的 {len(lib_ids)} 个风格库？此操作不可撤销",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        self._progress_label.setText("批量删除中...")
        worker = ApiWorker(client.delete, "/api/style-libraries/batch", json={"style_library_ids": lib_ids})
        worker.result.connect(lambda _: self._on_batch_delete_done(len(lib_ids)))
        worker.error.connect(self._on_batch_delete_error)
        self._add_worker(worker)
        worker.start()

    def _on_batch_delete_done(self, count: int) -> None:
        self._progress_label.clear()
        self._load_list()
        QMessageBox.information(self, "成功", f"已删除 {count} 个风格库")

    def _on_batch_delete_error(self, msg: str) -> None:
        self._progress_label.setText(f"批量删除失败：{msg}")
        QMessageBox.critical(self, "错误", f"批量删除失败：{msg}，请检查后重试")

    def _edit_selected(self) -> None:
        rows = set(item.row() for item in self.table.selectedItems())
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择要编辑的风格库")
            return
        row = sorted(rows)[0]
        item = self.table.item(row, 0)
        if not item:
            return
        lib_id = item.data(Qt.ItemDataRole.UserRole) or item.text()
        name = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
        # 用 ApiWorker 异步取详情，避免主线程同步 HTTP 卡住界面
        self._pending_edit_lib_id = lib_id
        self._pending_edit_name = name
        self._progress_label.setText("读取风格库详情...")
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/style-libraries/{lib_id}")
        worker.result.connect(self._on_detail_loaded)
        worker.error.connect(self._on_detail_error)
        self._add_worker(worker)
        worker.start()

    def _on_detail_loaded(self, detail: dict) -> None:
        self._progress_label.clear()
        description = detail.get("description", "") if isinstance(detail, dict) else ""
        self._open_edit_dialog(self._pending_edit_name, description)

    def _on_detail_error(self, msg: str) -> None:
        # 详情拉取失败不阻断编辑，只是描述为空，让用户手动补
        self._progress_label.setText(f"读取详情失败：{msg}")
        self._open_edit_dialog(self._pending_edit_name, "")

    def _open_edit_dialog(self, name: str, description: str) -> None:
        lib_id = self._pending_edit_lib_id
        if not lib_id:
            return
        dialog = StyleLibraryEditDialog(self, name, description)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        client = get_api_client()
        self._progress_label.setText("编辑保存中...")
        worker = ApiWorker(client.put, f"/api/style-libraries/{lib_id}", json=data)
        worker.result.connect(self._on_edit_done)
        worker.error.connect(self._on_edit_error)
        self._add_worker(worker)
        worker.start()

    def _on_edit_done(self, data: dict) -> None:
        self._progress_label.clear()
        self._load_list()
        self._mark_unsaved()
        QMessageBox.information(self, "成功", f"风格库已更新：{data.get('name', '')}")

    def _on_edit_error(self, msg: str) -> None:
        self._progress_label.setText(f"编辑保存失败：{msg}")
        QMessageBox.critical(self, "错误", f"编辑保存失败：{msg}，请检查后重试")

    def _on_table_double_clicked(self, row: int, col: int) -> None:
        self._edit_selected()


    def _on_error(self, msg: str) -> None:
        self.feed_btn.setEnabled(True)
        self.status_label.setText(f"错误：{msg}")
        self._progress_label.clear()
        QMessageBox.critical(self, "错误", msg)
