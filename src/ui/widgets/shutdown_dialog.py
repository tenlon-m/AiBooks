"""程序关闭进度对话框 - 逐行显示各组件关闭状态，避免用户不知后台在做什么."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)


class ShutdownDialog(QDialog):
    """不可由用户关闭的进度对话框，逐行显示关闭步骤."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._parent_window = parent
        self.setWindowTitle("正在关闭 AiBooks")
        self.setWindowFlags(
            Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setFixedSize(480, 320)
        self._finished = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel("正在关闭程序，请勿重复点击关闭按钮…")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setStyleSheet(
            "font-size: 12px; font-family: 'Consolas', 'Microsoft YaHei', monospace;"
        )
        layout.addWidget(self._log_view)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        layout.addWidget(self._progress)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._center_on_parent)

    def _center_on_parent(self) -> None:
        parent = self._parent_window
        if parent is not None and parent.isVisible():
            pg = parent.frameGeometry()
            self.move(
                pg.x() + (pg.width() - self.width()) // 2,
                pg.y() + (pg.height() - self.height()) // 2,
            )
        else:
            screen = QApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                self.move(
                    geo.x() + (geo.width() - self.width()) // 2,
                    geo.y() + (geo.height() - self.height()) // 2,
                )

    def log(self, message: str) -> None:
        self._log_view.appendPlainText(message)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()

    def finish(self) -> None:
        self._finished = True
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()

    def closeEvent(self, event) -> None:
        if not self._finished:
            event.ignore()
        else:
            super().closeEvent(event)