"""情感曲线图表控件 - 继承 ChartCanvas，matplotlib 折线图展示情感曲线.

双Y轴分别为紧张度与情绪起伏，X轴为章节。
"""
from __future__ import annotations

from src.ui.widgets.chart_canvas import ChartCanvas


class EmotionChartWidget(ChartCanvas):
    """情感曲线图表：紧张度（左Y轴）+ 情绪起伏（右Y轴）随章节变化."""

    def draw_emotion_curve(
        self,
        chapter_labels: list[str],
        tension_values: list[float],
        fluctuation_values: list[float],
        title: str = "情感曲线分析",
    ) -> None:
        """绘制情感曲线.

        Args:
            chapter_labels: X轴章节标签列表
            tension_values: 紧张度值列表（0-100）
            fluctuation_values: 情绪起伏值列表（0-100）
            title: 图表标题
        """
        series = {
            "紧张度": tension_values,
            "情绪起伏": fluctuation_values,
        }
        self.draw_line(
            x_labels=chapter_labels,
            series=series,
            title=title,
            xlabel="章节",
            ylabel="紧张度",
            ylabel2="情绪起伏",
        )

    def draw_empty(self, message: str = "暂无情感曲线数据，请点击生成按钮") -> None:
        """显示空状态提示."""
        self._ax.clear()
        self._ax.text(
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            fontsize=12,
            color=self._theme_fg,
            transform=self._ax.transAxes,
        )
        self._ax.set_axis_off()
        self._apply_theme_to_figure()