"""场景级大纲细化面板 - 列表展示章节场景+编辑/删除+生成触发."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker


class SceneOutlinePanel(QWidget):
    """场景级大纲细化面板.

    以表格展示当前章节的3-5个场景，每个场景包含：
    目标/出场角色/关键事件/情绪基调/预计字数。
    支持编辑与删除，并通过 generate_requested 信号通知父页面触发SSE生成。

    信号:
        scenes_loaded(int): 场景数量加载完成后发射
    """

    scenes_loaded = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._chapter_id: str | None = None
        self._has_unsaved_changes: bool = False
        self._init_ui()

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
        layout.setContentsMargins(6, 6, 6, 6)

        header = QLabel("场景级大纲细化")
        header.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px;")
        layout.addWidget(header)

        self._context_label = QLabel("未选择章节")
        self._context_label.setStyleSheet("color: #666; padding: 2px 4px;")
        layout.addWidget(self._context_label)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["序号", "场景目标", "出场角色", "关键事件", "情绪基调", "预计字数"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table, 1)

        btn_layout = QHBoxLayout()
        self._refresh_btn = QPushButton("刷新场景")
        self._refresh_btn.clicked.connect(self._load_scenes)
        self._edit_btn = QPushButton("编辑场景")
        self._edit_btn.clicked.connect(self._edit_selected)
        self._delete_btn = QPushButton("删除场景")
        self._delete_btn.setStyleSheet(
            "background-color: #f44336; color: white; padding: 4px 12px; border-radius: 3px;"
        )
        self._delete_btn.clicked.connect(self._delete_selected)
        btn_layout.addWidget(self._refresh_btn)
        btn_layout.addWidget(self._edit_btn)
        btn_layout.addWidget(self._delete_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._status_label)

    def set_chapter(self, chapter_id: str | None, chapter_title: str = "") -> None:
        """设置当前章节并加载场景列表."""
        self._chapter_id = chapter_id
        if chapter_id:
            self._context_label.setText(
                f"当前章节：{chapter_title or chapter_id[:8]}"
            )
            self._load_scenes()
        else:
            self._context_label.setText("未选择章节")
            self._table.setRowCount(0)

    def get_chapter_id(self) -> str | None:
        return self._chapter_id

    def _load_scenes(self) -> None:
        if not self._chapter_id:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.get, f"/api/scene-outline/{self._chapter_id}/scenes"
        )
        worker.result.connect(self._on_scenes_loaded)
        worker.error.connect(self._on_load_error)
        self._add_worker(worker)
        worker.start()

    def _on_scenes_loaded(self, data: dict | list) -> None:
        scenes = data if isinstance(data, list) else data.get("scenes", [])
        self._table.setRowCount(0)
        for i, scene in enumerate(scenes, 1):
            row = self._table.rowCount()
            self._table.insertRow(row)
            seq_item = QTableWidgetItem(str(i))
            seq_item.setData(Qt.ItemDataRole.UserRole, scene.get("scene_id"))
            self._table.setItem(row, 0, seq_item)
            self._table.setItem(row, 1, QTableWidgetItem(scene.get("goal", "")))
            self._table.setItem(row, 2, QTableWidgetItem(scene.get("characters", "")))
            self._table.setItem(row, 3, QTableWidgetItem(scene.get("key_event", "")))
            self._table.setItem(row, 4, QTableWidgetItem(scene.get("mood", "")))
            self._table.setItem(
                row, 5, QTableWidgetItem(str(scene.get("est_words", 0)))
            )
        self._status_label.setText(f"共 {len(scenes)} 个场景")
        self.scenes_loaded.emit(len(scenes))

    def _on_load_error(self, msg: str) -> None:
        if "404" in msg:
            self._table.setRowCount(0)
            self._status_label.setText("暂无场景，可点击「细化场景」生成")
        else:
            self._status_label.setText(f"加载失败：{msg}")

    def _edit_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选中要编辑的场景")
            return
        scene_id = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        current_data = {
            "scene_id": scene_id,
            "goal": self._table.item(row, 1).text(),
            "characters": self._table.item(row, 2).text(),
            "key_event": self._table.item(row, 3).text(),
            "mood": self._table.item(row, 4).text(),
            "est_words": int(self._table.item(row, 5).text() or 0),
        }
        dialog = _SceneEditDialog(current_data, self)
        if dialog.exec() != _SceneEditDialog.DialogCode.Accepted:
            return
        new_data = dialog.get_data()
        self._table.setItem(row, 1, QTableWidgetItem(new_data["goal"]))
        self._table.setItem(row, 2, QTableWidgetItem(new_data["characters"]))
        self._table.setItem(row, 3, QTableWidgetItem(new_data["key_event"]))
        self._table.setItem(row, 4, QTableWidgetItem(new_data["mood"]))
        self._table.setItem(
            row, 5, QTableWidgetItem(str(new_data["est_words"]))
        )
        self._has_unsaved_changes = True
        if scene_id:
            client = get_api_client()
            worker = ApiWorker(
                client.put,
                f"/api/scene-outline/{scene_id}",
                json=new_data,
            )
            worker.result.connect(lambda _: self._status_label.setText("场景已更新"))
            worker.error.connect(self._on_save_error)
            self._add_worker(worker)
            worker.start()

    def _delete_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选中要删除的场景")
            return
        scene_id = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定删除该场景？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._table.removeRow(row)
        if scene_id:
            client = get_api_client()
            worker = ApiWorker(
                client.delete, f"/api/scene-outline/{scene_id}"
            )
            worker.result.connect(lambda _: self._status_label.setText("场景已删除"))
            worker.error.connect(self._on_save_error)
            self._add_worker(worker)
            worker.start()

    def _on_save_error(self, msg: str) -> None:
        self._status_label.setText(f"保存失败：{msg}")
        QMessageBox.critical(self, "错误", msg)

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def clear(self) -> None:
        self._chapter_id = None
        self._table.setRowCount(0)
        self._context_label.setText("未选择章节")
        self._status_label.setText("就绪")
        self._has_unsaved_changes = False



class _SceneEditDialog(QDialog):
    """场景编辑对话框."""

    def __init__(self, scene_data: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene_data = scene_data
        self.setWindowTitle("编辑场景")
        self.setMinimumWidth(480)
        self._init_ui()
        self._fill_fields()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._goal_edit = QLineEdit()
        self._goal_edit.setPlaceholderText("该场景要达成的叙事目标")
        form.addRow("场景目标：", self._goal_edit)

        self._characters_edit = QLineEdit()
        self._characters_edit.setPlaceholderText("出场角色，逗号分隔")
        form.addRow("出场角色：", self._characters_edit)

        self._key_events_edit = QPlainTextEdit()
        self._key_events_edit.setMaximumHeight(80)
        form.addRow("关键事件：", self._key_events_edit)

        self._mood_edit = QLineEdit()
        self._mood_edit.setPlaceholderText("如：紧张、温馨、悲壮")
        form.addRow("情绪基调：", self._mood_edit)

        self._words_spin = QSpinBox()
        self._words_spin.setRange(100, 10000)
        self._words_spin.setSingleStep(100)
        form.addRow("预计字数：", self._words_spin)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _fill_fields(self) -> None:
        self._goal_edit.setText(self._scene_data.get("goal", ""))
        self._characters_edit.setText(self._scene_data.get("characters", ""))
        self._key_events_edit.setPlainText(self._scene_data.get("key_event", ""))
        self._mood_edit.setText(self._scene_data.get("mood", ""))
        self._words_spin.setValue(int(self._scene_data.get("est_words", 500)))

    def get_data(self) -> dict:
        return {
            "goal": self._goal_edit.text().strip(),
            "characters": self._characters_edit.text().strip(),
            "key_event": self._key_events_edit.toPlainText().strip(),
            "mood": self._mood_edit.text().strip(),
            "est_words": int(self._words_spin.value()),
        }