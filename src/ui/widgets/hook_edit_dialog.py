"""钩子单条编辑对话框."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

_STATUS_EN_TO_CN = {"pending": "未回收", "recycled": "已回收", "unrecycled": "未回收"}
_STATUS_CN_TO_EN = {"未回收": "pending", "已回收": "recycled"}


class HookEditDialog(QDialog):
    """编辑单条钩子的模态对话框."""

    def __init__(
        self,
        parent: QWidget | None = None,
        volume_no: int = 1,
        chapter_no: int = 1,
        hook_content: str = "",
        recycle_volume_no: int = 1,
        recycle_chapter_no: int = 1,
        recycle_status: str = "pending",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑钩子")
        self.setMinimumWidth(500)
        self._init_ui(volume_no, chapter_no, hook_content, recycle_volume_no, recycle_chapter_no, recycle_status)

    def _init_ui(
        self,
        volume_no: int,
        chapter_no: int,
        hook_content: str,
        recycle_volume_no: int,
        recycle_chapter_no: int,
        recycle_status: str,
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

        self._content_edit = QPlainTextEdit(hook_content)
        self._content_edit.setPlaceholderText("钩子内容（建议5-200字）")
        form.addRow("钩子内容：", self._content_edit)

        self._recycle_volume_spin = QSpinBox()
        self._recycle_volume_spin.setRange(1, 20)
        self._recycle_volume_spin.setValue(recycle_volume_no)
        form.addRow("回收卷号：", self._recycle_volume_spin)

        self._recycle_chapter_spin = QSpinBox()
        self._recycle_chapter_spin.setRange(1, 100)
        self._recycle_chapter_spin.setValue(recycle_chapter_no)
        form.addRow("回收章号：", self._recycle_chapter_spin)

        self._status_combo = QComboBox()
        self._status_combo.addItem("未回收")
        self._status_combo.addItem("已回收")
        cn_status = _STATUS_EN_TO_CN.get(recycle_status, "未回收")
        self._status_combo.setCurrentText(cn_status)
        form.addRow("回收状态：", self._status_combo)

        self._char_count_label = QLabel()
        form.addRow("", self._char_count_label)
        self._content_edit.textChanged.connect(self._update_char_count)
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
        count = len(self._content_edit.toPlainText().strip())
        if 5 <= count <= 200:
            self._char_count_label.setText(f"{count}字 ✓")
            self._char_count_label.setStyleSheet("color: green;")
        else:
            self._char_count_label.setText(f"{count}字（建议5-200字）")
            self._char_count_label.setStyleSheet("color: #ff9800;")

    def get_data(self) -> dict:
        cn_status = self._status_combo.currentText()
        return {
            "volume_no": self._volume_spin.value(),
            "chapter_no": self._chapter_spin.value(),
            "hook_content": self._content_edit.toPlainText().strip(),
            "recycle_volume_no": self._recycle_volume_spin.value(),
            "recycle_chapter_no": self._recycle_chapter_spin.value(),
            "recycle_status": _STATUS_CN_TO_EN.get(cn_status, "pending"),
        }