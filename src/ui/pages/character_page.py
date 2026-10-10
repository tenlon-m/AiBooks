"""人物管理页 - AI提取/生成人物 + 手动增删改 + 确认 + 增量去重 + 批量操作 + 进度提示."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context
from src.ui.widgets.character_edit_dialog import CharacterEditDialog
from src.ui.widgets.character_progress_timer import CharacterProgressTimer


class CharacterPage(QWidget):
    merge_completed = Signal()
    request_open_naming = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._progress_timer: CharacterProgressTimer | None = None
        self._characters_cache: list[dict] = []
        self._init_ui()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def _get_progress_timer(self) -> CharacterProgressTimer:
        if self._progress_timer is None:
            self._progress_timer = CharacterProgressTimer(self.window().statusBar())
        return self._progress_timer

    def clear_page(self) -> None:
        self.table.setRowCount(0)
        self.name_input.clear()
        self.identity_input.clear()
        self.intro_input.clear()
        self.relation_input.clear()
        self.status_label.clear()

    def has_unsaved_changes(self) -> bool:
        if not get_project_context().has_project():
            return False
        return bool(self.name_input.text().strip() or self.identity_input.text().strip())

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        if project_id:
            self._load_characters()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("人物管理")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        btn_layout = QHBoxLayout()
        self.extract_btn = QPushButton("AI提取人物")
        self.extract_btn.setStyleSheet("background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;")
        self.extract_btn.clicked.connect(self._ai_extract)
        self.import_btn = QPushButton("人物及关系自动识别导入")
        self.import_btn.setStyleSheet("background-color: #00838f; color: white; padding: 6px 16px; border-radius: 4px;")
        self.import_btn.clicked.connect(self._ai_import_from_file)
        self.gen_supporting_btn = QPushButton("AI生成配角")
        self.gen_supporting_btn.clicked.connect(self._ai_generate_supporting)
        self.naming_btn = QPushButton("命名生成器")
        self.naming_btn.setStyleSheet(
            "background-color: #9c27b0; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self.naming_btn.setToolTip("打开命名生成器，AI批量生成角色/地点/物品名称")
        self.naming_btn.clicked.connect(self.request_open_naming.emit)
        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.clicked.connect(self._load_characters)
        btn_layout.addWidget(self.extract_btn)
        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(self.gen_supporting_btn)
        btn_layout.addWidget(self.naming_btn)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        worldview_layout = QHBoxLayout()
        worldview_layout.addWidget(QLabel("世界观模板："))
        self._worldview_template_combo = QComboBox()
        self._worldview_template_combo.addItem("不应用", None)
        self._worldview_template_combo.setMinimumWidth(200)
        worldview_layout.addWidget(self._worldview_template_combo, 1)
        self._load_template_btn = QPushButton("加载模板列表")
        self._load_template_btn.clicked.connect(self._load_worldview_templates)
        worldview_layout.addWidget(self._load_template_btn)
        self._apply_template_btn = QPushButton("应用模板")
        self._apply_template_btn.setStyleSheet(
            "background-color: #00838f; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._apply_template_btn.setToolTip("将选中模板应用到当前项目世界观设定")
        self._apply_template_btn.clicked.connect(self._apply_worldview_template)
        worldview_layout.addWidget(self._apply_template_btn)
        layout.addLayout(worldview_layout)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["人物ID", "姓名", "身份", "简介", "关系", "状态", "来源", "作用域"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(lambda row, _col: self._open_edit_dialog())
        layout.addWidget(self.table, 1)

        form_layout = QHBoxLayout()
        form_layout.addWidget(QLabel("姓名："))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("1-20字符")
        form_layout.addWidget(self.name_input)
        form_layout.addWidget(QLabel("身份："))
        self.identity_input = QLineEdit()
        form_layout.addWidget(self.identity_input)
        form_layout.addWidget(QLabel("简介："))
        self.intro_input = QLineEdit()
        form_layout.addWidget(self.intro_input)
        form_layout.addWidget(QLabel("关系："))
        self.relation_input = QLineEdit()
        form_layout.addWidget(self.relation_input)
        layout.addLayout(form_layout)

        action_layout = QHBoxLayout()
        self.add_btn = QPushButton("添加人物")
        self.add_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;")
        self.add_btn.clicked.connect(self._add_character)
        self.confirm_btn = QPushButton("确认选中人物")
        self.confirm_btn.clicked.connect(self._batch_confirm)
        self.edit_btn = QPushButton("编辑人物")
        self.edit_btn.setStyleSheet("background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;")
        self.edit_btn.clicked.connect(self._open_edit_dialog)
        self.edit_btn.setEnabled(False)
        self.batch_delete_btn = QPushButton("批量删除")
        self.batch_delete_btn.setStyleSheet("background-color: #f44336; color: white; padding: 6px 16px; border-radius: 4px;")
        self.batch_delete_btn.clicked.connect(self._batch_delete)
        self.batch_delete_btn.setEnabled(False)
        self.confirm_btn.setEnabled(False)
        action_layout.addWidget(self.add_btn)
        action_layout.addWidget(self.confirm_btn)
        action_layout.addWidget(self.edit_btn)
        action_layout.addWidget(self.batch_delete_btn)
        action_layout.addStretch()
        layout.addLayout(action_layout)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

    def _get_project_id(self) -> str | None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return None
        return ctx.project_id

    def _load_characters(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/characters/{pid}")
        worker.result.connect(self._on_characters_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_characters_loaded(self, characters: list) -> None:
        self._characters_cache: list[dict] = characters
        self.table.setRowCount(0)
        source_map = {
            "ai_extract": "AI提取",
            "ai_generate": "AI生成",
            "manual_input": "手动输入",
            "file_import": "文件导入",
            "auto_generated": "自动生成",
            "naming_import": "命名导入",
        }
        for c in characters:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(c.get("character_id", "") or ""))
            self.table.setItem(row, 1, QTableWidgetItem(c.get("name", "")))
            self.table.setItem(row, 2, QTableWidgetItem(c.get("identity", "")))
            self.table.setItem(row, 3, QTableWidgetItem(c.get("intro", "") or ""))
            self.table.setItem(row, 4, QTableWidgetItem(c.get("relation", "") or ""))
            confirmed = c.get("confirmed", False)
            self._render_status_cell(row, confirmed)
            source_text = source_map.get(c.get("source", ""), c.get("source", ""))
            self.table.setItem(row, 6, QTableWidgetItem(source_text))
            scope_text = c.get("scope_type") or "全书"
            self.table.setItem(row, 7, QTableWidgetItem(scope_text))
        self.status_label.setText(f"共 {len(characters)} 个人物")

    def _render_status_cell(self, row: int, confirmed: bool) -> None:
        item = QTableWidgetItem("已确认" if confirmed else "待确认")
        if confirmed:
            item.setBackground(QColor("#c8e6c9"))
        else:
            item.setBackground(QColor("#fff9c4"))
        self.table.setItem(row, 5, item)

    def _collect_selected_ids(self) -> list[str]:
        rows = set()
        for item in self.table.selectedItems():
            rows.add(item.row())
        ids: list[str] = []
        for row in rows:
            id_item = self.table.item(row, 0)
            if id_item and id_item.text():
                ids.append(id_item.text())
        return ids

    def _on_selection_changed(self) -> None:
        selected_ids = self._collect_selected_ids()
        self.batch_delete_btn.setEnabled(len(selected_ids) > 0)
        self.confirm_btn.setEnabled(len(selected_ids) > 0)
        self.edit_btn.setEnabled(len(selected_ids) == 1)

    def _open_edit_dialog(self) -> None:
        selected_ids = self._collect_selected_ids()
        if len(selected_ids) != 1:
            QMessageBox.warning(self, "提示", "请选中一行人物进行编辑")
            return
        char_id = selected_ids[0]
        char_data = next(
            (c for c in getattr(self, "_characters_cache", []) if c.get("character_id") == char_id),
            None,
        )
        if char_data is None:
            QMessageBox.warning(self, "提示", "人物数据未加载，请刷新列表后重试")
            return
        dialog = CharacterEditDialog(char_data, self)
        dialog.saved.connect(lambda _cid: self._load_characters())
        dialog.exec()

    def _ai_extract(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        synopsis = ""
        worldview = ""
        try:
            syn = client.get(f"/api/creation/{pid}/synopsis")
            synopsis = syn.get("content", "")
        except Exception:
            pass
        try:
            wv = client.get(f"/api/creation/{pid}/worldview")
            worldview = wv.get("content", "")
        except Exception:
            pass
        if not synopsis or not worldview:
            QMessageBox.warning(self, "提示", "梗概或世界观未设定，请先在创作参数页填写并保存")
            return
        self._get_progress_timer().start("AI提取人物")
        self.extract_btn.setEnabled(False)
        payload = {"project_id": pid, "synopsis": synopsis, "worldview": worldview}
        worker = ApiWorker(client.post, "/api/characters/ai_extract", json=payload)
        worker.result.connect(self._on_merge_done)
        worker.error.connect(self._on_merge_error)
        self._workers.append(worker)
        worker.start()

    def _ai_import_from_file(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择人物设定文档", "",
            "Word文档 (*.docx);;Excel文件 (*.xlsx);;文本文件 (*.txt *.md);;所有文件 (*)"
        )
        if not file_path:
            return
        self._get_progress_timer().start("人物及关系导入")
        self.import_btn.setEnabled(False)
        payload = {"project_id": pid, "file_path": file_path}
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/characters/ai_import", json=payload)
        worker.result.connect(self._on_merge_done)
        worker.error.connect(self._on_merge_error)
        self._workers.append(worker)
        worker.start()

    def _ai_generate_supporting(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        try:
            existing = client.get(f"/api/characters/{pid}")
        except Exception:
            existing = []
        if not existing:
            QMessageBox.warning(self, "提示", "请先提取或添加主要人物")
            return
        synopsis = ""
        worldview = ""
        try:
            synopsis = client.get(f"/api/creation/{pid}/synopsis").get("content", "")
            worldview = client.get(f"/api/creation/{pid}/worldview").get("content", "")
        except Exception:
            pass
        self._get_progress_timer().start("AI生成配角")
        self.gen_supporting_btn.setEnabled(False)
        payload = {
            "project_id": pid,
            "synopsis": synopsis,
            "worldview": worldview,
            "existing_characters": existing,
            "count": 10,
        }
        worker = ApiWorker(client.post, "/api/characters/ai_generate_supporting", json=payload)
        worker.result.connect(self._on_merge_done)
        worker.error.connect(self._on_merge_error)
        self._workers.append(worker)
        worker.start()

    def _on_merge_done(self, resp: dict) -> None:
        self.extract_btn.setEnabled(True)
        self.import_btn.setEnabled(True)
        self.gen_supporting_btn.setEnabled(True)
        added_count = resp.get("added_count", 0)
        skipped_count = resp.get("skipped_count", 0)
        self._get_progress_timer().show_complete(added_count, skipped_count)
        self._load_characters()
        self.merge_completed.emit()

    def _on_merge_error(self, msg: str) -> None:
        self.extract_btn.setEnabled(True)
        self.import_btn.setEnabled(True)
        self.gen_supporting_btn.setEnabled(True)
        self._get_progress_timer().show_error(msg)
        QMessageBox.warning(self, "操作失败", msg)

    def _add_character(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        name = self.name_input.text().strip()
        identity = self.identity_input.text().strip()
        if not name or not identity:
            QMessageBox.warning(self, "提示", "请输入姓名和身份")
            return
        existing_names = {
            c.get("name", "") for c in getattr(self, "_characters_cache", [])
        }
        if name in existing_names:
            QMessageBox.warning(self, "提示", f"人物「{name}」已存在，名字需全书唯一")
            return
        payload = {
            "project_id": pid,
            "name": name,
            "identity": identity,
            "intro": self.intro_input.text().strip() or None,
            "relation": self.relation_input.text().strip() or None,
            "source": "manual_input",
        }
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/characters", json=payload)
        worker.result.connect(lambda _: (self._load_characters(), self.name_input.clear(), self.identity_input.clear(), self.intro_input.clear(), self.relation_input.clear()))
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _batch_confirm(self) -> None:
        selected_ids = self._collect_selected_ids()
        if not selected_ids:
            QMessageBox.warning(self, "提示", "请先选中要确认的人物")
            return
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/characters/batch_confirm", json={"character_ids": selected_ids})
        worker.result.connect(lambda _: self._load_characters())
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _batch_delete(self) -> None:
        selected_ids = self._collect_selected_ids()
        if not selected_ids:
            QMessageBox.warning(self, "提示", "请先选中要删除的人物")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除选中的{len(selected_ids)}个人物？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/characters/batch_delete", json={"character_ids": selected_ids})
        worker.result.connect(self._on_batch_delete_done)
        worker.error.connect(self._on_batch_delete_error)
        self._workers.append(worker)
        worker.start()

    def _on_batch_delete_done(self, resp: dict) -> None:
        deleted_count = resp.get("deleted_count", 0)
        if self.window():
            self.window().statusBar().showMessage(f"已删除{deleted_count}个人物", 3000)
        self._load_characters()

    def _on_batch_delete_error(self, msg: str) -> None:
        QMessageBox.critical(self, "批量删除失败", msg)


    def _on_error(self, msg: str) -> None:
        self.extract_btn.setEnabled(True)
        self.import_btn.setEnabled(True)
        self.gen_supporting_btn.setEnabled(True)
        self.status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)
    def _load_worldview_templates(self) -> None:
        """加载世界观模板列表."""
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/template-library/worldview")
        worker.result.connect(self._on_templates_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_templates_loaded(self, templates) -> None:
        if not isinstance(templates, list):
            templates = (templates or {}).get("templates", [])
        self._worldview_template_combo.clear()
        self._worldview_template_combo.addItem("不应用", None)
        for tpl in templates:
            self._worldview_template_combo.addItem(
                tpl.get("name", ""),
                tpl.get("world_type"),
            )
        self.status_label.setText(f"已加载 {len(templates)} 个世界观模板")

    def _apply_worldview_template(self) -> None:
        """应用选中的世界观模板到当前项目."""
        template_id = self._worldview_template_combo.currentData()
        if not template_id:
            QMessageBox.warning(self, "提示", "请先选择要应用的世界观模板")
            return
        pid = self._get_project_id()
        if not pid:
            return
        reply = QMessageBox.question(
            self, "确认应用",
            "应用世界观模板将覆盖当前世界观设定，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._apply_template_btn.setEnabled(False)
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            "/api/template-library/worldview/apply",
            json={"project_id": pid, "world_type": template_id},
        )
        worker.result.connect(self._on_template_applied)
        worker.error.connect(self._on_template_apply_error)
        self._workers.append(worker)
        worker.start()

    def _on_template_applied(self, data: dict) -> None:
        self._apply_template_btn.setEnabled(True)
        self.status_label.setText("世界观模板应用成功")
        self.merge_completed.emit()
        QMessageBox.information(self, "成功", "世界观模板已应用，请查看创作参数页的世界观设定")

    def _on_template_apply_error(self, msg: str) -> None:
        self._apply_template_btn.setEnabled(True)
        QMessageBox.critical(self, "应用失败", msg)
