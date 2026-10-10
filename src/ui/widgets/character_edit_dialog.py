"""人物编辑对话框 - 编辑已有人物信息，保存后发射saved信号."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker

_SCOPE_TYPES = ["全书", "某卷", "某大篇", "某中篇"]


class CharacterEditDialog(QDialog):
    """编辑已有人物的模态对话框.

    保存成功后发射 saved 信号（携带 character_id），调用方可据此刷新列表。
    编辑直接调用 PUT /api/characters/{id} 更新数据库，不仅仅修改列表显示。
    """

    saved = Signal(str)

    def __init__(self, character_data: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._character_data = character_data
        self._character_id: str = character_data.get("character_id", "")
        self._workers: list[ApiWorker] = []
        self._scope_units: list[dict] = []
        self.setWindowTitle("编辑人物")
        self.setMinimumWidth(520)
        self._init_ui()
        self._fill_fields()
        self._load_scope_units()

    def _add_worker(self, worker) -> None:
        """注册 ApiWorker 并在完成后自动清理."""
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))

    def _cleanup_worker(self, worker) -> None:
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()


    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("编辑人物信息")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("1-20字符")
        form.addRow("姓名：", self.name_input)

        self.identity_input = QLineEdit()
        self.identity_input.setPlaceholderText("如：阐教门人/主角挚友")
        form.addRow("身份：", self.identity_input)

        self.intro_edit = QTextEdit()
        self.intro_edit.setPlaceholderText("人物简介（建议不超过200字）")
        self.intro_edit.setFixedHeight(100)
        form.addRow("简介：", self.intro_edit)

        self.relation_edit = QTextEdit()
        self.relation_edit.setPlaceholderText("所属阵营及师承/亲属/敌对关系，如：阐教门人，师承元始天尊")
        self.relation_edit.setFixedHeight(100)
        form.addRow("关系：", self.relation_edit)

        self.scope_type_combo = QComboBox()
        self.scope_type_combo.addItems(_SCOPE_TYPES)
        self.scope_type_combo.currentTextChanged.connect(self._on_scope_type_changed)
        form.addRow("作用域类型：", self.scope_type_combo)

        self.scope_unit_combo = QComboBox()
        self.scope_unit_combo.setEnabled(False)
        form.addRow("作用域单元：", self.scope_unit_combo)

        layout.addLayout(form)

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
        self.name_input.setText(self._character_data.get("name", ""))
        self.identity_input.setText(self._character_data.get("identity", ""))
        self.intro_edit.setPlainText(self._character_data.get("intro", "") or "")
        self.relation_edit.setPlainText(self._character_data.get("relation", "") or "")
        scope_type = self._character_data.get("scope_type") or "全书"
        if scope_type in _SCOPE_TYPES:
            self.scope_type_combo.setCurrentText(scope_type)
        self._pending_scope_unit_id = self._character_data.get("scope_unit_id")

    def _load_scope_units(self) -> None:
        project_id = self._character_data.get("project_id")
        if not project_id:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/story-units/tree/{project_id}")
        worker.result.connect(self._on_scope_units_loaded)
        worker.error.connect(lambda _msg: None)
        self._add_worker(worker)
        worker.start()

    def _on_scope_units_loaded(self, data: dict) -> None:
        units = (data or {}).get("units", []) if isinstance(data, dict) else []
        self._scope_units = units if isinstance(units, list) else []
        self._refresh_scope_unit_combo()
        if getattr(self, "_pending_scope_unit_id", None):
            idx = self.scope_unit_combo.findData(self._pending_scope_unit_id)
            if idx >= 0:
                self.scope_unit_combo.setCurrentIndex(idx)
            self._pending_scope_unit_id = None

    def _on_scope_type_changed(self, text: str) -> None:
        self.scope_unit_combo.setEnabled(text != "全书")
        self._refresh_scope_unit_combo()

    def _refresh_scope_unit_combo(self) -> None:
        scope_type = self.scope_type_combo.currentText()
        self.scope_unit_combo.clear()
        if scope_type == "全书":
            return
        level_map = {"某卷": "volume", "某大篇": "major", "某中篇": "middle"}
        target_level = level_map.get(scope_type)
        for u in self._scope_units:
            if u.get("level_type") == target_level:
                self.scope_unit_combo.addItem(
                    u.get("unit_name", ""),
                    u.get("story_unit_id"),
                )

    def _save(self) -> None:
        name = self.name_input.text().strip()
        identity = self.identity_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "姓名不能为空")
            return
        if len(name) > 20:
            QMessageBox.warning(self, "提示", "姓名不能超过20字符")
            return
        if not identity:
            QMessageBox.warning(self, "提示", "身份不能为空")
            return
        payload = {
            "name": name,
            "identity": identity,
            "intro": self.intro_edit.toPlainText().strip() or None,
            "relation": self.relation_edit.toPlainText().strip() or None,
        }
        client = get_api_client()
        worker = ApiWorker(client.put, f"/api/characters/{self._character_id}", json=payload)
        worker.result.connect(lambda _d: self._save_scope())
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()
        self.save_btn.setEnabled(False)

    def _save_scope(self) -> None:
        scope_type = self.scope_type_combo.currentText()
        scope_unit_id = None
        if scope_type != "全书":
            scope_unit_id = self.scope_unit_combo.currentData()
            if not scope_unit_id:
                self.save_btn.setEnabled(True)
                self.saved.emit(self._character_id)
                self.accept()
                return
        client = get_api_client()
        worker = ApiWorker(
            client.put,
            f"/api/characters/{self._character_id}/scope",
            json={"scope_type": scope_type, "scope_unit_id": scope_unit_id},
        )
        worker.result.connect(self._on_saved)
        worker.error.connect(self._on_scope_error)
        self._add_worker(worker)
        worker.start()

    def _on_saved(self, data: dict) -> None:
        self.save_btn.setEnabled(True)
        self.saved.emit(self._character_id)
        self.accept()

    def _on_scope_error(self, msg: str) -> None:
        self.save_btn.setEnabled(True)
        self.saved.emit(self._character_id)
        self.accept()

    def _on_error(self, msg: str) -> None:
        self.save_btn.setEnabled(True)
        QMessageBox.critical(self, "保存失败", msg)