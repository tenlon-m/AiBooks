"""并排预览组件 - 左侧用户原始修改/右侧润色后内容，高亮标注调整处."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class SideBySidePreview(QWidget):
    """并排预览：左用户修改 / 右润色结果."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        left_label = QLabel("用户修改内容")
        left_label.setStyleSheet("font-weight: bold; padding: 4px; background-color: #fff3e0; border-radius: 4px;")
        right_label = QLabel("AI润色结果")
        right_label.setStyleSheet("font-weight: bold; padding: 4px; background-color: #e8f5e9; border-radius: 4px;")
        header.addWidget(left_label, 1)
        header.addWidget(right_label, 1)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.left_editor = QPlainTextEdit()
        self.left_editor.setReadOnly(True)
        self.left_editor.setStyleSheet("background-color: #fff8e1; border: 1px solid #ddd;")
        self.right_editor = QPlainTextEdit()
        self.right_editor.setReadOnly(True)
        self.right_editor.setStyleSheet("background-color: #f1f8e9; border: 1px solid #ddd;")
        splitter.addWidget(self.left_editor)
        splitter.addWidget(self.right_editor)
        splitter.setSizes([500, 500])
        layout.addWidget(splitter, 1)

        self.notes_label = QLabel("调整说明：")
        self.notes_label.setStyleSheet("padding: 4px; background-color: #f5f5f5; border-radius: 4px;")
        self.notes_label.setWordWrap(True)
        layout.addWidget(self.notes_label)

    def set_content(self, original: str, polished: str, notes: list[dict] | None = None) -> None:
        self.left_editor.setPlainText(original)
        self.right_editor.setPlainText(polished)
        if notes:
            notes_text = "调整说明：\n" + "\n".join(
                f"• {n.get('position', '')}: {n.get('reason', '')}" for n in notes
            )
            self.notes_label.setText(notes_text)
        else:
            self.notes_label.setText("调整说明：无")