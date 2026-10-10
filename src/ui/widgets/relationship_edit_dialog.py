"""角色关系编辑对话框 - 新增/编辑一条关系（后端 POST/PUT 已实现，此前无UI入口）."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# 与后端 RelationType Literal 保持一致（relationship_schema.py）
RELATION_TYPES: list[tuple[str, str]] = [
    ("family", "亲属"),
    ("master_apprentice", "师徒"),
    ("friend", "朋友"),
    ("hostile", "敌对"),
    ("servant_master", "主仆"),
    ("lover", "情人"),
    ("custom", "自定义"),
]


class RelationshipEditDialog(QDialog):
    """新增或编辑一条角色关系。

    Args:
        characters: 角色节点列表（后端 RelationshipGraphDto.nodes）
        relation: 编辑模式下传入已有关系；为 None 表示新增
    """

    def __init__(
        self,
        characters: list[dict],
        relation: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._characters = characters or []
        self._relation = relation
        self.setWindowTitle("编辑关系" if relation else "新增关系")
        self.setMinimumWidth(420)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._source_combo = QComboBox()
        self._target_combo = QComboBox()
        for c in self._characters:
            label = f"{c.get('name', '')}（{c.get('identity', '') or '未设定身份'}）"
            cid = c.get("character_id", "")
            self._source_combo.addItem(label, cid)
            self._target_combo.addItem(label, cid)

        self._type_combo = QComboBox()
        for key, label in RELATION_TYPES:
            self._type_combo.addItem(label, key)

        self._desc_input = QLineEdit()
        self._desc_input.setPlaceholderText("例如：同门师兄，后期因立场对立反目")

        form.addRow("源角色：", self._source_combo)
        form.addRow("目标角色：", self._target_combo)
        form.addRow("关系类型：", self._type_combo)
        form.addRow("描述：", self._desc_input)
        layout.addLayout(form)

        self._hint_label = QLabel("")
        self._hint_label.setStyleSheet("color: #666; padding: 2px;")
        self._hint_label.setWordWrap(True)
        layout.addWidget(self._hint_label)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确定")
        ok_btn.setStyleSheet(
            "background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        if self._relation:
            self._preselect(self._source_combo, self._relation.get("source_character_id", ""))
            self._preselect(self._target_combo, self._relation.get("target_character_id", ""))
            idx = self._type_combo.findData(self._relation.get("relation_type", "custom"))
            if idx >= 0:
                self._type_combo.setCurrentIndex(idx)
            self._desc_input.setText(self._relation.get("description") or "")

    def _preselect(self, combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _on_accept(self) -> None:
        if self._source_combo.count() == 0 or self._target_combo.count() == 0:
            QMessageBox.warning(self, "提示", "当前项目没有角色，请先在人物管理页添加")
            return
        if self._source_combo.currentData() == self._target_combo.currentData():
            QMessageBox.warning(self, "提示", "源角色与目标角色不能相同")
            return
        self.accept()

    def get_relation(self) -> dict:
        """返回符合后端 RelationshipCreateRequest / UpdateRequest 的字段."""
        return {
            "source_character_id": self._source_combo.currentData(),
            "target_character_id": self._target_combo.currentData(),
            "relation_type": self._type_combo.currentData(),
            "description": self._desc_input.text().strip() or None,
        }
