"""命名生成器页 - AI批量生成角色/地点/物品名称+候选表格+收藏+双击标记收藏."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context
from src.ui.sse_worker import SsePostWorker

_NAME_TYPE_LABELS = {
    "character": "人物",
    "location": "地点",
    "place": "地点",
    "item": "物品/法宝",
    "faction": "势力/门派",
    "sect": "门派",
    "skill": "功法/技能",
}


class NamingGeneratorPage(QWidget):
    """命名生成器页面 - 遵循UI统一范式.

    布局：标题→思路输入栏→状态标签→类型选择+候选表格+收藏表格→底部按钮栏→进度标签
    """

    naming_saved = Signal()
    characters_imported = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._sse_worker: SsePostWorker | None = None
        self._has_unsaved_changes: bool = False
        self._init_ui()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def clear_page(self) -> None:
        self._stop_sse_worker()
        self._candidate_table.setRowCount(0)
        self._favorite_table.setRowCount(0)
        self._ideas_input.clear()
        self._status_label.setText("就绪")
        self._progress_bar.setValue(0)
        self._progress_label.setText("")
        self._has_unsaved_changes = False


    def _stop_sse_worker(self) -> None:
        if self._sse_worker:
            try:
                self._sse_worker.stop()
            except Exception:
                pass
            self._sse_worker = None

    def closeEvent(self, event) -> None:
        self._stop_sse_worker()
        super().closeEvent(event)

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _mark_unsaved(self) -> None:
        self._has_unsaved_changes = True


    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self._ideas_input.clear()
        if project_id:
            self._load_favorites()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("命名生成器")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        ideas_label = QLabel(
            "命名思路与想法（可选）：在此输入你对命名的风格、文化背景等思路，AI生成时会充分参考"
        )
        ideas_label.setStyleSheet("color: #555; padding: 4px 8px;")
        layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText(
            "例如：仙侠风格，参考山海经异兽命名，单字或双字，避免过于生僻……"
        )
        self._ideas_input.setMaximumHeight(80)
        self._ideas_input.setStyleSheet("padding: 4px;")
        layout.addWidget(self._ideas_input)

        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self._status_label)

        config_layout = QHBoxLayout()
        config_layout.addWidget(QLabel("命名类型："))
        self._type_combo = QComboBox()
        self._type_combo.addItem("角色名", "character")
        self._type_combo.addItem("地点名", "location")
        self._type_combo.addItem("物品名", "item")
        self._type_combo.addItem("势力/门派名", "faction")
        self._type_combo.addItem("功法/技能名", "skill")
        config_layout.addWidget(self._type_combo)
        config_layout.addWidget(QLabel("数量："))
        from PySide6.QtWidgets import QSpinBox
        self._count_spin = QSpinBox()
        self._count_spin.setRange(1, 50)
        self._count_spin.setValue(10)
        config_layout.addWidget(self._count_spin)
        config_layout.addStretch()
        layout.addLayout(config_layout)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        layout.addWidget(self._progress_bar)

        layout.addWidget(QLabel("候选名称："))
        self._candidate_table = QTableWidget(0, 4)
        self._candidate_table.setHorizontalHeaderLabels(
            ["名称", "类型", "释义", "状态"]
        )
        self._candidate_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._candidate_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._candidate_table.cellDoubleClicked.connect(self._on_candidate_double_clicked)
        layout.addWidget(self._candidate_table, 1)

        layout.addWidget(QLabel("已收藏名称："))
        self._favorite_table = QTableWidget(0, 4)
        self._favorite_table.setHorizontalHeaderLabels(
            ["名称", "类型", "释义", "收藏时间"]
        )
        self._favorite_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._favorite_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        layout.addWidget(self._favorite_table, 1)

        btn_layout = QHBoxLayout()
        self._generate_btn = QPushButton("批量生成")
        self._generate_btn.setStyleSheet(
            "background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._generate_btn.clicked.connect(self._generate_names)
        self._stop_btn = QPushButton("停止")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet(
            "background-color: #f44336; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._stop_btn.clicked.connect(self._stop_generation)
        self._favorite_btn = QPushButton("收藏选中")
        self._favorite_btn.clicked.connect(self._favorite_selected)
        self._unfavorite_btn = QPushButton("取消收藏")
        self._unfavorite_btn.clicked.connect(self._unfavorite_selected)

        self._refresh_btn = QPushButton("刷新收藏")
        self._refresh_btn.clicked.connect(self._load_favorites)
        self._import_items_btn = QPushButton("导入到物品管理")
        self._import_items_btn.setStyleSheet(
            "background-color: #ff9800; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._import_items_btn.clicked.connect(self._import_to_items)
        self._import_chars_btn = QPushButton("导入到人物管理")
        self._import_chars_btn.setStyleSheet(
            "background-color: #9c27b0; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._import_chars_btn.clicked.connect(self._import_to_characters)
        self._append_wv_btn = QPushButton("追加到世界观")
        self._append_wv_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._append_wv_btn.clicked.connect(self._append_to_worldview)
        btn_layout.addWidget(self._generate_btn)
        btn_layout.addWidget(self._stop_btn)
        btn_layout.addWidget(self._favorite_btn)
        btn_layout.addWidget(self._unfavorite_btn)

        btn_layout.addWidget(self._refresh_btn)
        btn_layout.addWidget(self._import_chars_btn)
        btn_layout.addWidget(self._import_items_btn)
        btn_layout.addWidget(self._append_wv_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._progress_label)

    def _get_project_id(self) -> str | None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return None
        return ctx.project_id

    def _generate_names(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        if self._sse_worker:
            try:
                self._sse_worker.stop()
            except Exception:
                pass
            self._sse_worker = None
        naming_type = self._type_combo.currentData()
        count = int(self._count_spin.value())
        user_ideas = self._ideas_input.toPlainText().strip()
        self._candidate_table.setRowCount(0)
        self._status_label.setText("AI生成中...")
        self._progress_label.setText("AI生成中...")
        self._generate_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._progress_bar.setRange(0, 0)
        payload = {
            "project_id": pid,
            "name_type": naming_type,
            "count": count,
            "user_ideas": user_ideas,
        }
        self._sse_worker = SsePostWorker("/api/naming/generate/stream", payload=payload)
        self._sse_worker.chunk.connect(self._on_chunk)
        self._sse_worker.event.connect(self._on_event)
        self._sse_worker.error.connect(self._on_sse_error)
        self._sse_worker.finished_ok.connect(self._on_sse_finished)
        self._sse_worker.start()

    def _on_chunk(self, chunk: str) -> None:
        self._progress_label.setText(f"生成中... 已收到 {len(chunk)} 字符")

    def _on_event(self, data: dict) -> None:
        name = data.get("name")
        if name:
            row = self._candidate_table.rowCount()
            self._candidate_table.insertRow(row)
            self._candidate_table.setItem(row, 0, QTableWidgetItem(name))
            raw_type = data.get("naming_type", "")
            type_item = QTableWidgetItem(_NAME_TYPE_LABELS.get(raw_type, raw_type))
            type_item.setData(Qt.UserRole, raw_type)
            self._candidate_table.setItem(row, 1, type_item)
            self._candidate_table.setItem(
                row, 2, QTableWidgetItem(data.get("meaning", ""))
            )
            status_item = QTableWidgetItem("待收藏")
            status_item.setBackground(QColor("#fff9c4"))
            self._candidate_table.setItem(row, 3, status_item)
        progress = data.get("progress")
        if progress is not None:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(int(progress))
        count = data.get("count")
        total = data.get("total")
        if count and total:
            self._progress_label.setText(f"已生成 {count}/{total}")
        if data.get("type") == "done" and data.get("message"):
            self._progress_label.setText(str(data["message"]))

    def _on_sse_error(self, msg: str) -> None:
        self._generate_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(0)
        self._status_label.setText(f"错误：{msg}")
        self._progress_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "生成失败", msg)

    def _on_sse_finished(self) -> None:
        self._generate_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(1)
        total = self._candidate_table.rowCount()
        self._status_label.setText(f"生成完成，共 {total} 个候选名称")
        self._progress_label.setText("生成完成")

    def _stop_generation(self) -> None:
        self._stop_sse_worker()
        self._generate_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_label.setText("已停止")
        self._progress_label.setText("已停止")

    def _on_candidate_double_clicked(self, row: int, _col: int) -> None:
        """双击候选行标记/取消收藏."""
        name_item = self._candidate_table.item(row, 0)
        if not name_item:
            return
        status_item = self._candidate_table.item(row, 3)
        if status_item and status_item.text() == "已收藏":
            QMessageBox.information(self, "提示", "该名称已收藏")
            return
        self._candidate_table.selectRow(row)
        self._favorite_selected()

    def _favorite_selected(self) -> None:
        rows = set(item.row() for item in self._candidate_table.selectedItems())
        if not rows:
            QMessageBox.warning(self, "提示", "请先选中要收藏的候选名称")
            return
        pid = self._get_project_id()
        if not pid:
            return
        new_favorites = []
        for row in sorted(rows):
            status_item = self._candidate_table.item(row, 3)
            if status_item and status_item.text() == "已收藏":
                continue
            name_item = self._candidate_table.item(row, 0)
            type_item = self._candidate_table.item(row, 1)
            meaning_item = self._candidate_table.item(row, 2)
            raw_type = type_item.data(Qt.UserRole) if type_item else ""
            new_favorites.append({
                "name_type": raw_type,
                "value": name_item.text() if name_item else "",
                "meaning": meaning_item.text() if meaning_item else None,
            })
            if status_item:
                status_item.setText("已收藏")
                status_item.setBackground(QColor("#c8e6c9"))
        if not new_favorites:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            f"/api/naming/{pid}/favorites",
            json={"favorites": new_favorites},
        )
        # 收藏即时落库，成功后触发关键节点自动保存（main_window 监听 naming_saved）
        worker.result.connect(self._on_favorite_saved)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_favorite_saved(self, _data: object) -> None:
        self._load_favorites()
        self.naming_saved.emit()

    def _unfavorite_selected(self) -> None:
        rows = set(item.row() for item in self._favorite_table.selectedItems())
        if not rows:
            QMessageBox.warning(self, "提示", "请先选中要取消收藏的名称")
            return
        pid = self._get_project_id()
        if not pid:
            return
        for row in sorted(rows, reverse=True):
            name_item = self._favorite_table.item(row, 0)
            fav_id = name_item.data(Qt.UserRole) if name_item else ""
            if fav_id:
                client = get_api_client()
                worker = ApiWorker(
                    client.delete,
                    f"/api/naming/{pid}/favorites/{fav_id}",
                )
                worker.error.connect(self._on_error)
                self._workers.append(worker)
                worker.start()
            self._favorite_table.removeRow(row)
        self._status_label.setText("已取消收藏")
        self._load_favorites()

    def _load_favorites(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/naming/{pid}/favorites")
        worker.result.connect(self._on_favorites_loaded)
        worker.error.connect(self._on_favorites_error)
        self._workers.append(worker)
        worker.start()

    def _on_favorites_error(self, msg: str) -> None:
        # 收藏列表加载失败要可见，否则用户只看到空白列表以为没收藏
        self._status_label.setText(f"收藏列表加载失败：{msg}")

    def _on_favorites_loaded(self, data: dict | list) -> None:
        favorites = data if isinstance(data, list) else data.get("favorites", [])
        self._favorite_table.setRowCount(0)
        for fav in favorites:
            row = self._favorite_table.rowCount()
            self._favorite_table.insertRow(row)
            name_item = QTableWidgetItem(fav.get("value", ""))
            name_item.setData(Qt.UserRole, fav.get("favorite_id", ""))
            self._favorite_table.setItem(row, 0, name_item)
            raw_type = fav.get("name_type", "")
            type_item = QTableWidgetItem(_NAME_TYPE_LABELS.get(raw_type, raw_type))
            type_item.setData(Qt.UserRole, raw_type)
            self._favorite_table.setItem(row, 1, type_item)
            self._favorite_table.setItem(
                row, 2, QTableWidgetItem(fav.get("meaning", "") or "")
            )
            self._favorite_table.setItem(
                row, 3, QTableWidgetItem(str(fav.get("created_at", "")))
            )

    def _on_error(self, msg: str) -> None:
        self._status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)

    def _import_to_characters(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        reply = QMessageBox.question(
            self,
            "确认导入",
            "将命名收藏中的角色类名称导入到人物管理表？\n"
            "已存在于人物表中的同名角色会自动跳过。\n"
            "导入后角色默认为未确认状态，可在人物管理页补充身份与简介。",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.post, f"/api/naming/{pid}/import-to-characters")
        worker.result.connect(self._on_import_chars_done)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_import_chars_done(self, data: dict) -> None:
        count = data.get("imported_count", 0)
        self._status_label.setText(f"已导入 {count} 个角色到人物管理表")
        self.characters_imported.emit()
        QMessageBox.information(self, "导入完成", f"已导入 {count} 个角色到人物管理表\n请切换到人物管理页查看")

    def _import_to_items(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        reply = QMessageBox.question(
            self,
            "确认导入",
            "将命名收藏中的物品/功法类名称导入到物品管理表？\n"
            "已存在于物品表中的同名物品会自动跳过。",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.post, f"/api/naming/{pid}/import-to-items")
        worker.result.connect(self._on_import_items_done)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_import_items_done(self, data: dict) -> None:
        count = data.get("imported_count", 0)
        self._status_label.setText(f"已导入 {count} 个物品到物品管理表")
        QMessageBox.information(self, "导入完成", f"已导入 {count} 个物品到物品管理表")

    def _append_to_worldview(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        reply = QMessageBox.question(
            self,
            "确认追加",
            "将命名收藏中的地点/势力类名称追加到世界观设定？\n"
            "追加内容会添加到现有世界观文本末尾。",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.post, f"/api/naming/{pid}/append-to-worldview")
        worker.result.connect(self._on_append_wv_done)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_append_wv_done(self, data: dict) -> None:
        self._status_label.setText("已将命名收藏追加到世界观设定")
        QMessageBox.information(self, "追加完成", "已将地点/势力类命名收藏追加到世界观设定")