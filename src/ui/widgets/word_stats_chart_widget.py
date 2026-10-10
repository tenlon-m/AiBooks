"""字数统计图表控件 - 继承 ChartCanvas，柱状图/饼图/趋势线三种绘制方法.

柱状图（按章）、饼图（按卷）、趋势线（日均写作量），目标完成度以进度条展示。
"""
from __future__ import annotations

from PySide6.QtWidgets import QProgressBar, QVBoxLayout, QWidget

from src.ui.widgets.chart_canvas import ChartCanvas


class WordStatsChartWidget(QWidget):
    """字数统计图表容器：内嵌 ChartCanvas + 目标完成度进度条."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._chart = ChartCanvas()
        layout.addWidget(self._chart, 1)

        self._target_bar = QProgressBar()
        self._target_bar.setRange(0, 100)
        self._target_bar.setFormat("目标完成度: %p%")
        layout.addWidget(self._target_bar)

    def draw_chapter_bar(
        self,
        labels: list[str],
        values: list[float],
        title: str = "各章字数统计",
    ) -> None:
        """绘制按章柱状图."""
        self._chart.draw_bar(
            labels=labels,
            values=values,
            title=title,
            xlabel="章节",
            ylabel="字数",
            color="#4CAF50",
        )

    def draw_volume_pie(
        self,
        labels: list[str],
        values: list[float],
        title: str = "各卷字数占比",
    ) -> None:
        """绘制按卷饼图."""
        self._chart.draw_pie(labels=labels, values=values, title=title)

    def draw_trend_line(
        self,
        x_labels: list[str],
        values: list[float],
        title: str = "日均写作量趋势",
    ) -> None:
        """绘制日均写作量趋势线."""
        self._chart.draw_line(
            x_labels=x_labels,
            series={"日均字数": values},
            title=title,
            xlabel="日期",
            ylabel="字数",
        )

    def set_target_progress(self, current: int, target: int) -> None:
        """设置目标完成度进度条."""
        if target <= 0:
            self._target_bar.setValue(0)
            return
        ratio = min(100, int(current / target * 100))
        self._target_bar.setValue(ratio)

    def clear(self) -> None:
        self._chart.clear()
        self._target_bar.setValue(0)