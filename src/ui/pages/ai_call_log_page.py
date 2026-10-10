"""AI调用日志页 - 查看AI调用记录列表与详情."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
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

SCENE_LABELS: dict[str, str] = {
    "scene-split": "场景细化",
    "chapter": "章节摘要",
    "write-chapter": "撰写章节",
    "check-consistency": "一致性校验",
    "polish-synopsis": "润色梗概",
    "polish-worldview": "润色世界观",
    "generate-outline": "生成大纲",
    "generate-outline-batch": "分批生成大纲",
    "generate": "命名生成",
    "design-cool-points": "设计爽点",
    "design-hooks": "设计钩子",
    "generate-chapter": "生成章节",
    "chat": "对话",
    "extract-main": "提取主角",
    "extract-supporting": "提取配角",
    "generate-supporting": "生成配角",
    "import-from-file": "从文件导入",
    "full-book": "全书校验",
    "single-chapter": "单章润色",
    "auto-polish": "自动润色",
    "merge-title": "合并标题",
    "analyze": "情绪分析",
    "connection": "人物关系",
    "extract-features": "提取风格特征",
    "extract-items": "提取物品",
    "auto-generate-supporting": "自动生成配角",
}


class AiCallLogPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._init_ui()
        self._load_logs()
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
        self.table.setRowCount(0)
        self.detail_edit.clear()
        self.status_label.clear()

    def has_unsaved_changes(self) -> bool:
        return False

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        if project_id:
            self._load_logs()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("AI调用日志")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._load_logs)
        self.view_btn = QPushButton("查看详情")
        self.view_btn.clicked.connect(self._view_detail)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.view_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["日志ID", "场景", "模型", "AI源", "耗时(ms)", "状态", "调用时间"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setMinimumSectionSize(80)
        for i, w in enumerate([100, 120, 140, 100, 90, 80, 160]):
            self.table.setColumnWidth(i, w)
        layout.addWidget(self.table, 1)

        layout.addWidget(QLabel("调用详情："))
        self.detail_edit = QTextEdit()
        self.detail_edit.setReadOnly(True)
        layout.addWidget(self.detail_edit, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

    def _load_logs(self) -> None:
        client = get_api_client()
        ctx = get_project_context()
        path = "/api/ai_logs/logs?limit=200"
        if ctx.has_project():
            path += f"&project_id={ctx.project_id}"
        worker = ApiWorker(client.get, path)
        worker.result.connect(self._on_logs_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_logs_loaded(self, logs: list) -> None:
        self.table.setRowCount(0)
        for l in logs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            # 展示用短ID，完整 log_id 挂在首列 UserRole 供「查看详情」直接命中
            id_item = QTableWidgetItem(l.get("log_id", "")[:8])
            id_item.setData(Qt.ItemDataRole.UserRole, l.get("log_id", ""))
            self.table.setItem(row, 0, id_item)
            scene_raw = l.get("scene", "") or ""
            scene_display = SCENE_LABELS.get(scene_raw, scene_raw)
            scene_item = QTableWidgetItem(scene_display)
            scene_item.setToolTip(scene_display)
            self.table.setItem(row, 1, scene_item)
            self.table.setItem(row, 2, QTableWidgetItem(l.get("model_name", "") or ""))
            self.table.setItem(row, 3, QTableWidgetItem(l.get("source_name", "") or ""))
            self.table.setItem(row, 4, QTableWidgetItem(str(l.get("duration_ms", 0))))
            self.table.setItem(row, 5, QTableWidgetItem(l.get("status", "")))
            self.table.setItem(row, 6, QTableWidgetItem(str(l.get("called_at", ""))))
        self.status_label.setText(f"共 {len(logs)} 条记录")

    def _view_detail(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请选择一行")
            return
        item = self.table.item(row, 0)
        log_id = item.data(Qt.ItemDataRole.UserRole) if item else ""
        if not log_id:
            QMessageBox.warning(self, "提示", "未获取到日志ID，请刷新后重试")
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/ai_logs/logs/{log_id}")
        worker.result.connect(self._on_detail_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_detail_loaded(self, data: dict) -> None:
        if not data:
            self.detail_edit.setPlainText("未获取到日志详情")
            return
        scene_raw = data.get('scene', '') or ""
        scene_display = SCENE_LABELS.get(scene_raw, scene_raw)
        lines = [
            f"场景：{scene_display}",
            f"模型：{data.get('model_name', '')}",
            f"AI源：{data.get('source_name', '')}",
            f"耗时：{data.get('duration_ms', 0)}ms",
            f"状态：{data.get('status', '')}",
            f"调用时间：{data.get('called_at', '')}",
            "",
            "=== 提示词 ===",
            data.get("prompt", "")[:2000],
            "",
            "=== 响应 ===",
            data.get("response", "")[:2000],
        ]
        self.detail_edit.setPlainText("\n".join(lines))

    def _on_error(self, msg: str) -> None:
        self.status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)