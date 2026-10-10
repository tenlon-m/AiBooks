"""撰写一致性校验报告对话框 - 结构化展示问题与修复入口."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class WritingCheckReportDialog(QDialog):
    """结构化校验报告窗口，含 AI 一键修复入口."""

    repair_requested = Signal(list)

    LEVEL_ORDER = {"严重": 0, "一般": 1, "轻微": 2}

    def __init__(self, report: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._report = report
        self.setWindowTitle("撰写一致性校验报告")
        self.setMinimumSize(700, 450)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        issues = self._report.get("issues", []) or []
        score = self._report.get("score", 0)
        summary = self._report.get("summary", "")

        header_text = f"整体评分 {score}/100 · 问题 {len(issues)} 条"
        if summary:
            header_text += f" · {summary}"
        header = QLabel(header_text)
        header.setWordWrap(True)
        header.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px;")
        layout.addWidget(header)

        if not issues:
            no_issue = QLabel("未发现问题：已撰写章节与大纲、风格库基本一致")
            no_issue.setStyleSheet("color: green; padding: 16px;")
            layout.addWidget(no_issue)
        else:
            self._table = QTableWidget(0, 6)
            self._table.setHorizontalHeaderLabels(["级别", "卷", "章", "类型", "详情", "建议"])
            self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            self._table.horizontalHeader().setMinimumSectionSize(60)
            for i, w in enumerate([60, 50, 50, 120, 250, 250]):
                self._table.setColumnWidth(i, w)

            sorted_issues = sorted(
                issues,
                key=lambda i: (
                    self.LEVEL_ORDER.get(i.get("level", "提示"), 3),
                    i.get("volume_no", 0),
                    i.get("chapter_no", 0),
                ),
            )

            for issue in sorted_issues:
                row = self._table.rowCount()
                self._table.insertRow(row)
                level = issue.get("level", "提示") or "提示"
                vol = str(issue.get("volume_no", 0))
                ch = str(issue.get("chapter_no", 0))
                typ = issue.get("type", "其他") or "其他"
                detail = issue.get("detail", "")
                suggestion = issue.get("suggestion", "")
                vals = [level, vol, ch, typ, detail, suggestion]
                for col, v in enumerate(vals):
                    item = QTableWidgetItem(v)
                    item.setToolTip(v)
                    if col == 0:
                        if level == "严重":
                            item.setForeground(Qt.GlobalColor.red)
                        elif level == "一般":
                            item.setForeground(Qt.GlobalColor.darkYellow)
                    self._table.setItem(row, col, item)

            layout.addWidget(self._table, 1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        copy_btn = QPushButton("复制全文")
        copy_btn.clicked.connect(self._copy_text)
        btn_layout.addWidget(copy_btn)

        self._repair_btn = QPushButton("AI一键修复")
        self._repair_btn.setStyleSheet(
            "background-color: #ff9800; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._repair_btn.setEnabled(bool(issues))
        self._repair_btn.clicked.connect(self._on_repair)
        btn_layout.addWidget(self._repair_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(lambda: self.done(QDialog.DialogCode.Rejected))
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _copy_text(self) -> None:
        QApplication.clipboard().setText(self._report.get("text", ""))

    def _on_repair(self) -> None:
        issues = self._report.get("issues", []) or []
        self.repair_requested.emit(issues)
        self.done(QDialog.DialogCode.Accepted)