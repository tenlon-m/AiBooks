"""物品管理页 - 物品清单增删改查 + 全书一致性检查.

物品此前只能由「命名生成器 → 导入到物品管理」与撰写时自动提取产生，
无法集中维护；本页补齐了手动增删改查与一致性检查入口。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context

# 常见物品类型，仅用于下拉填充，可手动输入其它值
_ITEM_TYPE_PRESETS = ["武器", "防具", "丹药", "功法", "法宝", "材料", "书籍", "信物", "未知"]


class _ItemEditDialog(QDialog):
    """新增 / 编辑物品."""

    def __init__(self, item: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑物品" if item else "新增物品")
        self.setMinimumWidth(420)
        self._init_ui(item)

    def _init_ui(self, item: dict | None) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_input = QLineEdit()
        self._name_input.setMaxLength(30)
        self._name_input.setPlaceholderText("必填，同项目内不可重名")
        form.addRow("名称：", self._name_input)

        self._type_combo = QComboBox()
        self._type_combo.setEditable(True)
        self._type_combo.addItems(_ITEM_TYPE_PRESETS)
        form.addRow("类型：", self._type_combo)

        self._attrs_input = QLineEdit()
        self._attrs_input.setPlaceholderText("关键属性，例如：可增幅三成灵力")
        form.addRow("关键属性：", self._attrs_input)

        self._owner_input = QLineEdit()
        self._owner_input.setPlaceholderText("持有者姓名，可留空")
        form.addRow("持有者：", self._owner_input)

        vol_ch_layout = QHBoxLayout()
        self._volume_spin = QSpinBox()
        self._volume_spin.setRange(1, 999)
        self._chapter_spin = QSpinBox()
        self._chapter_spin.setRange(1, 9999)
        vol_ch_layout.addWidget(QLabel("卷"))
        vol_ch_layout.addWidget(self._volume_spin)
        vol_ch_layout.addWidget(QLabel("章"))
        vol_ch_layout.addWidget(self._chapter_spin)
        vol_ch_layout.addStretch()
        form.addRow("首次出场：", vol_ch_layout)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if item:
            self._name_input.setText(item.get("name", ""))
            self._type_combo.setCurrentText(item.get("item_type", ""))
            self._attrs_input.setText(item.get("key_attrs") or "")
            self._owner_input.setText(item.get("owner_character") or "")
            self._volume_spin.setValue(int(item.get("first_appear_volume", 1) or 1))
            self._chapter_spin.setValue(int(item.get("first_appear_chapter", 1) or 1))

    def _on_accept(self) -> None:
        if not self._name_input.text().strip():
            QMessageBox.warning(self, "提示", "请填写物品名称")
            return
        if not self._type_combo.currentText().strip():
            QMessageBox.warning(self, "提示", "请填写物品类型")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "name": self._name_input.text().strip(),
            "item_type": self._type_combo.currentText().strip(),
            "key_attrs": self._attrs_input.text().strip() or None,
            "owner_character": self._owner_input.text().strip() or None,
            "first_appear_volume": self._volume_spin.value(),
            "first_appear_chapter": self._chapter_spin.value(),
        }


class ItemPage(QWidget):
    """物品管理页."""

    items_updated = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._items_cache: list[dict] = []
        self._init_ui()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("物品管理")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        tip = QLabel(
            "集中维护全书物品（武器 / 丹药 / 功法 / 法宝等）。\n"
            "撰写时 AI 会自动提取新物品入库，也可从「命名生成器 → 导入到物品管理」批量导入。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #555; padding: 4px;")
        layout.addWidget(tip)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["名称", "类型", "关键属性", "持有者", "首次出场"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit_item)
        layout.addWidget(self.table, 1)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("新增物品")
        self.add_btn.setStyleSheet(
            "background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self.add_btn.clicked.connect(self._add_item)
        self.edit_btn = QPushButton("编辑选中")
        self.edit_btn.clicked.connect(self._edit_item)
        self.delete_btn = QPushButton("删除选中")
        self.delete_btn.clicked.connect(self._delete_item)
        self.check_btn = QPushButton("一致性检查")
        self.check_btn.clicked.connect(self._check_consistency)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._load_items)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.check_btn)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._progress_label)

    # ------------------------------------------------------------------ 基础
    def _get_project_id(self) -> str | None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return None
        return ctx.project_id

    def clear_page(self) -> None:
        self.table.setRowCount(0)
        self._items_cache = []
        self.status_label.clear()
        self._progress_label.clear()

    def has_unsaved_changes(self) -> bool:
        return False

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self.clear_page()
        if project_id:
            self._load_items()

    # ------------------------------------------------------------------ 数据
    def _load_items(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/items/{pid}")
        worker.result.connect(self._on_items_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_items_loaded(self, items: list) -> None:
        self._items_cache = list(items or [])
        self.table.setRowCount(0)
        for it in self._items_cache:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(it.get("name", ""))
            name_item.setData(Qt.ItemDataRole.UserRole, it.get("item_id", ""))
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(it.get("item_type", "")))
            self.table.setItem(row, 2, QTableWidgetItem(it.get("key_attrs") or ""))
            self.table.setItem(row, 3, QTableWidgetItem(it.get("owner_character") or ""))
            self.table.setItem(
                row, 4,
                QTableWidgetItem(
                    f"第{it.get('first_appear_volume', 1)}卷"
                    f"第{it.get('first_appear_chapter', 1)}章"
                ),
            )
        self.status_label.setText(f"共 {len(self._items_cache)} 个物品")

    def _selected_item(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        item_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not item_id:
            return None
        return next((i for i in self._items_cache if i.get("item_id") == item_id), None)

    # ------------------------------------------------------------------ 操作
    def _add_item(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        dialog = _ItemEditDialog(None, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        payload = dialog.get_data()
        payload["project_id"] = pid
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/items/", json=payload)
        worker.result.connect(self._on_write_done)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _edit_item(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        item = self._selected_item()
        if not item:
            QMessageBox.information(self, "提示", "请先选中一个物品（双击行也可编辑）")
            return
        dialog = _ItemEditDialog(item, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.put, f"/api/items/{item['item_id']}", json=dialog.get_data()
        )
        worker.result.connect(self._on_write_done)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _delete_item(self) -> None:
        item = self._selected_item()
        if not item:
            QMessageBox.information(self, "提示", "请先选中一个物品")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除物品「{item.get('name', '')}」？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.delete, f"/api/items/{item['item_id']}")
        worker.result.connect(self._on_write_done)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_write_done(self, _data: object) -> None:
        self._progress_label.setText("操作成功")
        self._load_items()
        self.items_updated.emit()

    def _check_consistency(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        self._progress_label.setText("一致性检查中...")
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/items/{pid}/consistency")
        worker.result.connect(self._on_consistency_checked)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_consistency_checked(self, data: dict) -> None:
        problems = data.get("problems", []) if isinstance(data, dict) else []
        if not problems:
            self._progress_label.setText("一致性检查通过，未发现问题")
            QMessageBox.information(self, "检查结果", "物品全书一致性检查通过，未发现问题")
            return
        self._progress_label.setText(f"发现 {len(problems)} 处问题")
        QMessageBox.warning(
            self, "检查结果",
            f"发现 {len(problems)} 处问题：\n" + "\n".join(f"  - {p}" for p in problems),
        )

    def _on_error(self, msg: str) -> None:
        self._progress_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)
