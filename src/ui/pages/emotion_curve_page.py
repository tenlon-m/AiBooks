"""情感曲线分析页 - 范围选择 + SSE生成 + 进度显示 + EmotionChartWidget 展示结果."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context
from src.ui.sse_worker import SsePostWorker
from src.ui.widgets.emotion_chart_widget import EmotionChartWidget
from src.ui.theme.theme_qss_builder import apply_theme_variant


class EmotionCurvePage(QWidget):
    emotion_generated = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._sse_worker: SsePostWorker | None = None
        self._has_unsaved_changes: bool = False
        # 一次生成任务的运行时状态
        self._total_chapters: int = 0
        self._done_chapters: int = 0
        self._collected_points: list[dict] = []
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
        if self._sse_worker is not None:
            try:
                self._sse_worker.stop()
            except Exception:
                pass
            self._sse_worker = None
        self.chart_widget.draw_empty()
        self.status_label.setText("就绪")
        self.progress_bar.setValue(0)
        self._progress_label.setText("")
        self._ideas_input.clear()
        self._has_unsaved_changes = False
        self._total_chapters = 0
        self._done_chapters = 0
        self._collected_points = []

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _mark_unsaved(self) -> None:
        self._has_unsaved_changes = True

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self._ideas_input.clear()
        if project_id:
            self._load_existing_curve()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("情感曲线分析")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        ideas_label = QLabel("情感曲线思路与想法（可选）：在此输入你对情感节奏的思路和想法")
        ideas_label.setProperty("role", "secondary")
        ideas_label.setStyleSheet("padding: 4px 8px;")
        layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText("例如：第一卷节奏舒缓，第二卷高潮迭起，第三卷收束平稳……")
        self._ideas_input.setMaximumHeight(80)
        self._ideas_input.setStyleSheet("padding: 4px;")
        layout.addWidget(self._ideas_input)

        self.status_label = QLabel("就绪")
        self.status_label.setProperty("role", "secondary")
        self.status_label.setStyleSheet("padding: 4px;")
        layout.addWidget(self.status_label)

        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("分析范围："))
        self._range_combo = QComboBox()
        self._range_combo.addItem("全书", "all")
        self._range_combo.addItem("指定章节", "range")
        self._range_combo.currentIndexChanged.connect(self._on_range_changed)
        range_layout.addWidget(self._range_combo)
        range_layout.addWidget(QLabel("起始章："))
        self._start_spin = QSpinBox()
        self._start_spin.setMinimum(1)
        self._start_spin.setMaximum(999)
        self._start_spin.setEnabled(False)
        range_layout.addWidget(self._start_spin)
        range_layout.addWidget(QLabel("结束章："))
        self._end_spin = QSpinBox()
        self._end_spin.setMinimum(1)
        self._end_spin.setMaximum(999)
        self._end_spin.setEnabled(False)
        range_layout.addWidget(self._end_spin)
        range_layout.addStretch()
        layout.addLayout(range_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        layout.addWidget(QLabel("情感曲线图："))
        self.chart_widget = EmotionChartWidget()
        self.chart_widget.draw_empty()
        layout.addWidget(self.chart_widget, 1)

        btn_layout = QHBoxLayout()
        self.generate_btn = QPushButton("生成情感曲线")
        apply_theme_variant(self.generate_btn, "success")
        self.generate_btn.clicked.connect(self._generate_curve)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._load_existing_curve)
        btn_layout.addWidget(self.generate_btn)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._progress_label = QLabel("")
        self._progress_label.setProperty("role", "secondary")
        self._progress_label.setStyleSheet("padding: 2px;")
        layout.addWidget(self._progress_label)

    def _on_range_changed(self, _idx: int) -> None:
        is_range = self._range_combo.currentData() == "range"
        self._start_spin.setEnabled(is_range)
        self._end_spin.setEnabled(is_range)

    def _get_project_id(self) -> str | None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return None
        return ctx.project_id

    def _load_existing_curve(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/emotion/{pid}/curve")
        worker.result.connect(self._on_curve_loaded)
        worker.error.connect(self._on_curve_error)
        self._add_worker(worker)
        worker.start()

    def _on_curve_error(self, msg: str) -> None:
        """加载/生成失败时不再静默吞异常，给出可见提示."""
        self.chart_widget.draw_empty()
        self.status_label.setText(f"加载失败：{msg}")

    def _render_points(self, points: list[dict], status_prefix: str = "已加载情感曲线") -> None:
        """把后端 EmotionCurvePointDto 列表渲染成折线图.

        后端 tension / emotion_fluctuation 取值 0.0-1.0，图表按 0-100 展示。
        """
        if not points:
            self.chart_widget.draw_empty()
            return
        ordered = sorted(points, key=lambda p: p.get("chapter_no", 0) or 0)
        labels = [f"第{p.get('chapter_no', i + 1)}章" for i, p in enumerate(ordered)]
        tension = [float(p.get("tension", 0.0)) * 100 for p in ordered]
        fluctuation = [float(p.get("emotion_fluctuation", 0.0)) * 100 for p in ordered]
        self.chart_widget.draw_emotion_curve(labels, tension, fluctuation)
        self.status_label.setText(f"{status_prefix}，共 {len(ordered)} 章")

    def _on_curve_loaded(self, data: dict) -> None:
        # 后端返回结构：{"project_id": ..., "points": [{chapter_no, tension, emotion_fluctuation, ...}]}
        points = data.get("points", []) if isinstance(data, dict) else []
        if not points:
            self.chart_widget.draw_empty()
            self.status_label.setText("暂无情感曲线数据，请点击「生成情感曲线」")
            return
        self._render_points(points)

    def _generate_curve(self) -> None:
        """生成情感曲线.

        后端 EmotionAnalyzeRequest 只接受 {project_id, chapter_ids}，不支持 range 参数，
        因此先拉取章节列表，在客户端按所选范围解析出 chapter_ids 再发起 SSE 分析。
        """
        pid = self._get_project_id()
        if not pid:
            return
        self.generate_btn.setEnabled(False)
        self.status_label.setText("正在读取章节列表...")
        self.progress_bar.setValue(0)
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/writing/{pid}/chapters")
        worker.result.connect(self._on_chapters_loaded)
        worker.error.connect(self._on_sse_error)
        self._add_worker(worker)
        worker.start()

    def _on_chapters_loaded(self, data: list | dict) -> None:
        """按所选范围解析出待分析章节ID，然后发起情感分析 SSE."""
        pid = self._get_project_id()
        if not pid:
            self.generate_btn.setEnabled(True)
            return
        chapters = data if isinstance(data, list) else data.get("chapters", [])
        if not chapters:
            self.generate_btn.setEnabled(True)
            self.status_label.setText("暂无章节，请先生成大纲并撰写正文")
            QMessageBox.warning(self, "提示", "当前项目没有章节，请先完成大纲与撰写")
            return

        range_type = self._range_combo.currentData()
        if range_type == "range":
            start = self._start_spin.value()
            end = self._end_spin.value()
            if start > end:
                start, end = end, start
            selected = [
                c for c in chapters
                if start <= int(c.get("chapter_no", 0) or 0) <= end
            ]
        else:
            selected = list(chapters)

        # 只有已完成且有正文的章节才能分析（内容不足时 service 会抛 ValueError）
        selected = [
            c for c in selected
            if c.get("gen_status") == "completed" and (c.get("content") or "").strip()
        ]
        chapter_ids = [c.get("chapter_id") for c in selected if c.get("chapter_id")]
        if not chapter_ids:
            self.generate_btn.setEnabled(True)
            self.status_label.setText("所选范围内没有已完成的章节")
            QMessageBox.warning(
                self, "提示",
                "所选范围内没有「已完成且有正文」的章节，请调整范围或先完成撰写。",
            )
            return

        self._total_chapters = len(chapter_ids)
        self._done_chapters = 0
        self._collected_points: list[dict] = []
        self.status_label.setText(f"生成中（共 {self._total_chapters} 章）...")
        self._progress_label.setText(f"分析中：0/{self._total_chapters} 章")
        self._sse_worker = SsePostWorker(
            "/api/emotion/analyze/stream",
            payload={"project_id": pid, "chapter_ids": chapter_ids},
        )
        self._sse_worker.event.connect(self._on_sse_event)
        self._sse_worker.error.connect(self._on_sse_error)
        self._sse_worker.finished_ok.connect(self._on_sse_finished)
        self._sse_worker.start()

    def _on_sse_event(self, data: dict) -> None:
        # 后端 EmotionStreamChunk 字段：type(progress|chunk|done) / chapter_id / point / message
        msg_type = data.get("type", "")
        message = data.get("message", "")
        point = data.get("point")

        if msg_type == "progress":
            self._progress_label.setText(message or "分析中...")
            return

        if msg_type == "chunk":
            if isinstance(point, dict):
                self._collected_points.append(point)
            self._done_chapters += 1
            if self._total_chapters > 0:
                self.progress_bar.setValue(
                    int(self._done_chapters / self._total_chapters * 100)
                )
            self._progress_label.setText(
                f"分析中：{self._done_chapters}/{self._total_chapters} 章"
            )
            # 实时增量绘图，避免用户长时间看不到反馈
            if self._collected_points:
                self._render_points(self._collected_points, "分析进行中")
            return

        if msg_type == "done":
            # 后端在章节内容不足 / AI 异常时也会以 type=done + message 结束单章
            if message:
                self._progress_label.setText(message)
            return

        if message:
            self._progress_label.setText(message)

    def _on_sse_error(self, msg: str) -> None:
        self.generate_btn.setEnabled(True)
        self.status_label.setText(f"错误：{msg}")
        self._progress_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)

    def _on_sse_finished(self) -> None:
        self.generate_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        if self._collected_points:
            self._render_points(self._collected_points, "情感曲线生成完成")
            self._progress_label.setText("完成")
        else:
            self._progress_label.setText("")
            self.status_label.setText("未生成任何数据，请检查章节正文是否充足")
        self._sse_worker = None
        self.emotion_generated.emit()
        # 生成结果已即时落库，这里重新拉取一次保证与后端一致
        self._load_existing_curve()