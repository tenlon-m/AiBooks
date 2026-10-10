"""大纲编辑对话框 - 编辑卷名或章节名+梗概要点+场景编辑."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker


class OutlineEditDialog(QDialog):
    """编辑单卷或单章大纲条目的模态对话框."""

    def __init__(
        self,
        parent: QWidget | None = None,
        edit_type: str = "chapter",
        volume_name: str = "",
        chapter_name: str = "",
        synopsis: str = "",
        characters_appearing: str = "",
        chapter_id: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._edit_type = edit_type
        self._chapter_id = chapter_id
        self.setWindowTitle("编辑卷名" if edit_type == "volume" else "编辑章节大纲")
        self.setMinimumWidth(500)
        self._init_ui(volume_name, chapter_name, synopsis, characters_appearing)

    def _init_ui(
        self,
        volume_name: str,
        chapter_name: str,
        synopsis: str,
        characters_appearing: str,
    ) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        if self._edit_type == "volume":
            self._volume_name_edit = QLineEdit(volume_name)
            self._volume_name_edit.setMaxLength(50)
            form.addRow("卷名：", self._volume_name_edit)
        else:
            self._chapter_name_edit = QLineEdit(chapter_name)
            self._chapter_name_edit.setMaxLength(50)
            form.addRow("章节名：", self._chapter_name_edit)

            self._synopsis_edit = QPlainTextEdit(synopsis)
            self._synopsis_edit.setPlaceholderText("该章故事梗概要点（建议100-300字）")
            form.addRow("梗概要点：", self._synopsis_edit)

            self._appearing_edit = QLineEdit(characters_appearing)
            self._appearing_edit.setPlaceholderText("本章出场人物，用「、」分隔，如：张三、李四")
            form.addRow("出场人物：", self._appearing_edit)

            self._char_count_label = QLabel()
            form.addRow("", self._char_count_label)
            self._synopsis_edit.textChanged.connect(self._update_char_count)
            self._update_char_count()

        layout.addLayout(form)

        if self._edit_type == "chapter" and self._chapter_id:
            self._scene_area = SceneEditArea(self._chapter_id, self)
            layout.addWidget(self._scene_area)
        else:
            self._scene_area = None

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
        count = len(self._synopsis_edit.toPlainText())
        if 100 <= count <= 300:
            self._char_count_label.setText(f"{count}字 ✓")
            self._char_count_label.setStyleSheet("color: green;")
        else:
            self._char_count_label.setText(f"{count}字（建议100-300字）")
            self._char_count_label.setStyleSheet("color: #ff9800;")

    def get_data(self) -> dict:
        if self._edit_type == "volume":
            return {"volume_name": self._volume_name_edit.text().strip()}
        scenes_changes = (
            self._scene_area.get_changes() if self._scene_area else {"modified": [], "deleted": []}
        )
        return {
            "chapter_name": self._chapter_name_edit.text().strip(),
            "synopsis_points": self._synopsis_edit.toPlainText().strip(),
            "characters_appearing": self._appearing_edit.text().strip(),
            "scenes_changes": scenes_changes,
        }

class SceneEditArea(QWidget):
    """场景编辑区域 - 加载/编辑/删除场景，延迟保存."""

    def __init__(self, chapter_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chapter_id = chapter_id
        self._workers: list[ApiWorker] = []
        self._modified_scenes: list[dict] = []
        self._deleted_scene_ids: list[str] = []
        self._scenes_loaded: list[dict] = []
        self._init_ui()
        self._load_scenes()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        label = QLabel("场景编辑（修改/删除将在保存时提交）")
        label.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(label)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["序号", "场景目标", "出场角色", "关键事件", "情绪基调", "预计字数"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setMinimumSectionSize(60)
        for i, w in enumerate([50, 120, 100, 200, 80, 80]):
            self._table.setColumnWidth(i, w)
        layout.addWidget(self._table)

        btn_layout = QHBoxLayout()
        edit_btn = QPushButton("编辑场景")
        edit_btn.clicked.connect(self._edit_selected)
        delete_btn = QPushButton("删除场景")
        delete_btn.clicked.connect(self._delete_selected)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(delete_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._status_label)

    def _load_scenes(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/scene-outline/{self._chapter_id}/scenes")
        worker.result.connect(self._on_scenes_loaded)
        worker.error.connect(self._on_load_error)
        self._workers.append(worker)
        worker.start()

    def _on_scenes_loaded(self, data: list) -> None:
        self._table.setRowCount(0)
        self._scenes_loaded = []
        scenes = sorted(data, key=lambda s: s.get("scene_order", 0))
        for sc in scenes:
            row = self._table.rowCount()
            self._table.insertRow(row)
            vals = [
                str(sc.get("scene_order", "")),
                sc.get("goal", ""),
                sc.get("characters", ""),
                sc.get("key_event", ""),
                sc.get("mood", ""),
                str(sc.get("est_words", "")),
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setToolTip(v)
                self._table.setItem(row, col, item)
            self._table.item(row, 0).setData(Qt.ItemDataRole.UserRole, sc.get("scene_id", ""))
            self._scenes_loaded.append(sc)
        if not scenes:
            self._status_label.setText("该章暂无场景")
        else:
            self._status_label.setText(f"共 {len(scenes)} 个场景")

    def _on_load_error(self, msg: str) -> None:
        self._status_label.setText(f"场景加载失败：{msg}")

    def _edit_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择要编辑的场景")
            return
        scene_id = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole) or ""
        scene_data = {
            "goal": self._table.item(row, 1).text(),
            "characters": self._table.item(row, 2).text(),
            "key_event": self._table.item(row, 3).text(),
            "mood": self._table.item(row, 4).text(),
            "est_words": int(self._table.item(row, 5).text() or 0),
        }
        from src.ui.widgets.scene_outline_panel import _SceneEditDialog

        dialog = _SceneEditDialog(scene_data, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_data()
            self._table.item(row, 1).setText(new_data["goal"])
            self._table.item(row, 2).setText(new_data["characters"])
            self._table.item(row, 3).setText(new_data["key_event"])
            self._table.item(row, 4).setText(new_data["mood"])
            self._table.item(row, 5).setText(str(new_data["est_words"]))
            for col in range(6):
                self._table.item(row, col).setToolTip(self._table.item(row, col).text())
            self._modified_scenes.append({
                "scene_id": scene_id,
                "goal": new_data["goal"],
                "characters": new_data["characters"],
                "key_event": new_data["key_event"],
                "mood": new_data["mood"],
                "est_words": new_data["est_words"],
            })
            self._status_label.setText("场景已修改，保存时提交")

    def _delete_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择要删除的场景")
            return
        scene_id = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole) or ""
        reply = QMessageBox.question(
            self, "确认删除", "确定删除该场景？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.No:
            return
        self._table.removeRow(row)
        if scene_id:
            self._deleted_scene_ids.append(scene_id)
        self._status_label.setText("场景已标记删除，保存时提交")

    def get_changes(self) -> dict:
        return {"modified": self._modified_scenes, "deleted": self._deleted_scene_ids}