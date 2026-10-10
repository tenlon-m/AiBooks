"""降AI率改写页 - 选择章节→AI改写→原文/改写对比→采纳或回退."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context

_STRATEGY_LABELS = {
    "句式变换": "句式变换",
    "同义替换": "同义替换",
    "口语化": "口语化",
    "全部": "全部策略",
}


class AntiAiPage(QWidget):
    """降AI率改写页面."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._current_chapter_id: str | None = None
        self._current_rewrite_id: str | None = None
        self._init_ui()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def clear_page(self) -> None:
        self._chapter_combo.clear()
        self._chapter_combo.addItem("-- 选择章节 --", None)
        self._original_edit.clear()
        self._rewritten_edit.clear()
        self._strategy_combo.setCurrentIndex(3)
        self._current_chapter_id = None
        self._current_rewrite_id = None
        self._adopt_btn.setEnabled(False)
        self._rollback_btn.setEnabled(False)
        self._status_label.setText("就绪")

    def has_unsaved_changes(self) -> bool:
        return False

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self.clear_page()
        if project_id:
            self._load_chapters()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("降AI率改写")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        desc = QLabel(
            "针对朱雀等AI检测器，通过句式变换、同义替换、口语化等策略改写章节，"
            "在保持语义不变的前提下降低AI检测率。"
        )
        desc.setStyleSheet("color: #555; padding: 4px 8px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        nav_layout = QHBoxLayout()
        nav_layout.addWidget(QLabel("选择章节："))
        self._chapter_combo = QComboBox()
        self._chapter_combo.setMinimumWidth(400)
        self._chapter_combo.currentIndexChanged.connect(self._on_chapter_selected)
        nav_layout.addWidget(self._chapter_combo, 1)
        self._refresh_btn = QPushButton("刷新章节列表")
        self._refresh_btn.clicked.connect(self._load_chapters)
        nav_layout.addWidget(self._refresh_btn)
        layout.addLayout(nav_layout)

        strategy_layout = QHBoxLayout()
        strategy_layout.addWidget(QLabel("改写策略："))
        self._strategy_combo = QComboBox()
        for label, data in _STRATEGY_LABELS.items():
            self._strategy_combo.addItem(label, data)
        self._strategy_combo.setCurrentIndex(3)
        strategy_layout.addWidget(self._strategy_combo)
        strategy_layout.addStretch()
        layout.addLayout(strategy_layout)

        btn_layout = QHBoxLayout()
        self._rewrite_btn = QPushButton("开始改写")
        self._rewrite_btn.setStyleSheet(
            "background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._rewrite_btn.clicked.connect(self._do_rewrite)
        self._adopt_btn = QPushButton("采纳改写")
        self._adopt_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._adopt_btn.clicked.connect(self._do_adopt)
        self._adopt_btn.setEnabled(False)
        self._rollback_btn = QPushButton("回退至原文")
        self._rollback_btn.setStyleSheet(
            "background-color: #ff9800; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._rollback_btn.clicked.connect(self._do_rollback)
        self._rollback_btn.setEnabled(False)
        self._history_btn = QPushButton("查看改写历史")
        self._history_btn.clicked.connect(self._load_history)
        btn_layout.addWidget(self._rewrite_btn)
        btn_layout.addWidget(self._adopt_btn)
        btn_layout.addWidget(self._rollback_btn)
        btn_layout.addWidget(self._history_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        compare_layout = QHBoxLayout()
        left_col = QVBoxLayout()
        left_col.addWidget(QLabel("原文："))
        self._original_edit = QTextEdit()
        self._original_edit.setReadOnly(True)
        left_col.addWidget(self._original_edit, 1)
        right_col = QVBoxLayout()
        right_col.addWidget(QLabel("改写文："))
        self._rewritten_edit = QTextEdit()
        self._rewritten_edit.setReadOnly(True)
        right_col.addWidget(self._rewritten_edit, 1)
        compare_layout.addLayout(left_col, 1)
        compare_layout.addLayout(right_col, 1)
        layout.addLayout(compare_layout, 1)

        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self._status_label)

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
        self._chapter_combo.clear()
        self._chapter_combo.addItem("-- 选择章节 --", None)
        for c in chapters:
            label = f"第{c['volume_no']}卷第{c['chapter_no']}章 {c['title']}"
            self._chapter_combo.addItem(label, c)

    def _on_chapter_selected(self, index: int) -> None:
        if index <= 0:
            self._current_chapter_id = None
            self._original_edit.clear()
            self._rewritten_edit.clear()
            self._adopt_btn.setEnabled(False)
            self._rollback_btn.setEnabled(False)
            return
        info = self._chapter_combo.itemData(index)
        if not info:
            return
        self._current_chapter_id = info["chapter_id"]
        self._rewritten_edit.clear()
        self._current_rewrite_id = None
        self._adopt_btn.setEnabled(False)
        self._rollback_btn.setEnabled(False)
        client = get_api_client()
        worker = ApiWorker(
            client.get, f"/api/chapters/{self._current_chapter_id}/content"
        )
        worker.result.connect(self._on_content_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_content_loaded(self, data: dict) -> None:
        content = data.get("content", "") or ""
        self._original_edit.setPlainText(content)
        self._status_label.setText(
            f"已加载原文，共 {len(content)} 字"
        )

    def _do_rewrite(self) -> None:
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择章节")
            return
        strategy = self._strategy_combo.currentData()
        self._rewrite_btn.setEnabled(False)
        self._adopt_btn.setEnabled(False)
        self._rollback_btn.setEnabled(False)
        self._status_label.setText("AI改写中，请稍候...")
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            "/api/anti-ai/rewrite",
            json={
                "chapter_id": self._current_chapter_id,
                "strategy": strategy,
            },
        )
        worker.result.connect(self._on_rewrite_done)
        worker.error.connect(self._on_rewrite_error)
        self._workers.append(worker)
        worker.start()

    def _on_rewrite_done(self, data: dict) -> None:
        self._rewrite_btn.setEnabled(True)
        rewritten = data.get("rewritten_content", "") or ""
        self._rewritten_edit.setPlainText(rewritten)
        self._current_rewrite_id = data.get("rewrite_id")
        adopt_status = data.get("adopt_status", "待采纳")
        self._adopt_btn.setEnabled(adopt_status == "待采纳")
        self._rollback_btn.setEnabled(adopt_status == "已采纳")
        self._status_label.setText(
            f"改写完成，共 {len(rewritten)} 字，策略：{data.get('strategy', '')}"
        )

    def _on_rewrite_error(self, msg: str) -> None:
        self._rewrite_btn.setEnabled(True)
        self._status_label.setText(f"改写失败：{msg}")
        QMessageBox.critical(self, "改写失败", msg)

    def _do_adopt(self) -> None:
        if not self._current_rewrite_id:
            QMessageBox.warning(self, "提示", "没有可采纳的改写")
            return
        reply = QMessageBox.question(
            self,
            "确认采纳",
            "采纳后章节正文将被替换为改写内容，确定采纳？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.post, f"/api/anti-ai/{self._current_rewrite_id}/adopt"
        )
        worker.result.connect(self._on_adopt_done)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_adopt_done(self, data: dict) -> None:
        content = data.get("content", "") or ""
        self._original_edit.setPlainText(content)
        self._adopt_btn.setEnabled(False)
        self._rollback_btn.setEnabled(True)
        self._status_label.setText("已采纳改写，章节正文已更新")
        QMessageBox.information(self, "采纳成功", "章节正文已更新为改写内容")

    def _do_rollback(self) -> None:
        if not self._current_rewrite_id:
            QMessageBox.warning(self, "提示", "没有可回退的改写")
            return
        reply = QMessageBox.question(
            self,
            "确认回退",
            "回退后章节正文将恢复为改写前的原文，确定回退？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.post, f"/api/anti-ai/{self._current_rewrite_id}/rollback"
        )
        worker.result.connect(self._on_rollback_done)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_rollback_done(self, data: dict) -> None:
        self._rollback_btn.setEnabled(False)
        self._adopt_btn.setEnabled(False)
        self._status_label.setText("已回退至原文")
        if self._current_chapter_id:
            client = get_api_client()
            worker = ApiWorker(
                client.get, f"/api/chapters/{self._current_chapter_id}/content"
            )
            worker.result.connect(self._on_content_loaded)
            worker.error.connect(self._on_error)
            self._workers.append(worker)
            worker.start()
        QMessageBox.information(self, "回退成功", "章节正文已恢复为原文")

    def _load_history(self) -> None:
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择章节")
            return
        client = get_api_client()
        worker = ApiWorker(
            client.get, f"/api/anti-ai/history/{self._current_chapter_id}"
        )
        worker.result.connect(self._on_history_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_history_loaded(self, data: dict) -> None:
        rewrites = data.get("rewrites", []) or []
        if not rewrites:
            QMessageBox.information(self, "提示", "该章节暂无改写历史")
            return
        latest = rewrites[0]
        self._current_rewrite_id = latest.get("rewrite_id")
        self._rewritten_edit.setPlainText(latest.get("rewritten_content", ""))
        adopt_status = latest.get("adopt_status", "待采纳")
        self._adopt_btn.setEnabled(adopt_status == "待采纳")
        self._rollback_btn.setEnabled(adopt_status == "已采纳")
        self._status_label.setText(
            f"已加载最新改写记录（共 {len(rewrites)} 条），状态：{adopt_status}"
        )

    def _on_error(self, msg: str) -> None:
        self._status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)