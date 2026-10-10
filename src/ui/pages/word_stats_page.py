"""字数统计可视化页 - QTabWidget 切换三维度（章节柱状图/卷饼图/趋势线）+ 目标完成度."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context
from src.ui.widgets.word_stats_chart_widget import WordStatsChartWidget
from src.ui.theme.theme_qss_builder import apply_theme_variant


class WordStatsPage(QWidget):
    stats_loaded = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._has_unsaved_changes: bool = False
        self._summary_cache: dict = {}
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
        self._chapter_widget.clear()
        self._volume_widget.clear()
        self._trend_widget.clear()
        self.status_label.clear()
        self._summary_cache = {}

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _mark_unsaved(self) -> None:
        self._has_unsaved_changes = True

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        if project_id:
            self._load_stats()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("字数统计可视化")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        # 本页是纯统计展示（后端 /api/stats 只有 GET，不接受 user_ideas），
        # 此前这里的「思路输入栏」收集了却从未提交任何接口，属于无效控件，已移除。
        hint = QLabel(
            "本页为纯统计展示：章节字数、按卷分布、日均写作量与目标完成度。\n"
            "数据随撰写进度实时变化，点「刷新统计」可重新拉取。"
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "secondary")
        hint.setStyleSheet("padding: 4px 8px;")
        layout.addWidget(hint)

        self.status_label = QLabel("")
        self.status_label.setProperty("role", "secondary")
        self.status_label.setStyleSheet("padding: 4px;")
        layout.addWidget(self.status_label)

        self._tab_widget = QTabWidget()
        self._chapter_widget = WordStatsChartWidget()
        self._volume_widget = WordStatsChartWidget()
        self._trend_widget = WordStatsChartWidget()
        self._tab_widget.addTab(self._chapter_widget, "章节柱状图")
        self._tab_widget.addTab(self._volume_widget, "卷饼图")
        self._tab_widget.addTab(self._trend_widget, "日均趋势线")
        layout.addWidget(self._tab_widget, 1)

        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新统计")
        apply_theme_variant(self.refresh_btn, "info")
        self.refresh_btn.clicked.connect(self._load_stats)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._progress_label = QLabel("")
        self._progress_label.setProperty("role", "secondary")
        self._progress_label.setStyleSheet("padding: 2px;")
        layout.addWidget(self._progress_label)

    def _get_project_id(self) -> str | None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return None
        return ctx.project_id

    def _load_stats(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(self._fetch_stats, client, pid)
        worker.result.connect(self._on_stats_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    @staticmethod
    def _fetch_stats(client, project_id: str) -> dict:
        # 不再吞异常：后端失败时应让 ApiWorker 的 error 信号冒泡到界面，
        # 否则用户只会看到空白图表，以为「还没有数据」。
        result: dict = {"by_chapter": [], "summary": {}}
        raw = client.get(f"/api/stats/{project_id}/by_chapter") or {}
        result["by_chapter"] = [
            {
                "chapter_label": (f"第{s.get('chapter_no', i + 1)}章 {s.get('title', '')}").strip(),
                "word_count": s.get("word_count", 0),
            }
            for i, s in enumerate(raw.get("stats", []))
        ]
        raw = client.get(f"/api/stats/{project_id}/summary") or {}
        target = raw.get("target_completion") or {}
        result["summary"] = {
            "by_volume": [
                {
                    "volume_name": f"第{v.get('volume_no', i + 1)}卷",
                    "word_count": v.get("total_words", 0),
                }
                for i, v in enumerate(raw.get("by_volume", []))
            ],
            "daily_trend": [
                {"date": str(d.get("day", "")), "word_count": d.get("word_count", 0)}
                for d in raw.get("daily_trend", [])
            ],
            "total_words": target.get("actual_total_words", raw.get("total_words", 0)),
            "target_words": target.get("target_total_words", 0),
        }
        return result

    def _on_stats_loaded(self, data: dict) -> None:
        self._summary_cache = data.get("summary", {})
        by_chapter = data.get("by_chapter", [])
        self._render_chapter_bar(by_chapter)
        self._render_volume_pie(self._summary_cache)
        self._render_trend_line(self._summary_cache)
        self._render_target(self._summary_cache)
        total_words = self._summary_cache.get("total_words", 0)
        target_words = self._summary_cache.get("target_words", 0)
        self.status_label.setText(
            f"总字数：{total_words} / 目标：{target_words}"
        )
        self.stats_loaded.emit()

    def _render_chapter_bar(self, by_chapter: list) -> None:
        if not by_chapter:
            self._chapter_widget.draw_chapter_bar([], [], "暂无章节数据")
            return
        labels = [c.get("chapter_label", f"第{i+1}章") for i, c in enumerate(by_chapter)]
        values = [c.get("word_count", 0) for c in by_chapter]
        self._chapter_widget.draw_chapter_bar(labels, values)

    def _render_volume_pie(self, summary: dict) -> None:
        volumes = summary.get("by_volume", [])
        if not volumes:
            self._volume_widget.draw_volume_pie([], [], "暂无卷数据")
            return
        labels = [v.get("volume_name", f"第{i+1}卷") for i, v in enumerate(volumes)]
        values = [v.get("word_count", 0) for v in volumes]
        self._volume_widget.draw_volume_pie(labels, values)

    def _render_trend_line(self, summary: dict) -> None:
        daily = summary.get("daily_trend", [])
        if not daily:
            self._trend_widget.draw_trend_line([], [], "暂无日均数据")
            return
        labels = [d.get("date", "") for d in daily]
        values = [d.get("word_count", 0) for d in daily]
        self._trend_widget.draw_trend_line(labels, values)

    def _render_target(self, summary: dict) -> None:
        current = summary.get("total_words", 0)
        target = summary.get("target_words", 0)
        self._chapter_widget.set_target_progress(current, target)
        self._volume_widget.set_target_progress(current, target)
        self._trend_widget.set_target_progress(current, target)

    def _on_error(self, msg: str) -> None:
        self._progress_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)