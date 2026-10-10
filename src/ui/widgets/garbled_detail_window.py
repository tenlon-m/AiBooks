"""字符修复明细独立窗口 - 逐条展示修复明细与汇总统计."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class GarbledDetailWindow(QDialog):
    """字符修复明细窗口，展示逐条修复明细与汇总统计."""

    def __init__(
        self,
        details: list[dict] | None = None,
        stat: dict | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("字符修复明细")
        self.setMinimumSize(600, 400)
        self.details = details or []
        self.stat = stat or {}

        layout = QVBoxLayout(self)

        summary_label = QLabel(self._build_summary())
        summary_label.setStyleSheet("font-size: 13px; padding: 4px;")
        layout.addWidget(summary_label)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["问题类型", "位置/原文片段", "处理动作", "是否不可逆"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        self._populate()

    def _build_summary(self) -> str:
        if not self.stat:
            return "未发现乱码与格式问题"
        parts = []
        garbled_detected = self.stat.get("garbled_detected", 0)
        format_detected = self.stat.get("format_detected", 0)
        garbled_fixed = self.stat.get("garbled_fixed", 0)
        format_fixed = self.stat.get("format_fixed", 0)
        remainder = self.stat.get("remainder", 0)
        irreversible = self.stat.get("irreversible_cleared", 0)
        parts.append(f"字符乱码：检出 {garbled_detected}，修复 {garbled_fixed}")
        parts.append(f"格式错乱：检出 {format_detected}，修复 {format_fixed}")
        parts.append(f"剩余未修复：{remainder}")
        parts.append(f"不可逆清除：{irreversible}")
        return "  |  ".join(parts)

    def _populate(self) -> None:
        if not self.details:
            self.table.setRowCount(1)
            empty_item = QTableWidgetItem("未发现乱码与格式问题")
            empty_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(0, 0, empty_item)
            self.table.setSpan(0, 0, 1, 4)
            return

        self.table.setRowCount(len(self.details))
        for i, item in enumerate(self.details):
            category = item.get("category", "")
            position = item.get("position", "")
            action = item.get("action", "")
            irreversible = item.get("irreversible", False)

            cat_item = QTableWidgetItem(category)
            pos_item = QTableWidgetItem(str(position))
            act_item = QTableWidgetItem(action)
            irr_item = QTableWidgetItem("是" if irreversible else "否")

            if irreversible:
                color = QColor(255, 200, 200)
                for itm in (cat_item, pos_item, act_item, irr_item):
                    itm.setBackground(color)

            self.table.setItem(i, 0, cat_item)
            self.table.setItem(i, 1, pos_item)
            self.table.setItem(i, 2, act_item)
            self.table.setItem(i, 3, irr_item)