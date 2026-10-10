"""matplotlib QtAgg 后端图表画布封装.

供情感曲线与字数统计图表复用。
"""
from __future__ import annotations

# matplotlib -> dateutil -> six.moves 的伪模块会让 PySide6 的 shiboken import hook
# 抛 AttributeError，必须在导入 matplotlib 之前打上补丁（详见 src/utils/compat.py）。
from src.utils.compat import apply_six_namespace_fix

apply_six_namespace_fix()

import matplotlib
matplotlib.use("QtAgg")

matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "SimSun", "KaiTi", "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QWidget, QVBoxLayout


class ChartCanvas(QWidget):
    """matplotlib 图表画布，支持柱状图/饼图/折线图."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._figure = Figure(figsize=(8, 4), dpi=100)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._ax = self._figure.add_subplot(111)

        self._theme_fg = "#222222"
        self._theme_bg = "#FFFFFF"
        self._init_theme_from_manager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)
        self._apply_theme_to_figure()

    def _init_theme_from_manager(self) -> None:
        try:
            from src.ui.theme.theme_manager import ThemeManager
            mgr = ThemeManager.instance()
            resolved = mgr.resolve_colors(mgr.current_theme().theme_id)
            self._theme_fg = resolved.foreground
            self._theme_bg = resolved.background
        except Exception:
            pass

    def apply_theme(self, foreground: str, background: str) -> None:
        """应用主题配色到 matplotlib 图表."""
        self._theme_fg = foreground
        self._theme_bg = background
        self._apply_theme_to_figure()

    def _apply_theme_to_figure(self) -> None:
        """将当前主题色应用到 figure/axes."""
        self._figure.set_facecolor(self._theme_bg)
        for ax in self._figure.axes:
            ax.set_facecolor(self._theme_bg)
            ax.tick_params(colors=self._theme_fg)
            for spine in ax.spines.values():
                spine.set_edgecolor(self._theme_fg)
            if ax.get_title():
                ax.title.set_color(self._theme_fg)
            if ax.get_xlabel():
                ax.xaxis.label.set_color(self._theme_fg)
            if ax.get_ylabel():
                ax.yaxis.label.set_color(self._theme_fg)
        self._canvas.draw()

    def clear(self) -> None:
        """清空图表."""
        self._ax.clear()
        self._apply_theme_to_figure()

    def draw_bar(
        self,
        labels: list[str],
        values: list[float],
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        color: str = "#4CAF50",
    ) -> None:
        """绘制柱状图."""
        self._ax.clear()
        if labels and values:
            self._ax.bar(labels, values, color=color)
        if title:
            self._ax.set_title(title)
        if xlabel:
            self._ax.set_xlabel(xlabel)
        if ylabel:
            self._ax.set_ylabel(ylabel)
        self._figure.tight_layout()
        self._apply_theme_to_figure()

    def draw_pie(
        self,
        labels: list[str],
        values: list[float],
        title: str = "",
    ) -> None:
        """绘制饼图."""
        self._ax.clear()
        import math
        filtered = [
            (l, v) for l, v in zip(labels, values)
            if v and not math.isnan(v) and v > 0
        ]
        if filtered:
            f_labels = [l for l, _ in filtered]
            f_values = [v for _, v in filtered]
            self._ax.pie(f_values, labels=f_labels, autopct="%1.1f%%", startangle=90)
        elif title:
            self._ax.text(0.5, 0.5, "暂无数据", ha="center", va="center", transform=self._ax.transAxes)
        if title:
            self._ax.set_title(title)
        self._figure.tight_layout()
        self._apply_theme_to_figure()

    def draw_line(
        self,
        x_labels: list[str],
        series: dict[str, list[float]],
        title: str = "",
        xlabel: str = "",
        ylabel: str = "",
        ylabel2: str = "",
    ) -> None:
        """绘制折线图，支持双Y轴.

        Args:
            x_labels: X轴标签列表
            series: {系列名: 值列表}，最多两个系列（第二个用右Y轴）
            title/ylabel/ylabel2: 标题与左右Y轴标签
        """
        self._ax.clear()
        if not x_labels or not series:
            self._canvas.draw()
            return

        x = range(len(x_labels))
        items = list(series.items())
        if items:
            name0, vals0 = items[0]
            self._ax.plot(x, vals0, marker="o", label=name0, color="#2196F3")
            self._ax.set_ylabel(ylabel or name0)

        if len(items) > 1:
            ax2 = self._ax.twinx()
            name1, vals1 = items[1]
            ax2.plot(x, vals1, marker="s", label=name1, color="#FF5722")
            ax2.set_ylabel(ylabel2 or name1)

        self._ax.set_xticks(list(x))
        self._ax.set_xticklabels(x_labels, rotation=45, ha="right")
        if title:
            self._ax.set_title(title)
        if xlabel:
            self._ax.set_xlabel(xlabel)
        self._ax.legend(loc="upper left")
        self._figure.tight_layout()
        self._apply_theme_to_figure()