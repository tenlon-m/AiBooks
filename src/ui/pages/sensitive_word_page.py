"""敏感词检测页 - 词库CRUD + 全书扫描 + 命中结果展示 + 跳转章节段落."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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
from src.ui.project_context import get_project_context


class SensitiveWordPage(QWidget):
    scan_completed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._has_unsaved_changes: bool = False
        self._init_ui()
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
        self.word_table.setRowCount(0)
        self.result_table.setRowCount(0)
        self.status_label.clear()
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _mark_unsaved(self) -> None:
        self._has_unsaved_changes = True
        self.save_btn.setStyleSheet("border: 2px solid #ff9800;")

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self._ideas_input.clear()
        if project_id:
            self._load_words()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("敏感词检测")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        ideas_label = QLabel("敏感词检测思路与想法（可选）：在此输入你对敏感词管理的思路和想法")
        ideas_label.setStyleSheet("color: #555; padding: 4px 8px;")
        layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText("例如：屏蔽涉政涉黄词汇，保留文学性表达……")
        self._ideas_input.setMaximumHeight(80)
        self._ideas_input.setStyleSheet("padding: 4px;")
        layout.addWidget(self._ideas_input)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("敏感词库："))
        self.word_table = QTableWidget(0, 4)
        self.word_table.setHorizontalHeaderLabels(["词库ID", "敏感词", "分类", "替换建议"])
        self.word_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.word_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.word_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.word_table)

        word_form_layout = QHBoxLayout()
        word_form_layout.addWidget(QLabel("敏感词："))
        self._word_input = QLineEdit()
        self._word_input.setPlaceholderText("输入敏感词")
        word_form_layout.addWidget(self._word_input)
        word_form_layout.addWidget(QLabel("分类："))
        self._category_input = QLineEdit()
        self._category_input.setPlaceholderText("如：涉政/涉黄/暴力")
        word_form_layout.addWidget(self._category_input)
        word_form_layout.addWidget(QLabel("替换："))
        self._replace_input = QLineEdit()
        self._replace_input.setPlaceholderText("替换建议（可选）")
        word_form_layout.addWidget(self._replace_input)
        layout.addLayout(word_form_layout)

        word_btn_layout = QHBoxLayout()
        self.add_word_btn = QPushButton("添加")
        self.add_word_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;")
        self.add_word_btn.clicked.connect(self._add_word)
        self.delete_word_btn = QPushButton("删除选中")
        self.delete_word_btn.setStyleSheet("background-color: #f44336; color: white; padding: 6px 16px; border-radius: 4px;")
        self.delete_word_btn.clicked.connect(self._delete_word)
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self._save_words)
        word_btn_layout.addWidget(self.add_word_btn)
        word_btn_layout.addWidget(self.delete_word_btn)
        word_btn_layout.addWidget(self.save_btn)
        word_btn_layout.addStretch()
        layout.addLayout(word_btn_layout)

        layout.addWidget(QLabel("扫描结果（双击命中项跳转至对应章节段落）："))
        self.result_table = QTableWidget(0, 6)
        self.result_table.setHorizontalHeaderLabels(["命中ID", "章节", "段落位置", "敏感词", "分类", "替换建议"])
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.result_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.result_table.cellDoubleClicked.connect(self._on_result_double_clicked)
        layout.addWidget(self.result_table)

        btn_layout = QHBoxLayout()
        self.scan_btn = QPushButton("全书扫描")
        self.scan_btn.setStyleSheet("background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;")
        self.scan_btn.clicked.connect(self._scan_all)
        self.refresh_btn = QPushButton("刷新词库")
        self.refresh_btn.clicked.connect(self._load_words)
        btn_layout.addWidget(self.scan_btn)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._progress_label)

    def _get_project_id(self) -> str | None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return None
        return ctx.project_id

    def _load_words(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/sensitive/words")
        worker.result.connect(self._on_words_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_words_loaded(self, words: list) -> None:
        self.word_table.setRowCount(0)
        for w in words:
            row = self.word_table.rowCount()
            self.word_table.insertRow(row)
            word_id_item = QTableWidgetItem(w.get("word_id", ""))
            word_id_item.setData(Qt.ItemDataRole.UserRole, w.get("word_id"))
            self.word_table.setItem(row, 0, word_id_item)
            self.word_table.setItem(row, 1, QTableWidgetItem(w.get("word", "")))
            self.word_table.setItem(row, 2, QTableWidgetItem(w.get("category", "")))
            self.word_table.setItem(row, 3, QTableWidgetItem(w.get("replace_suggestion", "")))
        self.status_label.setText(f"共 {len(words)} 个敏感词")

    def _add_word(self) -> None:
        word = self._word_input.text().strip()
        category = self._category_input.text().strip()
        if not word:
            QMessageBox.warning(self, "提示", "敏感词不能为空")
            return
        if not category:
            QMessageBox.warning(self, "提示", "分类不能为空")
            return
        payload = {
            "word": word,
            "category": category,
            "replace_suggestion": self._replace_input.text().strip() or None,
        }
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/sensitive/words", json=payload)
        worker.result.connect(self._on_word_added)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_word_added(self, _data) -> None:
        self._word_input.clear()
        self._category_input.clear()
        self._replace_input.clear()
        self._load_words()
        self._mark_unsaved()

    def _delete_word(self) -> None:
        rows = set(item.row() for item in self.word_table.selectedItems())
        if not rows:
            QMessageBox.warning(self, "提示", "请先选中要删除的敏感词")
            return
        word_ids: list[str] = []
        for row in rows:
            word_id = self.word_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if word_id:
                word_ids.append(word_id)
        reply = QMessageBox.question(
            self, "确认删除", f"确定删除选中的 {len(word_ids)} 个敏感词？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.delete, "/api/sensitive/words", json={"word_ids": word_ids})
        worker.result.connect(lambda _: self._load_words())
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _save_words(self) -> None:
        words: list[dict] = []
        for row in range(self.word_table.rowCount()):
            words.append({
                "word_id": self.word_table.item(row, 0).data(Qt.ItemDataRole.UserRole),
                "word": self.word_table.item(row, 1).text() if self.word_table.item(row, 1) else "",
                "category": self.word_table.item(row, 2).text() if self.word_table.item(row, 2) else "",
                "replace_suggestion": self.word_table.item(row, 3).text() if self.word_table.item(row, 3) else "",
            })
        client = get_api_client()
        worker = ApiWorker(client.put, "/api/sensitive/words", json={"words": words})
        worker.result.connect(self._on_save_done)
        worker.error.connect(self._on_save_error)
        self._add_worker(worker)
        worker.start()

    def _on_save_done(self, _data) -> None:
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")
        QMessageBox.information(self, "成功", "敏感词库保存成功")

    def _on_save_error(self, msg: str) -> None:
        QMessageBox.critical(self, "保存失败", msg)

    def _scan_all(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        self.scan_btn.setEnabled(False)
        self._progress_label.setText("扫描中...")
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            f"/api/sensitive/scan/{pid}",
            json={"user_ideas": self._ideas_input.toPlainText().strip()},
        )
        worker.result.connect(self._on_scan_done)
        worker.error.connect(self._on_scan_error)
        self._add_worker(worker)
        worker.start()

    def _on_scan_done(self, data: dict) -> None:
        self.scan_btn.setEnabled(True)
        hits = data.get("hits", [])
        self.result_table.setRowCount(0)
        for h in hits:
            row = self.result_table.rowCount()
            self.result_table.insertRow(row)
            hit_id_item = QTableWidgetItem(h.get("hit_id", ""))
            hit_id_item.setData(Qt.ItemDataRole.UserRole, h)
            self.result_table.setItem(row, 0, hit_id_item)
            self.result_table.setItem(row, 1, QTableWidgetItem(h.get("chapter_ref", "")))
            self.result_table.setItem(row, 2, QTableWidgetItem(str(h.get("paragraph_pos", ""))))
            self.result_table.setItem(row, 3, QTableWidgetItem(h.get("word", "")))
            self.result_table.setItem(row, 4, QTableWidgetItem(h.get("category", "")))
            self.result_table.setItem(row, 5, QTableWidgetItem(h.get("replace_suggestion", "")))
        self._progress_label.setText(f"扫描完成，命中 {len(hits)} 处")
        self.scan_completed.emit()

    def _on_scan_error(self, msg: str) -> None:
        self.scan_btn.setEnabled(True)
        self._progress_label.setText(f"扫描失败：{msg}")
        QMessageBox.critical(self, "扫描失败", msg)

    def _on_result_double_clicked(self, row: int, _col: int) -> None:
        item = self.result_table.item(row, 0)
        if not item:
            return
        hit_data: dict = item.data(Qt.ItemDataRole.UserRole) or {}
        chapter_id = hit_data.get("chapter_id", "")
        paragraph_pos = hit_data.get("paragraph_pos", 0)
        chapter_ref = hit_data.get("chapter_ref") or chapter_id
        if not chapter_id:
            QMessageBox.information(self, "提示", "该命中项无章节关联信息")
            return
        main_window = self.window()
        if hasattr(main_window, "pages") and "edit" in main_window.pages:
            edit_page = main_window.pages["edit"]
            if hasattr(edit_page, "load_chapter"):
                # 后端目前只做整章计数（paragraph_pos 固定为 0），
                # 改为把命中的敏感词本身传过去，在章节正文里直接定位高亮。
                edit_page.load_chapter(chapter_id, hit_data.get("word", ""))
            main_window._switch_page("edit")
            word = hit_data.get("word", "")
            self._progress_label.setText(
                f"已跳转到章节 {chapter_ref} 并定位「{word}」"
                if word else f"已跳转到章节 {chapter_ref}"
            )
        else:
            QMessageBox.information(
                self, "提示", f"命中章节：{chapter_ref}，段落位置：{paragraph_pos}"
            )

    def _on_error(self, msg: str) -> None:
        self._progress_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)