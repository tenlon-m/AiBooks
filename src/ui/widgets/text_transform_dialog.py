"""文本变换结果对话框 - 续写/扩写/缩写SSE结果展示+替换/插入操作."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


from src.ui.sse_worker import SsePostWorker


# 前端语义值 -> 后端 TextTransformRequest 的 scene 枚举（Literal["continue","expand","shrink"]）
# 历史前端用 "condense" 表示缩写，而后端 Literal 只接受 "shrink"，此处做显式映射。
TRANSFORM_SCENE_MAP = {
    "continue": "continue",
    "expand": "expand",
    "condense": "shrink",
    "shrink": "shrink",
}


class TextTransformDialog(QDialog):
    """文本变换（续写/扩写/缩写）流式结果对话框.

    通过 SSE POST /api/text-transform/{scene}/stream 接收结果，
    scene 取值 continue / expand / shrink，
    完成后提供「替换原文」与「插入到原文后」两个操作。

    信号:
        replace_requested(str): 用户选择替换原文，携带生成结果
        insert_requested(str): 用户选择插入到原文后，携带生成结果
    """

    replace_requested = Signal(str)
    insert_requested = Signal(str)

    def __init__(
        self,
        project_id: str,
        chapter_id: str,
        original_text: str,
        transform_type: str,
        parent: QWidget | None = None,
        direction: str = "",
        target_words: int = 0,
        user_ideas: str = "",
    ) -> None:
        super().__init__(parent)
        self._project_id = project_id
        self._chapter_id = chapter_id
        self._original_text = original_text
        self._transform_type = transform_type
        self._direction = direction
        self._target_words = target_words
        self._user_ideas = user_ideas
        self._sse_worker: SsePostWorker | None = None
        self._accumulated: str = ""
        self.setWindowTitle(f"AI{transform_type}")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self._init_ui()
        self._start_transform()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title_map = {"continue": "续写", "expand": "扩写", "condense": "缩写", "shrink": "缩写"}
        title = QLabel(f"AI{title_map.get(self._transform_type, '变换')}结果")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        layout.addWidget(QLabel("原文："))
        self._original_view = QPlainTextEdit()
        self._original_view.setReadOnly(True)
        self._original_view.setPlainText(self._original_text)
        self._original_view.setMaximumHeight(120)
        layout.addWidget(self._original_view)

        layout.addWidget(QLabel("AI生成结果："))
        self._result_view = QPlainTextEdit()
        self._result_view.setReadOnly(True)
        layout.addWidget(self._result_view, 1)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        layout.addWidget(self._progress_bar)

        self._status_label = QLabel("正在生成...")
        self._status_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._status_label)

        btn_layout = QHBoxLayout()
        self._replace_btn = QPushButton("替换原文")
        self._replace_btn.setStyleSheet(
            "background-color: #ff9800; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._replace_btn.setEnabled(False)
        self._replace_btn.clicked.connect(self._on_replace)
        self._insert_btn = QPushButton("插入到原文后")
        self._insert_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._insert_btn.setEnabled(False)
        self._insert_btn.clicked.connect(self._on_insert)
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(self._replace_btn)
        btn_layout.addWidget(self._insert_btn)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

    def _start_transform(self) -> None:
        scene = TRANSFORM_SCENE_MAP.get(self._transform_type)
        if not scene:
            self._status_label.setText(f"错误：不支持的变换类型 {self._transform_type}")
            self._progress_bar.setRange(0, 1)
            self._progress_bar.setValue(0)
            return
        # 严格对齐后端 TextTransformRequest 字段名
        payload = {
            "project_id": self._project_id,
            "chapter_id": self._chapter_id,
            "content": self._original_text,
            "direction": self._direction,
            "target_words": int(self._target_words or 0),
            "user_ideas": self._user_ideas,
        }
        self._sse_worker = SsePostWorker(
            f"/api/text-transform/{scene}/stream", payload=payload
        )
        self._sse_worker.chunk.connect(self._on_chunk)
        self._sse_worker.event.connect(self._on_event)
        self._sse_worker.error.connect(self._on_error)
        self._sse_worker.finished_ok.connect(self._on_finished)
        self._sse_worker.start()

    def _on_chunk(self, chunk: str) -> None:
        self._accumulated += chunk
        self._result_view.moveCursor(QTextCursor.MoveOperation.End)
        self._result_view.insertPlainText(chunk)
        self._result_view.ensureCursorVisible()

    def _on_event(self, data: dict) -> None:
        progress = data.get("progress")
        if progress is not None:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(int(progress))

    def _on_error(self, msg: str) -> None:
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(0)
        self._status_label.setText(f"错误：{msg}")
        self._cancel_btn.setText("关闭")

    def _on_finished(self) -> None:
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(1)
        self._status_label.setText("生成完成")
        if self._accumulated.strip():
            self._replace_btn.setEnabled(True)
            self._insert_btn.setEnabled(True)

    def _on_replace(self) -> None:
        self.replace_requested.emit(self._accumulated)
        self.accept()

    def _on_insert(self) -> None:
        self.insert_requested.emit(self._accumulated)
        self.accept()

    def _on_cancel(self) -> None:
        if self._sse_worker:
            try:
                self._sse_worker.stop()
            except RuntimeError:
                pass
        self.reject()

    def closeEvent(self, event) -> None:
        if self._sse_worker:
            try:
                self._sse_worker.stop()
            except RuntimeError:
                pass
        super().closeEvent(event)