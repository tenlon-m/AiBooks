"""章节版本管理对话框 - 版本列表+差異对比+手动标记+回滚.

后端 API:
    GET  /api/chapters/versions/{chapter_id}            列出章节全部版本
    GET  /api/chapters/versions/diff                    取兩版本差異（HTML diff）
    POST /api/chapters/versions/{version_id}/rollback   回滚到指定版本
    POST /api/chapters/versions/{chapter_id}/mark       手动标记当前内容为新版本
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker


class ChapterVersionDialog(QDialog):
    """章节版本管理对话框.

    展示版本列表（类型/名稱/字數/時間），选中版本后加載差異对比（HTML diff）。
    支持手动标记当前内容为新版本、回滚到指定版本（回滚前彈确认框）。

    信号:
        rollback_requested(str): 用戶请求回滚，攜帶 version_id
        rollback_done(dict): 回滚完成，攜帶后端返回結果
        mark_done(dict): 手动标记完成
    """

    rollback_requested = Signal(str)
    rollback_done = Signal(dict)
    mark_done = Signal(dict)

    def __init__(
        self,
        chapter_id: str,
        chapter_title: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._chapter_id = chapter_id
        self._chapter_title = chapter_title
        self._workers: list[ApiWorker] = []
        self._versions: list[dict] = []
        self._current_version_id: str | None = None
        self.setWindowTitle(f"章节版本管理 - {chapter_title or chapter_id[:8]}")
        self.setMinimumWidth(900)
        self.setMinimumHeight(600)
        self._init_ui()
        self._load_versions()

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


    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("章节版本管理")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        self._context_label = QLabel(
            f"当前章节：{self._chapter_title or self._chapter_id[:8]}"
        )
        self._context_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._context_label)

        # 版本列表表格
        layout.addWidget(QLabel("版本列表（雙擊查看差異）："))
        self._version_table = QTableWidget(0, 5)
        self._version_table.setHorizontalHeaderLabels(
            ["类型", "名稱", "字數", "创建時間", "version_id"]
        )
        self._version_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._version_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._version_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._version_table.setColumnWidth(4, 0)
        self._version_table.itemSelectionChanged.connect(self._on_version_selected)
        layout.addWidget(self._version_table, 1)

        # 差異对比視圖
        layout.addWidget(QLabel("差異对比（与当前内容）："))
        self._diff_view = QTextBrowser()
        self._diff_view.setOpenExternalLinks(False)
        layout.addWidget(self._diff_view, 1)

        # 手动标记
        mark_layout = QHBoxLayout()
        mark_layout.addWidget(QLabel("手动标记名稱："))
        self._mark_edit = QLineEdit()
        self._mark_edit.setPlaceholderText("为当前内容创建一个命名版本（可选）")
        mark_layout.addWidget(self._mark_edit, 1)
        self._mark_btn = QPushButton("标记当前为新版本")
        self._mark_btn.setStyleSheet(
            "background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._mark_btn.clicked.connect(self._mark_current)
        mark_layout.addWidget(self._mark_btn)
        layout.addLayout(mark_layout)

        # 状态
        self._status_label = QLabel("就緒")
        self._status_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._status_label)

        # 按鈕
        btn_layout = QHBoxLayout()
        self._refresh_btn = QPushButton("刷新版本列表")
        self._refresh_btn.clicked.connect(self._load_versions)
        self._rollback_btn = QPushButton("回滚到选中版本")
        self._rollback_btn.setStyleSheet(
            "background-color: #ff9800; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._rollback_btn.setEnabled(False)
        self._rollback_btn.clicked.connect(self._rollback_selected)
        self._close_btn = QPushButton("关闭")
        self._close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._refresh_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self._rollback_btn)
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

    # ---------- 版本列表 ----------
    def _load_versions(self) -> None:
        self._status_label.setText("加載版本列表中...")
        client = get_api_client()
        worker = ApiWorker(
            client.get, f"/api/chapters/versions/{self._chapter_id}"
        )
        worker.result.connect(self._on_versions_loaded)
        worker.error.connect(self._on_load_error)
        self._add_worker(worker)
        worker.start()

    def _on_versions_loaded(self, data: dict | list) -> None:
        versions = data if isinstance(data, list) else data.get("versions", [])
        self._versions = versions
        self._version_table.setRowCount(0)
        type_map = {
            "auto": "自动",
            "manual": "手动",
            "polish": "潤色",
            "rollback": "回滚",
        }
        for v in versions:
            row = self._version_table.rowCount()
            self._version_table.insertRow(row)
            self._version_table.setItem(
                row, 0, QTableWidgetItem(type_map.get(v.get("version_type", ""), "其他"))
            )
            self._version_table.setItem(
                row, 1, QTableWidgetItem(v.get("version_name", ""))
            )
            self._version_table.setItem(
                row, 2, QTableWidgetItem(str(v.get("word_count", 0)))
            )
            self._version_table.setItem(
                row, 3, QTableWidgetItem(v.get("created_at", ""))
            )
            vid_item = QTableWidgetItem(str(v.get("version_id", "")))
            vid_item.setData(Qt.ItemDataRole.UserRole, v.get("version_id"))
            self._version_table.setItem(row, 4, vid_item)
        self._status_label.setText(f"共 {len(versions)} 个版本")

    def _on_load_error(self, msg: str) -> None:
        self._status_label.setText(f"加載失敗：{msg}")
        if "404" not in msg:
            QMessageBox.critical(self, "错误", msg)

    def _on_version_selected(self) -> None:
        row = self._version_table.currentRow()
        if row < 0:
            self._rollback_btn.setEnabled(False)
            return
        vid_item = self._version_table.item(row, 4)
        if not vid_item:
            return
        version_id = vid_item.data(Qt.ItemDataRole.UserRole)
        self._current_version_id = version_id
        self._rollback_btn.setEnabled(bool(version_id))
        if version_id:
            self._load_diff(version_id)

    # ---------- 差異对比 ----------
    def _load_diff(self, version_id: str) -> None:
        self._status_label.setText("加載差異对比中...")
        client = get_api_client()
        payload = {
            "chapter_id": self._chapter_id,
            "version_id": version_id,
        }
        worker = ApiWorker(
            client.get, "/api/chapters/versions/diff", params=payload
        )
        worker.result.connect(self._on_diff_loaded)
        worker.error.connect(self._on_diff_error)
        self._add_worker(worker)
        worker.start()

    def _on_diff_loaded(self, data: dict) -> None:
        html = data.get("diff_html", "")
        if not html:
            # 后端未返回 HTML 時用純文本兜底
            before = data.get("before", "")
            after = data.get("after", "")
            html = (
                f"<h3>选中版本</h3><pre>{before}</pre>"
                f"<h3>当前内容</h3><pre>{after}</pre>"
            )
        self._diff_view.setHtml(html)
        self._status_label.setText("差異对比已加載")

    def _on_diff_error(self, msg: str) -> None:
        self._status_label.setText(f"差異加載失敗：{msg}")
        self._diff_view.setPlainText(f"差異加載失敗：{msg}")

    # ---------- 手动标记 ----------
    def _mark_current(self) -> None:
        name = self._mark_edit.text().strip()
        self._status_label.setText("标记中...")
        self._mark_btn.setEnabled(False)
        client = get_api_client()
        payload = {"version_name": name} if name else {}
        worker = ApiWorker(
            client.post,
            f"/api/chapters/versions/{self._chapter_id}/mark",
            json=payload,
        )
        worker.result.connect(self._on_mark_done)
        worker.error.connect(self._on_mark_error)
        self._add_worker(worker)
        worker.start()

    def _on_mark_done(self, data: dict) -> None:
        self._mark_btn.setEnabled(True)
        self._mark_edit.clear()
        self._status_label.setText("已标记为新版本")
        self.mark_done.emit(data)
        self._load_versions()

    def _on_mark_error(self, msg: str) -> None:
        self._mark_btn.setEnabled(True)
        self._status_label.setText(f"标记失敗：{msg}")
        QMessageBox.critical(self, "错误", msg)

    # ---------- 回滚 ----------
    def _rollback_selected(self) -> None:
        if not self._current_version_id:
            QMessageBox.warning(self, "提示", "请先选中要回滚的版本")
            return
        reply = QMessageBox.question(
            self,
            "确认回滚",
            "确定回滚到选中版本？当前内容將被覆蓋（會自动保存为新版本）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.rollback_requested.emit(self._current_version_id)
        self._status_label.setText("回滚中...")
        self._rollback_btn.setEnabled(False)
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            f"/api/chapters/versions/{self._current_version_id}/rollback",
        )
        worker.result.connect(self._on_rollback_done)
        worker.error.connect(self._on_rollback_error)
        self._add_worker(worker)
        worker.start()

    def _on_rollback_done(self, data: dict) -> None:
        self._rollback_btn.setEnabled(True)
        self._status_label.setText("回滚完成")
        self.rollback_done.emit(data)
        QMessageBox.information(
            self,
            "回滚完成",
            f"已回滚到目标版本，当前字數 {data.get('word_count', 0)}",
        )
        self._load_versions()

    def _on_rollback_error(self, msg: str) -> None:
        self._rollback_btn.setEnabled(True)
        self._status_label.setText(f"回滚失敗：{msg}")
        QMessageBox.critical(self, "错误", msg)