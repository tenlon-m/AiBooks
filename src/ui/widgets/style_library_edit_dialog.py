"""风格库单条编辑对话框."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class StyleLibraryEditDialog(QDialog):
    """编辑单条风格库的模态对话框."""

    def __init__(
        self,
        parent: QWidget | None = None,
        name: str = "",
        description: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑风格库")
        self.setMinimumWidth(500)
        self._init_ui(name, description)

    def _init_ui(self, name: str, description: str) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit(name)
        self._name_edit.setMaxLength(100)
        self._name_edit.setPlaceholderText("风格库名称（1-100字符，必填）")
        form.addRow("名称：", self._name_edit)

        self._name_count_label = QLabel()
        form.addRow("", self._name_count_label)
        self._name_edit.textChanged.connect(self._update_name_count)
        self._update_name_count()

        self._desc_edit = QPlainTextEdit(description)
        self._desc_edit.setPlaceholderText("风格库描述（可选，最多500字符）")
        form.addRow("描述：", self._desc_edit)

        self._desc_count_label = QLabel()
        form.addRow("", self._desc_count_label)
        self._desc_edit.textChanged.connect(self._update_desc_count)
        self._update_desc_count()

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 20px; border-radius: 4px;")
        save_btn.clicked.connect(self._on_save_clicked)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _update_name_count(self) -> None:
        count = len(self._name_edit.text().strip())
        if 1 <= count <= 100:
            self._name_count_label.setText(f"{count}字 ✓")
            self._name_count_label.setStyleSheet("color: green;")
        else:
            self._name_count_label.setText(f"{count}字（建议1-100字，必填）")
            self._name_count_label.setStyleSheet("color: #ff9800;")

    def _update_desc_count(self) -> None:
        count = len(self._desc_edit.toPlainText().strip())
        if count <= 500:
            self._desc_count_label.setText(f"{count}字 ✓")
            self._desc_count_label.setStyleSheet("color: green;")
        else:
            self._desc_count_label.setText(f"{count}字（超出500字上限）")
            self._desc_count_label.setStyleSheet("color: #ff9800;")

    def _on_save_clicked(self) -> None:
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "提示", "名称不能为空")
            return
        if len(self._desc_edit.toPlainText().strip()) > 500:
            QMessageBox.warning(self, "提示", "描述不能超过500字符")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "name": self._name_edit.text().strip(),
            "description": self._desc_edit.toPlainText().strip(),
        }
