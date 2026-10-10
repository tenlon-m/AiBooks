"""时间线节点编辑对话框 - 编辑事件名/时间点/涉及角色/关联章节/事件描述."""
from __future__ import annotations

from PySide6.QtCore import Signal
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


class TimelineNodeEditDialog(QDialog):
    """编辑时间线节点的模态对话框.

    保存成功后发射 saved 信号（携带节点数据字典）。
    """

    saved = Signal(dict)

    def __init__(self, node_data: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._node_data: dict = dict(node_data) if node_data else {}
        self.setWindowTitle("编辑时间线节点")
        self.setMinimumWidth(520)
        self._init_ui()
        self._fill_fields()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("时间线节点信息")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        form = QFormLayout()

        self.event_name_input = QLineEdit()
        self.event_name_input.setPlaceholderText("事件名称")
        form.addRow("事件名：", self.event_name_input)

        self.time_point_input = QLineEdit()
        self.time_point_input.setPlaceholderText("如：第一卷第三章 / 开篇前三年")
        form.addRow("时间点：", self.time_point_input)

        self.characters_input = QLineEdit()
        self.characters_input.setPlaceholderText("涉及角色，逗号分隔")
        form.addRow("涉及角色：", self.characters_input)

        self.chapter_input = QLineEdit()
        self.chapter_input.setPlaceholderText("关联章节，如：1-3 表示第1卷第3章")
        form.addRow("关联章节：", self.chapter_input)

        layout.addLayout(form)

        layout.addWidget(QLabel("事件描述："))
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setPlaceholderText("事件详细描述")
        self.desc_edit.setMaximumHeight(120)
        layout.addWidget(self.desc_edit)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.save_btn = QPushButton("保存")
        self.save_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 20px; border-radius: 4px;")
        self.save_btn.clicked.connect(self._save)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def _fill_fields(self) -> None:
        self.event_name_input.setText(self._node_data.get("event_name", ""))
        self.time_point_input.setText(self._node_data.get("time_point", ""))
        self.characters_input.setText(self._node_data.get("characters", ""))
        self.chapter_input.setText(self._node_data.get("chapter_ref", ""))
        self.desc_edit.setPlainText(self._node_data.get("description", ""))

    def _save(self) -> None:
        event_name = self.event_name_input.text().strip()
        if not event_name:
            QMessageBox.warning(self, "提示", "事件名不能为空")
            return
        data = {
            "node_id": self._node_data.get("node_id"),
            "event_name": event_name,
            "time_point": self.time_point_input.text().strip(),
            "characters": self.characters_input.text().strip(),
            "chapter_ref": self.chapter_input.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
        }
        self.saved.emit(data)
        self.accept()

    def get_data(self) -> dict:
        return {
            "node_id": self._node_data.get("node_id"),
            "event_name": self.event_name_input.text().strip(),
            "time_point": self.time_point_input.text().strip(),
            "characters": self.characters_input.text().strip(),
            "chapter_ref": self.chapter_input.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
        }