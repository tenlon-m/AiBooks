"""章节衔接优化对话框 - SSE 分析相邻两章的衔接并生成过渡段（后端已实现，此前无UI入口）."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


from src.ui.sse_worker import SsePostWorker


class ConnectionDialog(QDialog):
    """分析「前一章结尾」与「后一章开头」的衔接，输出评分、问题清单与过渡段。

    信号:
        transition_generated(str): 生成完成，携带过渡段文本（供插入到后一章开头）
    """

    transition_generated = Signal(str)

    def __init__(
        self,
        project_id: str,
        chapters: list[dict],
        prev_chapter_id: str = "",
        next_chapter_id: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_id = project_id
        self._chapters = sorted(
            chapters or [],
            key=lambda c: (int(c.get("volume_no", 0) or 0), int(c.get("chapter_no", 0) or 0)),
        )
        self._prev_chapter_id = prev_chapter_id
        self._next_chapter_id = next_chapter_id
        self._sse_worker: SsePostWorker | None = None
        self._accumulated: str = ""
        self.setWindowTitle("章节衔接优化")
        self.setMinimumSize(680, 520)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        tip = QLabel(
            "选择相邻的两章，AI 会比对前一章结尾与后一章开头，"
            "给出衔接评分、问题清单，并生成一段可直接使用的过渡段。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #555; padding: 4px;")
        layout.addWidget(tip)

        sel_layout = QHBoxLayout()
        sel_layout.addWidget(QLabel("前一章："))
        self._prev_combo = QComboBox()
        sel_layout.addWidget(self._prev_combo, 1)
        sel_layout.addWidget(QLabel("后一章："))
        self._next_combo = QComboBox()
        sel_layout.addWidget(self._next_combo, 1)
        layout.addLayout(sel_layout)

        for combo in (self._prev_combo, self._next_combo):
            for c in self._chapters:
                combo.addItem(
                    f"第{c.get('volume_no')}卷第{c.get('chapter_no')}章 {c.get('title', '')}",
                    c.get("chapter_id", ""),
                )

        self._preselect(self._prev_combo, self._prev_chapter_id)
        self._preselect(self._next_combo, self._next_chapter_id)
        # 未指定时默认选中「前一章 + 它的下一章」
        if self._prev_combo.currentIndex() < 0 and self._prev_combo.count() > 0:
            self._prev_combo.setCurrentIndex(0)
        if self._next_combo.currentIndex() < 0 and self._next_combo.count() > 1:
            self._next_combo.setCurrentIndex(min(1, self._next_combo.count() - 1))
        self._prev_combo.currentIndexChanged.connect(self._sync_next_to_prev)
        self._sync_next_to_prev()

        ideas_label = QLabel("补充说明（可选）：")
        ideas_label.setStyleSheet("color: #555; padding: 4px 0 0 0;")
        layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText("例如：希望过渡段承接上一章的紧张氛围，并点出主角的心理变化……")
        self._ideas_input.setMaximumHeight(70)
        layout.addWidget(self._ideas_input)

        btn_layout = QHBoxLayout()
        self._analyze_btn = QPushButton("开始分析")
        self._analyze_btn.setStyleSheet(
            "background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._analyze_btn.clicked.connect(self._start_analyze)
        self._stop_btn = QPushButton("停止")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_analyze)
        self._use_btn = QPushButton("使用过渡段")
        self._use_btn.setEnabled(False)
        self._use_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._use_btn.clicked.connect(self._use_transition)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._analyze_btn)
        btn_layout.addWidget(self._stop_btn)
        btn_layout.addWidget(self._use_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._status_label)

        layout.addWidget(QLabel("过渡段："))
        self._result_edit = QPlainTextEdit()
        self._result_edit.setReadOnly(True)
        self._result_edit.setPlaceholderText("分析结果与过渡段会显示在这里")
        layout.addWidget(self._result_edit, 1)

    # ------------------------------------------------------------------ 内部
    def _preselect(self, combo: QComboBox, chapter_id: str) -> None:
        if not chapter_id:
            return
        for i in range(combo.count()):
            if combo.itemData(i) == chapter_id:
                combo.setCurrentIndex(i)
                return

    def _sync_next_to_prev(self) -> None:
        """切换前一章时，默认把后一章设为它的直接下一章。"""
        idx = self._prev_combo.currentIndex()
        if idx < 0 or self._next_combo.count() == 0:
            return
        if idx + 1 < self._next_combo.count():
            self._next_combo.setCurrentIndex(idx + 1)

    def _start_analyze(self) -> None:
        prev_id = self._prev_combo.currentData()
        next_id = self._next_combo.currentData()
        if not prev_id or not next_id:
            QMessageBox.warning(self, "提示", "请先选择前一章与后一章")
            return
        if prev_id == next_id:
            QMessageBox.warning(self, "提示", "前一章与后一章不能相同")
            return
        if not self._project_id:
            QMessageBox.warning(self, "提示", "未获取到项目信息")
            return

        self._result_edit.clear()
        self._accumulated = ""
        self._analyze_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._use_btn.setEnabled(False)
        self._status_label.setText("分析中...")

        self._sse_worker = SsePostWorker(
            "/api/connection/analyze/stream",
            payload={
                "project_id": self._project_id,
                "prev_chapter_id": prev_id,
                "next_chapter_id": next_id,
                "user_ideas": self._ideas_input.toPlainText().strip(),
            },
        )
        self._sse_worker.event.connect(self._on_event)
        self._sse_worker.error.connect(self._on_error)
        self._sse_worker.finished_ok.connect(self._on_finished)
        self._sse_worker.start()

    def _stop_analyze(self) -> None:
        if self._sse_worker is not None:
            try:
                self._sse_worker.stop()
            except Exception:
                pass
            self._sse_worker = None
        self._analyze_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_label.setText("已停止")

    def _on_event(self, data: dict) -> None:
        # 后端 ConnectionStreamChunk：type(progress/chunk/done) / content / message
        msg_type = data.get("type", "")
        message = data.get("message", "")
        content = data.get("content", "")

        if msg_type == "progress":
            self._status_label.setText(message or "分析中...")
            return

        if content:
            self._accumulated = content
            self._result_edit.setPlainText(content)

        if msg_type == "done":
            self._status_label.setText(message or "分析完成")
            if self._accumulated:
                self._use_btn.setEnabled(True)
            elif message:
                # 后端在章节不存在 / 内容不足 / AI异常时只回 message
                self._result_edit.setPlainText(f"（未生成过渡段）{message}")

    def _on_error(self, msg: str) -> None:
        self._analyze_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "衔接分析失败", msg)

    def _on_finished(self) -> None:
        self._analyze_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._sse_worker = None
        if self._accumulated:
            self._use_btn.setEnabled(True)
            if not self._status_label.text().startswith("衔接分数"):
                self._status_label.setText("分析完成")

    def closeEvent(self, event) -> None:
        self._stop_analyze()
        super().closeEvent(event)

    def _use_transition(self) -> None:
        if not self._accumulated:
            return
        self.transition_generated.emit(self._accumulated)
        self.accept()
