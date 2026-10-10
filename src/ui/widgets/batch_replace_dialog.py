"""批量查找替换对话框 - 跨章节查找替换预览+逐項/全部确认执行.

后端 API:
    POST /api/chapters/replace/preview   预览替换結果（分頁）
    POST /api/chapters/replace/execute   执行替换
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker


# 每頁预览條數：后端分頁加載，避免一次返回數千條匹配导致 UI 卡頓
_PAGE_SIZE = 50


class BatchReplaceDialog(QDialog):
    """批量查找替换对话框.

    支持全書/指定章节范围、普通/正则模式、大小写敏感。
    预览表格分頁加載，逐項确认（按行勾选）或全部确认后执行替换。

    信号:
        confirmed(list[int]): 用戶确认执行替换，攜帶选中的预览項索引列表
        replace_done(dict): 替换完成，攜帶后端返回的执行報告
    """

    confirmed = Signal(list)
    replace_done = Signal(dict)

    def __init__(
        self,
        project_id: str,
        chapter_ids: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_id = project_id
        # 为 None 表示全書范围；非空列表表示指定章节
        self._chapter_ids: list[str] = list(chapter_ids) if chapter_ids else []
        self._workers: list[ApiWorker] = []
        # 预览結果緩存：每項 {preview_id, chapter_id, chapter_title, before, after, match_count}
        self._preview_items: list[dict] = []
        self._current_page: int = 0
        self._total_count: int = 0
        self.setWindowTitle("批量查找替换")
        self.setMinimumWidth(900)
        self.setMinimumHeight(600)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("批量查找替换")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        # 查找/替换输入
        find_layout = QHBoxLayout()
        find_layout.addWidget(QLabel("查找："))
        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText("输入要查找的内容")
        find_layout.addWidget(self._find_edit, 1)
        layout.addLayout(find_layout)

        replace_layout = QHBoxLayout()
        replace_layout.addWidget(QLabel("替换为："))
        self._replace_edit = QLineEdit()
        self._replace_edit.setPlaceholderText("输入替换后的内容")
        replace_layout.addWidget(self._replace_edit, 1)
        layout.addLayout(replace_layout)

        # 范围 + 模式 + 大小写
        option_layout = QHBoxLayout()
        option_layout.addWidget(QLabel("范围："))
        self._scope_combo = QComboBox()
        self._scope_combo.addItem("全書", "all")
        self._scope_combo.addItem("指定章节", "selected")
        if self._chapter_ids:
            self._scope_combo.setCurrentIndex(1)
        else:
            self._scope_combo.setCurrentIndex(0)
        option_layout.addWidget(self._scope_combo)

        option_layout.addWidget(QLabel("模式："))
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("普通", "plain")
        self._mode_combo.addItem("正则", "regex")
        option_layout.addWidget(self._mode_combo)

        self._case_check = QCheckBox("区分大小写")
        option_layout.addWidget(self._case_check)
        option_layout.addStretch()
        layout.addLayout(option_layout)

        # 章节范围提示
        self._scope_label = QLabel()
        self._scope_label.setStyleSheet("color: #666; padding: 2px;")
        self._update_scope_label()
        layout.addWidget(self._scope_label)

        # 预览表格
        layout.addWidget(QLabel("替换预览（勾选要执行的項）："))
        self._preview_table = QTableWidget(0, 6)
        self._preview_table.setHorizontalHeaderLabels(
            ["选", "章节", "匹配數", "原片段", "替换后", "preview_id"]
        )
        self._preview_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._preview_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        # 第 0 列为勾选列，第 5 列 preview_id 隱藏
        self._preview_table.setColumnWidth(0, 40)
        self._preview_table.setColumnWidth(5, 0)
        layout.addWidget(self._preview_table, 1)

        # 分頁导航
        page_layout = QHBoxLayout()
        self._prev_page_btn = QPushButton("上一頁")
        self._prev_page_btn.clicked.connect(self._prev_page)
        self._page_label = QLabel("第 0/0 頁")
        self._page_label.setStyleSheet("color: #666; padding: 2px;")
        self._next_page_btn = QPushButton("下一頁")
        self._next_page_btn.clicked.connect(self._next_page)
        page_layout.addWidget(self._prev_page_btn)
        page_layout.addWidget(self._page_label)
        page_layout.addWidget(self._next_page_btn)
        page_layout.addStretch()
        layout.addLayout(page_layout)

        # 状态
        self._status_label = QLabel("就緒")
        self._status_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._status_label)

        # 按鈕
        btn_layout = QHBoxLayout()
        self._preview_btn = QPushButton("预览")
        self._preview_btn.setStyleSheet(
            "background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._preview_btn.clicked.connect(self._load_preview)
        self._select_all_btn = QPushButton("全选")
        self._select_all_btn.clicked.connect(self._select_all)
        self._select_none_btn = QPushButton("全不选")
        self._select_none_btn.clicked.connect(self._select_none)
        self._confirm_btn = QPushButton("逐項确认执行")
        self._confirm_btn.setStyleSheet(
            "background-color: #ff9800; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._confirm_btn.clicked.connect(self._confirm_selected)
        self._confirm_all_btn = QPushButton("全部确认执行")
        self._confirm_all_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._confirm_all_btn.clicked.connect(self._confirm_all)
        self._close_btn = QPushButton("关闭")
        self._close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._preview_btn)
        btn_layout.addWidget(self._select_all_btn)
        btn_layout.addWidget(self._select_none_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self._confirm_btn)
        btn_layout.addWidget(self._confirm_all_btn)
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

    def _update_scope_label(self) -> None:
        if self._scope_combo.currentData() == "selected":
            count = len(self._chapter_ids)
            self._scope_label.setText(f"指定章节范围：{count} 章")
        else:
            self._scope_label.setText("范围：全書")

    # ---------- 预览加載 ----------
    def _build_payload(self, page: int) -> dict:
        scope = self._scope_combo.currentData()
        return {
            "project_id": self._project_id,
            "find_text": self._find_edit.text(),
            "replace_text": self._replace_edit.text(),
            "mode": self._mode_combo.currentData(),
            "case_sensitive": self._case_check.isChecked(),
            "scope": scope,
            "chapter_ids": self._chapter_ids if scope == "selected" else [],
            "page": page,
            "page_size": _PAGE_SIZE,
        }

    def _load_preview(self) -> None:
        find_text = self._find_edit.text()
        if not find_text:
            QMessageBox.warning(self, "提示", "请输入查找内容")
            return
        if self._scope_combo.currentData() == "selected" and not self._chapter_ids:
            QMessageBox.warning(self, "提示", "指定章节范围为空，请改选全書或先选中章节")
            return
        self._current_page = 0
        self._fetch_page(0)

    def _fetch_page(self, page: int) -> None:
        self._status_label.setText("预览加載中...")
        self._preview_btn.setEnabled(False)
        client = get_api_client()
        payload = self._build_payload(page)
        worker = ApiWorker(client.post, "/api/chapters/replace/preview", json=payload)
        worker.result.connect(self._on_preview_loaded)
        worker.error.connect(self._on_preview_error)
        self._workers.append(worker)
        worker.start()

    def _on_preview_loaded(self, data: dict) -> None:
        self._preview_btn.setEnabled(True)
        items = data.get("items", []) or []
        self._preview_items = items
        self._total_count = int(data.get("total", len(items)))
        self._current_page = int(data.get("page", 0))
        total_pages = max(
            1, (self._total_count + _PAGE_SIZE - 1) // _PAGE_SIZE
        )
        self._page_label.setText(f"第 {self._current_page + 1}/{total_pages} 頁")
        self._prev_page_btn.setEnabled(self._current_page > 0)
        self._next_page_btn.setEnabled(
            (self._current_page + 1) * _PAGE_SIZE < self._total_count
        )
        self._fill_table(items)
        self._status_label.setText(
            f"共 {self._total_count} 处匹配，当前頁 {len(items)} 條"
        )

    def _on_preview_error(self, msg: str) -> None:
        self._preview_btn.setEnabled(True)
        self._status_label.setText(f"预览失敗：{msg}")
        QMessageBox.critical(self, "错误", msg)

    def _fill_table(self, items: list[dict]) -> None:
        self._preview_table.setRowCount(0)
        for item in items:
            row = self._preview_table.rowCount()
            self._preview_table.insertRow(row)
            # 勾选列
            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
            )
            check_item.setCheckState(Qt.CheckState.Checked)
            self._preview_table.setItem(row, 0, check_item)
            # 章节
            self._preview_table.setItem(
                row, 1, QTableWidgetItem(item.get("chapter_title", ""))
            )
            # 匹配數
            self._preview_table.setItem(
                row, 2, QTableWidgetItem(str(item.get("match_count", 0)))
            )
            # 原片段
            self._preview_table.setItem(
                row, 3, QTableWidgetItem(item.get("before", ""))
            )
            # 替换后
            self._preview_table.setItem(
                row, 4, QTableWidgetItem(item.get("after", ""))
            )
            # preview_id（隱藏列）
            pid_item = QTableWidgetItem(str(item.get("preview_id", "")))
            pid_item.setData(Qt.ItemDataRole.UserRole, item.get("preview_id"))
            self._preview_table.setItem(row, 5, pid_item)

    def _prev_page(self) -> None:
        if self._current_page > 0:
            self._fetch_page(self._current_page - 1)

    def _next_page(self) -> None:
        self._fetch_page(self._current_page + 1)

    def _select_all(self) -> None:
        for row in range(self._preview_table.rowCount()):
            item = self._preview_table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def _select_none(self) -> None:
        for row in range(self._preview_table.rowCount()):
            item = self._preview_table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _collect_selected_ids(self) -> list[str]:
        ids: list[str] = []
        for row in range(self._preview_table.rowCount()):
            check_item = self._preview_table.item(row, 0)
            pid_item = self._preview_table.item(row, 5)
            if (
                check_item
                and pid_item
                and check_item.checkState() == Qt.CheckState.Checked
            ):
                pid = pid_item.data(Qt.ItemDataRole.UserRole)
                if pid:
                    ids.append(str(pid))
        return ids

    # ---------- 执行替换 ----------
    def _confirm_selected(self) -> None:
        ids = self._collect_selected_ids()
        if not ids:
            QMessageBox.warning(self, "提示", "请先勾选要执行的替换項")
            return
        reply = QMessageBox.question(
            self,
            "确认执行",
            f"确定对选中的 {len(ids)} 項执行替换？此操作不可撤銷（可通过版本回滚恢復）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.confirmed.emit(list(range(len(ids))))
        self._execute_replace(ids)

    def _confirm_all(self) -> None:
        if not self._preview_items:
            QMessageBox.warning(self, "提示", "请先点擊预览加載匹配結果")
            return
        reply = QMessageBox.question(
            self,
            "确认全部执行",
            f"确定对全部 {self._total_count} 处匹配执行替换？此操作不可撤銷（可通过版本回滚恢復）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # 全部执行：preview_ids 为空表示全量
        self.confirmed.emit([])
        self._execute_replace([])

    def _execute_replace(self, preview_ids: list[str]) -> None:
        self._status_label.setText("执行替换中...")
        self._confirm_btn.setEnabled(False)
        self._confirm_all_btn.setEnabled(False)
        client = get_api_client()
        payload = {
            "project_id": self._project_id,
            "find_text": self._find_edit.text(),
            "replace_text": self._replace_edit.text(),
            "mode": self._mode_combo.currentData(),
            "case_sensitive": self._case_check.isChecked(),
            "scope": self._scope_combo.currentData(),
            "chapter_ids": self._chapter_ids
            if self._scope_combo.currentData() == "selected"
            else [],
            "preview_ids": preview_ids,
        }
        worker = ApiWorker(
            client.post, "/api/chapters/replace/execute", json=payload
        )
        worker.result.connect(self._on_replace_done)
        worker.error.connect(self._on_replace_error)
        self._workers.append(worker)
        worker.start()

    def _on_replace_done(self, data: dict) -> None:
        self._confirm_btn.setEnabled(True)
        self._confirm_all_btn.setEnabled(True)
        replaced = data.get("replaced_count", 0)
        affected = data.get("affected_chapters", 0)
        self._status_label.setText(
            f"替换完成：{replaced} 处，影響 {affected} 章"
        )
        self.replace_done.emit(data)
        QMessageBox.information(
            self,
            "替换完成",
            f"已替换 {replaced} 处，影響 {affected} 章。\n"
            f"失敗：{data.get('failed_count', 0)} 处",
        )
        self.accept()

    def _on_replace_error(self, msg: str) -> None:
        self._confirm_btn.setEnabled(True)
        self._confirm_all_btn.setEnabled(True)
        self._status_label.setText(f"替换失敗：{msg}")
        QMessageBox.critical(self, "错误", msg)