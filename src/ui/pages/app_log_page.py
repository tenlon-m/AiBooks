"""应用程序日志管理页 - 查看/筛选/清理/导出 data/logs/ 下的运行日志."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
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

from src.config.settings import get_config
from src.ui.project_context import get_project_context


class AppLogPage(QWidget):
    """应用程序日志管理页面."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._has_unsaved_changes = False
        self._current_file: Path | None = None
        self._raw_content: str = ""
        self._init_ui()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("应用程序日志管理")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        self.idea_edit = QTextEdit()
        self.idea_edit.setPlaceholderText("思路输入栏（可选）：输入筛选关键词后点击查看内容")
        self.idea_edit.setMaximumHeight(80)
        layout.addWidget(self.idea_edit)

        self.status_label = QLabel("就绪")
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.clicked.connect(self._load_log_files)
        self.view_btn = QPushButton("查看内容")
        self.view_btn.clicked.connect(self._view_content)
        self.export_btn = QPushButton("导出日志")
        self.export_btn.clicked.connect(self._export_log)
        self.clear_btn = QPushButton("清理日志")
        self.clear_btn.setStyleSheet("color: #d32f2f;")
        self.clear_btn.clicked.connect(self._clear_logs)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.view_btn)
        btn_layout.addWidget(self.export_btn)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["文件名", "大小(KB)", "修改时间", "行数"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(self._view_content)
        layout.addWidget(self.table)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("日志级别筛选:"))
        self.level_combo = QComboBox()
        self.level_combo.addItems(["全部", "INFO", "WARNING", "ERROR", "DEBUG"])
        self.level_combo.currentTextChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.level_combo)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        self.content_edit = QTextEdit()
        self.content_edit.setReadOnly(True)
        self.content_edit.setMaximumHeight(300)
        layout.addWidget(self.content_edit)

        self.progress_label = QLabel("")
        layout.addWidget(self.progress_label)

        self._load_log_files()

    def _get_log_dir(self) -> Path:
        return get_config().log_dir

    def _load_log_files(self) -> None:
        self.table.setRowCount(0)
        log_dir = self._get_log_dir()
        if not log_dir.exists():
            self.status_label.setText("日志目录不存在")
            return

        files = sorted(log_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        self.table.setRowCount(len(files))
        for i, f in enumerate(files):
            stat = f.stat()
            self.table.setItem(i, 0, QTableWidgetItem(f.name))
            self.table.setItem(i, 1, QTableWidgetItem(f"{stat.st_size / 1024:.1f}"))
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            self.table.setItem(i, 2, QTableWidgetItem(mtime))
            try:
                line_count = sum(1 for _ in open(f, encoding="utf-8", errors="replace"))
            except Exception:
                line_count = 0
            self.table.setItem(i, 3, QTableWidgetItem(str(line_count)))
        self.status_label.setText(f"共 {len(files)} 个日志文件")

    def _view_content(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择一个日志文件")
            return
        filename = self.table.item(row, 0).text()
        self._current_file = self._get_log_dir() / filename
        if not self._current_file.exists():
            QMessageBox.warning(self, "错误", f"日志文件不存在: {self._current_file}")
            return
        try:
            content = self._current_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"读取日志失败: {e}")
            return
        self._raw_content = content
        self._apply_filter()
        self.progress_label.setText(f"正在查看: {filename}")

    def _apply_filter(self) -> None:
        content = self._raw_content
        if not content:
            return
        level = self.level_combo.currentText()
        keyword = self.idea_edit.toPlainText().strip()
        lines = content.splitlines()
        filtered = []
        for line in lines:
            if level != "全部" and f"| {level}" not in line and f"|{level}" not in line:
                continue
            if keyword and keyword not in line:
                continue
            filtered.append(line)
        display = "\n".join(filtered)
        if not display:
            display = "(无匹配日志行)"
        self.content_edit.setPlainText(display)

    def _export_log(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择一个日志文件")
            return
        filename = self.table.item(row, 0).text()
        src = self._get_log_dir() / filename
        if not src.exists():
            return
        dest, _ = QFileDialog.getSaveFileName(self, "导出日志", filename, "Log Files (*.log);;All Files (*)")
        if dest:
            try:
                Path(dest).write_bytes(src.read_bytes())
                QMessageBox.information(self, "成功", f"已导出到: {dest}")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"导出失败: {e}")

    def _clear_logs(self) -> None:
        reply = QMessageBox.question(
            self, "确认清理",
            "将删除所有历史日志文件（保留当前会话的日志），确定继续？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        log_dir = self._get_log_dir()
        if not log_dir.exists():
            return
        # loguru 的 {time:YYYY-MM-DD} 用的是本地时间，这里必须用本地日期匹配文件名，
        # 否则跨时区时（原实现用 timezone.utc）会误判「当前会话日志」而被删掉
        now = datetime.now().strftime("%Y-%m-%d")
        count = 0
        for f in log_dir.glob("*.log"):
            if now not in f.name:
                try:
                    f.unlink()
                    count += 1
                except Exception:
                    pass
        self._load_log_files()
        self.content_edit.clear()
        QMessageBox.information(self, "完成", f"已清理 {count} 个历史日志文件")

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        pass

    def clear_page(self) -> None:
        self.table.setRowCount(0)
        self.content_edit.clear()
        self.status_label.clear()

    def has_unsaved_changes(self) -> bool:
        return False
