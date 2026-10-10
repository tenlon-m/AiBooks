"""角色关系图谱页 - QGraphicsView 渲染节点(角色)与边(关系) + 关系类型筛选 + 自动提取."""
from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context
from src.ui.widgets.character_progress_timer import CharacterProgressTimer
from src.ui.widgets.relationship_edit_dialog import RelationshipEditDialog, RELATION_TYPES

# 与后端 RelationType Literal 保持一致（relationship_schema.py）
# 单一来源：relationship_edit_dialog.RELATION_TYPES
_RELATION_TYPES: list[tuple[str, str]] = RELATION_TYPES


class RelationshipGraphPage(QWidget):
    relationship_updated = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._progress_timer: CharacterProgressTimer | None = None
        self._has_unsaved_changes: bool = False
        self._characters_cache: list[dict] = []
        self._relations_cache: list[dict] = []
        self._active_types: set[str] = {t for t, _ in _RELATION_TYPES}
        self._init_ui()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

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


    def _get_progress_timer(self) -> CharacterProgressTimer:
        if self._progress_timer is None:
            self._progress_timer = CharacterProgressTimer(self.window().statusBar())
        return self._progress_timer

    def clear_page(self) -> None:
        self._scene.clear()
        self._characters_cache = []
        self._relations_cache = []
        self.status_label.clear()
        self._detail_view.clear()
        self._relation_table.setRowCount(0)
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _mark_unsaved(self) -> None:
        self._has_unsaved_changes = True
        self.save_btn.setStyleSheet("border: 2px solid #ff9800;")

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self._ideas_input.clear()
        if project_id:
            self._load_graph()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("角色关系图谱")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        ideas_label = QLabel("关系图谱思路与想法（可选）：在此输入你对角色关系的思路和想法")
        ideas_label.setStyleSheet("color: #555; padding: 4px 8px;")
        layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText("例如：主角与反派为宿敌，主角与女主为情人关系……")
        self._ideas_input.setMaximumHeight(80)
        self._ideas_input.setStyleSheet("padding: 4px;")
        layout.addWidget(self._ideas_input)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("关系类型筛选："))
        self._type_checkboxes: dict[str, QCheckBox] = {}
        for type_key, type_label in _RELATION_TYPES:
            cb = QCheckBox(type_label)
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_filter_changed)
            self._type_checkboxes[type_key] = cb
            filter_layout.addWidget(cb)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        content_layout = QHBoxLayout()
        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setMinimumWidth(600)
        self._view.clicked_node = None
        self._view.mousePressEvent = self._on_view_mouse_press
        content_layout.addWidget(self._view, 3)

        detail_container = QWidget()
        detail_layout = QVBoxLayout(detail_container)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(QLabel("角色详情："))
        self._detail_view = QTextEdit()
        self._detail_view.setReadOnly(True)
        detail_layout.addWidget(self._detail_view, 1)

        detail_layout.addWidget(QLabel("关系列表："))
        self._relation_table = QTableWidget(0, 3)
        self._relation_table.setHorizontalHeaderLabels(["关系", "类型", "描述"])
        self._relation_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._relation_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._relation_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._relation_table.setMaximumHeight(220)
        detail_layout.addWidget(self._relation_table)
        content_layout.addWidget(detail_container, 1)
        layout.addLayout(content_layout, 1)

        btn_layout = QHBoxLayout()
        self.extract_btn = QPushButton("自动提取关系")
        self.extract_btn.setStyleSheet("background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;")
        self.extract_btn.clicked.connect(self._auto_extract)
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self._save_relations)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._load_graph)
        self.add_btn = QPushButton("新增关系")
        self.add_btn.clicked.connect(self._add_relation)
        self.edit_btn = QPushButton("编辑选中")
        self.edit_btn.clicked.connect(self._edit_relation)
        self.delete_btn = QPushButton("删除选中")
        self.delete_btn.clicked.connect(self._delete_relation)
        btn_layout.addWidget(self.extract_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.delete_btn)
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

    def _load_graph(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/relationships/{pid}")
        worker.result.connect(self._on_graph_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_graph_loaded(self, data: dict) -> None:
        # 后端 RelationshipGraphDto 返回 nodes（角色）/edges（关系）
        self._characters_cache = data.get("nodes", [])
        self._relations_cache = data.get("edges", [])
        self._render_graph()
        self._render_relation_table()
        self.status_label.setText(
            f"共 {len(self._characters_cache)} 个角色，{len(self._relations_cache)} 条关系"
        )

    # ---------------------------------------------------------------- 关系表
    def _char_name(self, char_id: str) -> str:
        char = next(
            (c for c in self._characters_cache if c.get("character_id") == char_id), None
        )
        return char.get("name", char_id) if char else (char_id or "?")

    def _render_relation_table(self) -> None:
        self._relation_table.setRowCount(0)
        type_labels = dict(_RELATION_TYPES)
        for rel in self._relations_cache:
            row = self._relation_table.rowCount()
            self._relation_table.insertRow(row)
            src = self._char_name(rel.get("source_character_id", ""))
            tgt = self._char_name(rel.get("target_character_id", ""))
            item = QTableWidgetItem(f"{src} → {tgt}")
            # 整条关系挂在首列，供编辑/删除取用
            item.setData(Qt.ItemDataRole.UserRole, rel)
            self._relation_table.setItem(row, 0, item)
            rel_type = rel.get("relation_type", "custom")
            self._relation_table.setItem(
                row, 1, QTableWidgetItem(type_labels.get(rel_type, rel_type))
            )
            self._relation_table.setItem(
                row, 2, QTableWidgetItem(rel.get("description") or "")
            )

    def _selected_relation(self) -> dict | None:
        row = self._relation_table.currentRow()
        if row < 0:
            return None
        item = self._relation_table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _add_relation(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        if not self._characters_cache:
            QMessageBox.warning(self, "提示", "当前项目没有角色，请先在人物管理页添加")
            return
        dialog = RelationshipEditDialog(self._characters_cache, None, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        payload = dialog.get_relation()
        payload["project_id"] = pid
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/relationships/", json=payload)
        worker.result.connect(self._on_relation_saved)
        worker.error.connect(self._on_save_error)
        self._add_worker(worker)
        worker.start()

    def _edit_relation(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        rel = self._selected_relation()
        if not rel:
            QMessageBox.information(self, "提示", "请先在下方「关系列表」中选中一条关系")
            return
        dialog = RelationshipEditDialog(self._characters_cache, rel, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.get_relation()
        relationship_id = rel.get("relationship_id", "")
        if not relationship_id:
            QMessageBox.warning(self, "提示", "该关系缺少ID，请刷新后重试")
            return
        client = get_api_client()
        worker = ApiWorker(
            client.put,
            f"/api/relationships/{pid}/{relationship_id}",
            json={"relation_type": data["relation_type"], "description": data["description"]},
        )
        worker.result.connect(self._on_relation_saved)
        worker.error.connect(self._on_save_error)
        self._add_worker(worker)
        worker.start()

    def _delete_relation(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        rel = self._selected_relation()
        if not rel:
            QMessageBox.information(self, "提示", "请先在下方「关系列表」中选中一条关系")
            return
        relationship_id = rel.get("relationship_id", "")
        if not relationship_id:
            QMessageBox.warning(self, "提示", "该关系缺少ID，请刷新后重试")
            return
        src = self._char_name(rel.get("source_character_id", ""))
        tgt = self._char_name(rel.get("target_character_id", ""))
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除关系「{src} → {tgt}」？（将立即从数据库删除，无需再点保存）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.delete, f"/api/relationships/{pid}/{relationship_id}"
        )
        worker.result.connect(self._on_relation_deleted)
        worker.error.connect(self._on_save_error)
        self._add_worker(worker)
        worker.start()

    def _on_relation_saved(self, _data: object) -> None:
        QMessageBox.information(self, "成功", "关系已保存")
        self._load_graph()
        self.relationship_updated.emit()

    def _on_relation_deleted(self, _data: object) -> None:
        QMessageBox.information(self, "成功", "关系已删除")
        self._load_graph()
        self.relationship_updated.emit()

    def _render_graph(self) -> None:
        self._scene.clear()
        if not self._characters_cache:
            return
        n = len(self._characters_cache)
        radius = max(200, n * 30)
        center_x, center_y = radius + 50, radius + 50
        positions: dict[str, tuple[float, float]] = {}
        for idx, char in enumerate(self._characters_cache):
            angle = 2 * math.pi * idx / max(n, 1)
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            char_id = char.get("character_id", "")
            positions[char_id] = (x, y)

            ellipse = QGraphicsEllipseItem(x - 25, y - 25, 50, 50)
            ellipse.setBrush(QBrush(QColor("#1976D2")))
            ellipse.setPen(QPen(QColor("#0D47A1"), 2))
            ellipse.setData(0, char_id)
            self._scene.addItem(ellipse)

            label = QGraphicsTextItem(char.get("name", ""), ellipse)
            label.setFont(QFont("Microsoft YaHei", 9))
            label.setPos(x - label.boundingRect().width() / 2, y + 28)
            label.setDefaultTextColor(QColor("#333333"))

        type_colors = {
            "family": "#E91E63",
            "master_apprentice": "#9C27B0",
            "friend": "#4CAF50",
            "hostile": "#F44336",
            "servant_master": "#FF9800",
            "lover": "#E91E63",
            "custom": "#607D8B",
        }
        for rel in self._relations_cache:
            rel_type = rel.get("relation_type", "custom")
            if rel_type not in self._active_types:
                continue
            src_id = rel.get("source_character_id", "")
            tgt_id = rel.get("target_character_id", "")
            if src_id not in positions or tgt_id not in positions:
                continue
            x1, y1 = positions[src_id]
            x2, y2 = positions[tgt_id]
            line = QGraphicsLineItem(x1, y1, x2, y2)
            color = type_colors.get(rel_type, "#607D8B")
            line.setPen(QPen(QColor(color), 2))
            line.setZValue(-1)
            self._scene.addItem(line)

            mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
            rel_label = QGraphicsTextItem(rel.get("description", rel_type), self._scene)
            rel_label.setFont(QFont("Microsoft YaHei", 8))
            rel_label.setPos(mid_x, mid_y)
            rel_label.setDefaultTextColor(QColor(color))

        self._scene.setSceneRect(self._scene.itemsBoundingRect())

    def _on_view_mouse_press(self, event) -> None:
        item = self._view.itemAt(event.pos())
        if isinstance(item, QGraphicsEllipseItem):
            char_id = item.data(0)
            self._show_character_detail(char_id)
        QGraphicsView.mousePressEvent(self._view, event)

    def _show_character_detail(self, char_id: str) -> None:
        char = next((c for c in self._characters_cache if c.get("character_id") == char_id), None)
        if not char:
            return
        lines = [
            f"姓名：{char.get('name', '')}",
            f"身份：{char.get('identity', '')}",
            f"简介：{char.get('intro', '') or '无'}",
            f"关系：{char.get('relation', '') or '无'}",
            "",
            "相关关系：",
        ]
        for rel in self._relations_cache:
            src_id = rel.get("source_character_id", "")
            tgt_id = rel.get("target_character_id", "")
            if char_id in (src_id, tgt_id):
                other_id = tgt_id if src_id == char_id else src_id
                other = next((c for c in self._characters_cache if c.get("character_id") == other_id), None)
                other_name = other.get("name", other_id) if other else other_id
                lines.append(
                    f"  - {other_name}：{rel.get('relation_type', '')} / {rel.get('description', '')}"
                )
        self._detail_view.setPlainText("\n".join(lines))

    def _on_filter_changed(self, _state: int) -> None:
        self._active_types = {
            type_key for type_key, cb in self._type_checkboxes.items() if cb.isChecked()
        }
        self._render_graph()

    def _auto_extract(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        self._get_progress_timer().start("自动提取关系")
        self.extract_btn.setEnabled(False)
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            f"/api/relationships/{pid}/auto_extract",
            json={"user_ideas": self._ideas_input.toPlainText().strip()},
        )
        worker.result.connect(self._on_extract_done)
        worker.error.connect(self._on_extract_error)
        self._add_worker(worker)
        worker.start()

    def _on_extract_done(self, data: dict) -> None:
        self.extract_btn.setEnabled(True)
        self._get_progress_timer().stop()
        # 后端 AutoExtractResult：extracted 列表 + skipped 数
        added = len(data.get("extracted", []))
        self._progress_label.setText(f"自动提取完成，新增 {added} 条关系")
        self._load_graph()
        self._mark_unsaved()
        self.relationship_updated.emit()

    def _on_extract_error(self, msg: str) -> None:
        self.extract_btn.setEnabled(True)
        self._get_progress_timer().show_error(msg)
        QMessageBox.warning(self, "提取失败", msg)

    def _save_relations(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        # 后端按全量替换语义保存：空列表会清空库中全部关系，需二次确认防误删
        if not self._relations_cache:
            reply = QMessageBox.question(
                self,
                "确认",
                "当前关系列表为空，保存将清空该项目全部已有关系。确定继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        client = get_api_client()
        worker = ApiWorker(
            client.put,
            f"/api/relationships/{pid}",
            json={"relations": self._relations_cache},
        )
        worker.result.connect(self._on_save_done)
        worker.error.connect(self._on_save_error)
        self._add_worker(worker)
        worker.start()

    def _on_save_done(self, data: Any) -> None:
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")
        QMessageBox.information(self, "成功", "关系图谱保存成功")

    def _on_save_error(self, msg: str) -> None:
        QMessageBox.critical(self, "保存失败", msg)

    def _on_error(self, msg: str) -> None:
        self._progress_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)