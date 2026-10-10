"""AI写剧本页 - 基于大纲一键生成分集剧本、查看与导出."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context
from src.ui.sse_worker import SsePostWorker


class ScriptPage(QWidget):
    """AI写剧本页面."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._sse_worker: SsePostWorker | None = None
        self._project_id: str | None = None
        self._episodes: list[dict] = []
        self._init_ui()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QLabel("AI写剧本")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(header)

        self._status_label = QLabel("请先选择项目并确保大纲已生成")
        self._status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self._status_label)

        btn_layout = QHBoxLayout()
        self._generate_btn = QPushButton("一键转剧本")
        self._generate_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._generate_btn.clicked.connect(self._on_generate)
        self._export_btn = QPushButton("导出剧本")
        self._export_btn.setStyleSheet(
            "background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._export_btn.clicked.connect(self._on_export)
        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self._load_episodes)
        btn_layout.addWidget(self._generate_btn)
        btn_layout.addWidget(self._export_btn)
        btn_layout.addWidget(self._refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._progress_label = QLabel()
        self._progress_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._progress_label)

        split_layout = QHBoxLayout()

        self._episode_list = QListWidget()
        self._episode_list.setMinimumWidth(200)
        self._episode_list.currentRowChanged.connect(self._on_episode_selected)
        split_layout.addWidget(self._episode_list)

        self._content_view = QTextEdit()
        self._content_view.setReadOnly(True)
        self._content_view.setPlaceholderText("选择左侧分集查看场景描述与角色对白")
        split_layout.addWidget(self._content_view)

        layout.addLayout(split_layout, 1)

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self._project_id = project_id
        self._load_episodes()

    def _load_episodes(self) -> None:
        if not self._project_id:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/script/episodes/{self._project_id}")
        worker.result.connect(self._on_load_done)
        worker.error.connect(self._on_load_error)
        self._workers.append(worker)
        worker.start()

    def _on_load_done(self, data: list | dict) -> None:
        self._episode_list.clear()
        self._content_view.clear()
        episodes = data if isinstance(data, list) else []
        self._episodes = episodes
        for ep in episodes:
            item = QListWidgetItem(f"第{ep['episode_no']}集")
            item.setData(Qt.UserRole, ep)
            self._episode_list.addItem(item)
        if episodes:
            self._status_label.setText(f"共 {len(episodes)} 集剧本")
        else:
            self._status_label.setText("暂无剧本，可点击一键转剧本生成")

    def _on_load_error(self, msg: str) -> None:
        self._status_label.setText(f"加载剧本失败: {msg}")

    def _on_episode_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._episodes):
            return
        ep = self._episodes[row]
        text = (
            f"第{ep['episode_no']}集\n\n"
            f"【场景描述】\n{ep.get('scene_description', '')}\n\n"
            f"【角色对白】\n{ep.get('character_dialogue', '')}"
        )
        self._content_view.setPlainText(text)

    def _on_generate(self) -> None:
        if not self._project_id:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        reply = QMessageBox.question(
            self,
            "确认",
            "将根据大纲生成分集剧本，已有剧本将被覆盖，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._generate_btn.setEnabled(False)
        self._progress_label.setText("正在生成分集剧本...")
        self._episode_list.clear()
        self._content_view.clear()
        self._episodes = []
        self._sse_worker = SsePostWorker(
            "/api/script/generate",
            payload={"project_id": self._project_id},
        )
        self._sse_worker.event.connect(self._on_sse_event)
        self._sse_worker.error.connect(self._on_sse_error)
        self._sse_worker.finished_ok.connect(self._on_sse_done)
        self._sse_worker.start()

    def _on_sse_event(self, data: dict) -> None:
        event_type = data.get("type", "")
        message = data.get("message", "")
        progress = data.get("progress")
        if message:
            self._progress_label.setText(message)
        if progress is not None:
            self._progress_label.setText(f"{self._progress_label.text()} ({progress}%)")
        if event_type == "episode_done":
            episode_no = data.get("episode_no", 0)
            scene = data.get("scene_description", "")
            dialogue = data.get("character_dialogue", "")
            ep = {
                "episode_no": episode_no,
                "scene_description": scene,
                "character_dialogue": dialogue,
            }
            self._episodes.append(ep)
            item = QListWidgetItem(f"第{episode_no}集")
            item.setData(Qt.UserRole, ep)
            self._episode_list.addItem(item)
            self._episode_list.setCurrentRow(self._episode_list.count() - 1)
        elif event_type == "completed":
            self._progress_label.setText("分集剧本生成完成")
        elif event_type == "error":
            self._progress_label.setText(f"生成失败: {message}")
            QMessageBox.warning(self, "生成失败", message or "未知错误")

    def _on_sse_error(self, msg: str) -> None:
        self._generate_btn.setEnabled(True)
        self._progress_label.setText(f"SSE异常: {msg}")
        QMessageBox.warning(self, "生成失败", msg)

    def _on_sse_done(self) -> None:
        self._generate_btn.setEnabled(True)
        self._load_episodes()

    def _on_export(self) -> None:
        if not self._project_id:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        if not self._episodes:
            QMessageBox.warning(self, "提示", "暂无剧本，请先生成")
            return
        target_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not target_dir:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            "/api/script/export",
            json={
                "project_id": self._project_id,
                "target_dir": target_dir,
                "format": "txt",
            },
        )
        worker.result.connect(self._on_export_done)
        worker.error.connect(self._on_export_error)
        self._workers.append(worker)
        worker.start()

    def _on_export_done(self, data: dict) -> None:
        file_path = data.get("file_path", "")
        count = data.get("episode_count", 0)
        QMessageBox.information(self, "导出成功", f"已导出 {count} 集剧本至:\n{file_path}")

    def _on_export_error(self, msg: str) -> None:
        QMessageBox.warning(self, "导出失败", msg)