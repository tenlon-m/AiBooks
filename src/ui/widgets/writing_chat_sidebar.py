"""AI对话式写作辅助侧栏 - 对话历史+输入+四类快捷操作+SSE流式接收."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (

    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.sse_worker import SsePostWorker
from src.utils.logger import get_logger


# 前端上下文模式 -> 后端 WritingChatRequest.context_mode（Literal["selected","full"]）
CONTEXT_MODE_MAP = {
    "paragraph": "selected",
    "selected": "selected",
    "whole_chapter": "full",
    "full": "full",
}


class WritingChatSidebar(QWidget):
    """AI对话式写作辅助侧栏.

    通过 SSE POST /api/writing-chat/chat/stream 与后端交互。

    信号:
        message_received(str): SSE chunk 累积完成后，向主线程通知最新一条消息文本
    """

    message_received = Signal(str)

    def __init__(self, project_id: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI写作对话")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self._workers: list[ApiWorker] = []
        self._sse_worker: SsePostWorker | None = None
        self._project_id = project_id
        self._chapter_id: str | None = None
        self._selected_text: str = ""
        self._context_mode: str = "paragraph"
        self._accumulated_chunk: str = ""
        self._init_ui()
        self.setMinimumWidth(360)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self._context_label = QLabel("上下文：未选择")
        self._context_label.setStyleSheet(
            "color: #666; padding: 4px; background-color: #f0f4c3; border-radius: 4px;"
        )
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        action_layout = QHBoxLayout()
        self._rewrite_btn = QPushButton("改写")
        self._rewrite_btn.setToolTip("对选中段落进行改写")
        self._rewrite_btn.clicked.connect(lambda: self._send_quick("rewrite"))
        self._suggest_btn = QPushButton("建议")
        self._suggest_btn.setToolTip("请AI给出写作建议")
        self._suggest_btn.clicked.connect(lambda: self._send_quick("suggest"))
        self._discuss_btn = QPushButton("讨论")
        self._discuss_btn.setToolTip("与AI讨论当前段落")
        self._discuss_btn.clicked.connect(lambda: self._send_quick("discuss"))
        self._plot_btn = QPushButton("剧情走向")
        self._plot_btn.setToolTip("探讨后续剧情走向")
        self._plot_btn.clicked.connect(lambda: self._send_quick("plot_direction"))
        for btn in (self._rewrite_btn, self._suggest_btn, self._discuss_btn, self._plot_btn):
            btn.setStyleSheet(
                "background-color: #00838f; color: white; padding: 4px 10px; border-radius: 3px;"
            )
            action_layout.addWidget(btn)
        action_layout.addStretch()
        layout.addLayout(action_layout)

        layout.addWidget(QLabel("对话历史："))
        self._history_list = QListWidget()
        self._history_list.setMaximumHeight(120)
        self._history_list.itemClicked.connect(self._on_history_item_clicked)
        layout.addWidget(self._history_list)

        layout.addWidget(QLabel("对话内容："))
        self._chat_view = QTextBrowser()
        self._chat_view.setOpenExternalLinks(True)
        layout.addWidget(self._chat_view, 1)

        layout.addWidget(QLabel("输入消息："))
        self._input_edit = QPlainTextEdit()
        self._input_edit.setMaximumHeight(80)
        self._input_edit.setPlaceholderText("输入你的问题或指令，按发送与AI对话……")
        layout.addWidget(self._input_edit)

        btn_layout = QHBoxLayout()
        self._send_btn = QPushButton("发送")
        self._send_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._send_btn.clicked.connect(self._send_input)
        self._clear_btn = QPushButton("清空对话")
        self._clear_btn.clicked.connect(self._clear_chat)
        self._stop_btn = QPushButton("停止")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet(
            "background-color: #f44336; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._stop_btn.clicked.connect(self._stop_sse)
        btn_layout.addWidget(self._send_btn)
        btn_layout.addWidget(self._stop_btn)
        btn_layout.addWidget(self._clear_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._status_label)


    def set_chapter_context(
        self,
        chapter_id: str | None,
        selected_text: str = "",
        context_mode: str = "paragraph",
    ) -> None:
        """设置当前对话上下文：章节ID、选中文本、上下文模式."""
        self._chapter_id = chapter_id
        self._selected_text = selected_text
        self._context_mode = context_mode
        if not chapter_id:
            self._context_label.setText("上下文：未选择章节")
        elif context_mode == "whole_chapter":
            self._context_label.setText("上下文：整章模式")
        elif selected_text:
            preview = selected_text[:40].replace("\n", " ")
            self._context_label.setText(f"上下文：选中段落「{preview}……」")
        else:
            self._context_label.setText("上下文：未选中段落（整章模式）")
        if chapter_id:
            self._load_history(chapter_id)

    def _load_history(self, chapter_id: str) -> None:
        """加载指定章节的对话历史."""
        client = get_api_client()
        worker = ApiWorker(
            client.get, f"/api/writing-chat/{chapter_id}/history"
        )
        worker.result.connect(self._on_history_loaded)
        worker.error.connect(self._on_history_error)
        self._workers.append(worker)
        worker.start()

    def _on_history_error(self, msg: str) -> None:
        """对话历史加载失败：此前是 ``lambda _: None`` 静默吞掉，界面毫无提示."""
        get_logger().warning(f"AI对话历史加载失败：{msg}")
        self._status_label.setText(f"对话历史加载失败：{msg}")
        self._status_label.setStyleSheet("color: #c62828; padding: 2px;")
        self._history_list.clear()
        self._history_list.addItem("（历史加载失败，不影响本次对话）")

    def _on_history_loaded(self, data: dict | list) -> None:
        """历史加载完成，填充历史列表与对话视图."""
        messages = data if isinstance(data, list) else data.get("messages", [])
        self._history_list.clear()
        self._chat_view.clear()
        self._status_label.setText("就绪")
        self._status_label.setStyleSheet("color: #666; padding: 2px;")
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            self._append_message(role, content)
            item = QListWidgetItem(
                f"[{role}] {content[:30]}……" if len(content) > 30 else f"[{role}] {content}"
            )
            item.setData(Qt.ItemDataRole.UserRole, msg)
            self._history_list.addItem(item)

    def _on_history_item_clicked(self, item: QListWidgetItem) -> None:
        msg = item.data(Qt.ItemDataRole.UserRole)
        if not msg:
            return
        content = msg.get("content", "")
        QMessageBox.information(self, "对话详情", content)

    def _append_message(self, role: str, content: str) -> None:
        """向对话视图追加一条消息."""
        if role == "user":
            color = "#1565c0"
            label = "我"
        else:
            color = "#2e7d32"
            label = "AI"
        cursor = self._chat_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._chat_view.setTextCursor(cursor)
        self._chat_view.append(
            f'<p style="color:{color};font-weight:bold;">{label}：</p>'
            f'<p style="color:#333;">{content}</p>'
        )

    def _send_input(self) -> None:
        text = self._input_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        self._send_message(text, action_type="chat")

    def _send_quick(self, action_type: str) -> None:
        """快捷操作按钮：改写/建议/讨论/剧情走向."""
        if not self._chapter_id:
            QMessageBox.warning(self, "提示", "请先选中段落或切换整章模式")
            return
        preset_messages = {
            "rewrite": "请改写以下段落，使其更生动：",
            "suggest": "请对以下段落给出写作建议：",
            "discuss": "我想讨论以下段落的处理方式：",
            "plot_direction": "请基于当前段落分析后续剧情走向：",
        }
        prefix = preset_messages.get(action_type, "")
        selected = self._selected_text or ""
        if action_type == "rewrite" and not selected:
            QMessageBox.warning(self, "提示", "改写需要先选中段落")
            return
        message = prefix + ("\n" + selected if selected else "")
        self._send_message(message, action_type=action_type)

    def set_project_id(self, project_id: str) -> None:
        """注入当前项目ID（切换项目后需重新注入）."""
        self._project_id = project_id

    def _send_message(self, message: str, action_type: str = "chat") -> None:
        """发送消息到后端 SSE 端点并流式接收回复."""
        if not self._chapter_id:
            QMessageBox.warning(self, "提示", "请先选中段落或切换整章模式")
            return
        if not self._project_id:
            QMessageBox.warning(self, "提示", "未获取到项目信息，请先打开或创建项目")
            return
        self._append_message("user", message)
        self._input_edit.clear()
        self._status_label.setText("AI回复中...")
        self._send_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._accumulated_chunk = ""
        # 后端 WritingChatRequest 无 action_type / selected_text 字段：
        # 把选中段落作为补充上下文并入 user_ideas，避免信息丢失。
        user_ideas = ""
        if self._selected_text:
            user_ideas = f"参考段落：\n{self._selected_text}"
        payload = {
            "project_id": self._project_id,
            "chapter_id": self._chapter_id,
            "message": message,
            "context_mode": CONTEXT_MODE_MAP.get(self._context_mode, "selected"),
            "user_ideas": user_ideas,
        }
        self._sse_worker = SsePostWorker(
            "/api/writing-chat/chat/stream",
            payload=payload,
        )
        self._sse_worker.chunk.connect(self._on_chunk)
        self._sse_worker.event.connect(self._on_event)
        self._sse_worker.error.connect(self._on_sse_error)
        self._sse_worker.finished_ok.connect(self._on_sse_finished)
        self._sse_worker.start()

    def _on_chunk(self, chunk: str) -> None:
        self._accumulated_chunk += chunk
        self._chat_view.moveCursor(QTextCursor.MoveOperation.End)
        self._chat_view.insertPlainText(chunk)
        self._chat_view.ensureCursorVisible()

    def _on_event(self, data: dict) -> None:
        # 后端 WritingChatStreamChunk 字段：type / content / suggestion / message
        msg_type = data.get("type", "")
        message = data.get("message", "")
        if message:
            self._status_label.setText(f"状态：{message}")
        elif msg_type:
            self._status_label.setText(f"状态：{msg_type}")

    def _on_sse_error(self, msg: str) -> None:
        self._status_label.setText(f"错误：{msg}")
        self._send_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        QMessageBox.critical(self, "对话错误", msg)

    def _on_sse_finished(self) -> None:
        self._send_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_label.setText("回复完成")
        if self._accumulated_chunk:
            self.message_received.emit(self._accumulated_chunk)
            self._chat_view.append("")
        if self._chapter_id:
            self._load_history(self._chapter_id)

    def _stop_sse(self) -> None:
        if self._sse_worker:
            self._sse_worker.stop()
        self._send_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_label.setText("已停止")

    def _clear_chat(self) -> None:
        self._chat_view.clear()
        self._accumulated_chunk = ""
        self._status_label.setText("已清空对话")

    def clear(self) -> None:
        """清空侧栏状态（项目切换时调用）."""
        if self._sse_worker:
            try:
                self._sse_worker.stop()
            except Exception:
                pass
            self._sse_worker = None
        self._chapter_id = None
        self._selected_text = ""
        self._chat_view.clear()
        self._history_list.clear()
        self._input_edit.clear()
        self._accumulated_chunk = ""
        self._context_label.setText("上下文：未选择")
        self._status_label.setText("就绪")
        self._send_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)