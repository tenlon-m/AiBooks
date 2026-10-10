"""爽点单条编辑对话框."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class CoolPointEditDialog(QDialog):
    """编辑单条爽点的模态对话框."""

    def __init__(
        self,
        parent: QWidget | None = None,
        volume_no: int = 1,
        chapter_no: int = 1,
        cool_type: str = "",
        content_desc: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑爽点")
        self.setMinimumWidth(500)
        self._init_ui(volume_no, chapter_no, cool_type, content_desc)

    def _init_ui(
        self,
        volume_no: int,
        chapter_no: int,
        cool_type: str,
        content_desc: str,
    ) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._volume_spin = QSpinBox()
        self._volume_spin.setRange(1, 20)
        self._volume_spin.setValue(volume_no)
        form.addRow("卷号：", self._volume_spin)

        self._chapter_spin = QSpinBox()
        self._chapter_spin.setRange(1, 100)
        self._chapter_spin.setValue(chapter_no)
        form.addRow("章号：", self._chapter_spin)

        self._type_edit = QLineEdit(cool_type)
        self._type_edit.setMaxLength(20)
        form.addRow("类型：", self._type_edit)

        self._desc_edit = QPlainTextEdit(content_desc)
        self._desc_edit.setPlaceholderText("爽点描述（建议5-200字）")
        form.addRow("描述：", self._desc_edit)

        self._char_count_label = QLabel()
        form.addRow("", self._char_count_label)
        self._desc_edit.textChanged.connect(self._update_char_count)
        self._update_char_count()

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 20px; border-radius: 4px;")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _update_char_count(self) -> None:
        count = len(self._desc_edit.toPlainText().strip())
        if 5 <= count <= 200:
            self._char_count_label.setText(f"{count}字 ✓")
            self._char_count_label.setStyleSheet("color: green;")
        else:
            self._char_count_label.setText(f"{count}字（建议5-200字）")
            self._char_count_label.setStyleSheet("color: #ff9800;")

    def get_data(self) -> dict:
        return {
            "volume_no": self._volume_spin.value(),
            "chapter_no": self._chapter_spin.value(),
            "cool_type": self._type_edit.text().strip(),
            "content_desc": self._desc_edit.toPlainText().strip(),
        }