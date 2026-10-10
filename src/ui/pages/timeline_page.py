"""时间线管理页 - 横向时间轴可视化 + 节点CRUD + 拖拽排序 + 冲突检测."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context
from src.ui.widgets.timeline_node_edit_dialog import TimelineNodeEditDialog
from src.ui.widgets.timeline_widget import TimelineWidget


class TimelinePage(QWidget):
    timeline_saved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._has_unsaved_changes: bool = False
        self._nodes_cache: list[dict] = []
        self._init_ui()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def clear_page(self) -> None:
        self.timeline_widget.clear_nodes()
        self.status_label.clear()
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")
        self._nodes_cache = []

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _mark_unsaved(self) -> None:
        self._has_unsaved_changes = True
        self.save_btn.setStyleSheet("border: 2px solid #ff9800;")

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self._ideas_input.clear()
        if project_id:
            self._load_nodes()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("时间线管理")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        ideas_label = QLabel("时间线思路与想法（可选）：在此输入你对故事时间线的思路和想法")
        ideas_label.setStyleSheet("color: #555; padding: 4px 8px;")
        layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText("例如：以主角成长为主线，先铺垫背景再展开主线冲突……")
        self._ideas_input.setMaximumHeight(80)
        self._ideas_input.setStyleSheet("padding: 4px;")
        layout.addWidget(self._ideas_input)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("时间轴（拖拽节点可调整顺序，双击节点编辑）："))
        self.timeline_widget = TimelineWidget()
        self.timeline_widget.setMinimumHeight(200)
        self.timeline_widget.order_changed.connect(self._on_order_changed)
        self.timeline_widget.node_double_clicked.connect(self._on_node_double_clicked)
        layout.addWidget(self.timeline_widget, 1)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("新增节点")
        self.add_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;")
        self.add_btn.clicked.connect(self._add_node)
        self.delete_btn = QPushButton("删除选中")
        self.delete_btn.setStyleSheet("background-color: #f44336; color: white; padding: 6px 16px; border-radius: 4px;")
        self.delete_btn.clicked.connect(self._delete_node)
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self._save_all)
        self.check_btn = QPushButton("冲突检测")
        self.check_btn.clicked.connect(self._check_conflicts)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._load_nodes)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.check_btn)
        btn_layout.addWidget(self.refresh_btn)
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

    def _load_nodes(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/timeline/{pid}")
        worker.result.connect(self._on_nodes_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_nodes_loaded(self, data: dict | list) -> None:
        nodes = data.get("nodes", []) if isinstance(data, dict) else data
        self._nodes_cache = nodes
        self.timeline_widget.set_nodes(nodes)
        conflicts = data.get("conflicts", []) if isinstance(data, dict) else []
        if conflicts:
            self.timeline_widget.set_conflicts(conflicts)
            self.status_label.setText(f"共 {len(nodes)} 个节点，{len(conflicts)} 个冲突")
        else:
            self.status_label.setText(f"共 {len(nodes)} 个节点")

    def _on_order_changed(self, new_order: list[str]) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        self._progress_label.setText("正在保存排序...")
        client = get_api_client()
        # 后端 TimelineReorderRequest 需要 node_orders: [{node_id, node_order}]
        node_orders = [
            {"node_id": nid, "node_order": idx}
            for idx, nid in enumerate(new_order)
        ]
        worker = ApiWorker(
            client.post,
            f"/api/timeline/{pid}/reorder",
            json={"node_orders": node_orders},
        )
        worker.result.connect(self._on_reorder_done)
        worker.error.connect(self._on_reorder_error)
        self._workers.append(worker)
        worker.start()

    def _on_reorder_done(self, data: dict) -> None:
        conflicts = data.get("conflicts", [])
        if conflicts:
            self.timeline_widget.set_conflicts(conflicts)
            self._progress_label.setText(f"检测到 {len(conflicts)} 个时间线冲突")
            QMessageBox.warning(self, "时间线冲突", f"检测到 {len(conflicts)} 个节点存在时间线冲突，已高亮显示")
        else:
            self.timeline_widget.set_conflicts([])
            self._progress_label.setText("排序已保存")
        self._mark_unsaved()

    def _on_reorder_error(self, msg: str) -> None:
        self._progress_label.setText(f"排序失败：{msg}")
        QMessageBox.critical(self, "错误", f"排序保存失败：{msg}")

    def _on_node_double_clicked(self, node_id: str) -> None:
        node = next((n for n in self._nodes_cache if n.get("node_id") == node_id), None)
        if not node:
            return
        dialog = TimelineNodeEditDialog(node, self)
        if dialog.exec() == TimelineNodeEditDialog.DialogCode.Accepted:
            data = dialog.get_data()
            self._update_node(node_id, data)

    def _add_node(self) -> None:
        dialog = TimelineNodeEditDialog(parent=self)
        if dialog.exec() == TimelineNodeEditDialog.DialogCode.Accepted:
            data = dialog.get_data()
            pid = self._get_project_id()
            if not pid:
                return
            payload = {"project_id": pid, **data}
            client = get_api_client()
            worker = ApiWorker(client.post, "/api/timeline", json=payload)
            worker.result.connect(lambda _: self._on_node_saved("新增"))
            worker.error.connect(self._on_error)
            self._workers.append(worker)
            worker.start()

    def _update_node(self, node_id: str, data: dict) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.put, f"/api/timeline/{pid}/{node_id}", json=data
        )
        worker.result.connect(lambda _: self._on_node_saved("更新"))
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _delete_node(self) -> None:
        order = self.timeline_widget.get_node_order()
        if not order:
            QMessageBox.warning(self, "提示", "暂无节点可删除")
            return
        node_id, ok = self._select_node_to_delete(order)
        if not ok or not node_id:
            return
        reply = QMessageBox.question(
            self, "确认删除", "确定删除选中的时间线节点？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.delete, f"/api/timeline/{pid}/{node_id}")
        worker.result.connect(lambda _: self._on_node_saved("删除"))
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _select_node_to_delete(self, order: list[str]) -> tuple[str, bool]:

        items = [f"{i+1}. {nid}" for i, nid in enumerate(order)]
        choice, ok = QInputDialog.getItem(
            self, "选择节点", "选择要删除的节点：", items, 0, False
        )
        if not ok or not choice:
            return "", False
        idx = int(choice.split(".")[0]) - 1
        return order[idx], True

    def _on_node_saved(self, action: str) -> None:
        self._progress_label.setText(f"节点{action}完成")
        self._load_nodes()
        self._mark_unsaved()
        self.timeline_saved.emit()

    def _save_all(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        new_order = self.timeline_widget.get_node_order()
        client = get_api_client()
        node_orders = [
            {"node_id": nid, "node_order": idx}
            for idx, nid in enumerate(new_order)
        ]
        worker = ApiWorker(
            client.post,
            f"/api/timeline/{pid}/reorder",
            json={"node_orders": node_orders},
        )
        worker.result.connect(self._on_save_done)
        worker.error.connect(self._on_save_error)
        self._workers.append(worker)
        worker.start()

    def _on_save_done(self, data: dict) -> None:
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")
        conflicts = data.get("conflicts", [])
        if conflicts:
            self.timeline_widget.set_conflicts(conflicts)
            self.status_label.setText(f"保存完成，{len(conflicts)} 个冲突")
        else:
            self.status_label.setText("保存完成")
        QMessageBox.information(self, "成功", "时间线保存成功")

    def _on_save_error(self, msg: str) -> None:
        QMessageBox.critical(self, "保存失败", f"保存失败：{msg}")

    def _check_conflicts(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        self._progress_label.setText("冲突检测中...")
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/timeline/{pid}/conflicts")
        worker.result.connect(self._on_check_done)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_check_done(self, data: dict) -> None:
        conflicts = data.get("conflicts", []) if isinstance(data, dict) else []
        self.timeline_widget.set_conflicts(conflicts)
        if conflicts:
            self._progress_label.setText(f"检测到 {len(conflicts)} 个冲突")
            QMessageBox.warning(self, "冲突检测", f"检测到 {len(conflicts)} 个时间线冲突，已高亮显示")
        else:
            self._progress_label.setText("无冲突")

    def _on_error(self, msg: str) -> None:
        self._progress_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)