"""大纲管理页 - AI生成/编辑/保存/清空大纲 + 前置条件校验 + 未保存提示 + 场景级细化."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class _DraggableOutlineTree(QTreeWidget):
    """支持內部拖拽排序的大綱樹.

    啟用 InternalMove 後，dropEvent 完成時發射 order_changed 信號，
    供父頁面收集新順序並調用後端 reorder 接口。
    """

    order_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        self.order_changed.emit()

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.outline_batch_controller import OutlineBatchController
from src.ui.outline_check_controller import OutlineCheckController
from src.ui.pages.outline_edit_dialog import OutlineEditDialog
from src.ui.project_context import get_project_context
from src.ui.sse_worker import OutlineRepairSseWorker, SsePostWorker
from src.ui.widgets.character_progress_timer import CharacterProgressTimer
from src.ui.widgets.outline_check_report_dialog import OutlineCheckReportDialog


class OutlinePage(QWidget):
    """大纲管理页面."""

    outline_saved = Signal()
    scene_refined = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._progress_timer: CharacterProgressTimer | None = None
        self._has_unsaved_changes: bool = False
        self._project_id: str | None = None
        self._batch_controller: OutlineBatchController | None = None
        self._check_controller: OutlineCheckController | None = None
        self._scene_sse_worker: SsePostWorker | None = None
        self._batch_scene_sse_worker: SsePostWorker | None = None
        self._batch_scene_results: list[dict] = []
        self._batch_scene_total: int = 0
        self._batch_scene_completed: int = 0
        self._batch_scene_failed: list[dict] = []
        self._repair_sse_worker: OutlineRepairSseWorker | None = None
        self._layer_mode: bool = False
        self._story_unit_tree_data: dict | None = None
        self._init_ui()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def _get_progress_timer(self) -> CharacterProgressTimer:
        if self._progress_timer is None:
            self._progress_timer = CharacterProgressTimer(self.window().statusBar())
        return self._progress_timer

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QLabel("大纲管理")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(header)

        ideas_label = QLabel("大纲思路与想法（可选）：在此输入你对大纲的思路和想法，AI 生成大纲时会充分参考")
        ideas_label.setStyleSheet("color: #555; padding: 4px 8px;")
        layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText("例如：第一卷以主角成长为主线，第二卷进入封神大战，第三卷收束结局……")
        self._ideas_input.setMaximumHeight(80)
        self._ideas_input.setStyleSheet("padding: 4px;")
        layout.addWidget(self._ideas_input)

        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self._status_label)

        self._outline_tree = _DraggableOutlineTree()
        self._outline_tree.setHeaderLabels(["卷/章", "名称", "出场人物", "梗概要点预览", "场景数量"])
        self._outline_tree.setColumnWidth(0, 120)
        self._outline_tree.setColumnWidth(1, 200)
        self._outline_tree.setColumnWidth(2, 160)
        self._outline_tree.setColumnWidth(3, 200)
        self._outline_tree.setColumnWidth(4, 90)
        self._outline_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._outline_tree.order_changed.connect(self._on_outline_order_changed)
        self._outline_tree.itemDoubleClicked.connect(lambda *_: self._edit_selected())
        layout.addWidget(self._outline_tree)

        btn_layout = QHBoxLayout()
        self._layer_mode_btn = QPushButton("分层模式")
        self._layer_mode_btn.setToolTip("切换雪花式5级分层大纲模式（分卷→大篇→中篇→小篇→章纲）")
        self._layer_mode_btn.setCheckable(True)
        self._layer_mode_btn.setStyleSheet("background-color: #607d8b; color: white; padding: 6px 16px; border-radius: 4px;")
        self._layer_mode_btn.clicked.connect(self._on_layer_mode_toggle)
        self._gen_volume_btn = QPushButton("生成分卷层")
        self._gen_volume_btn.setToolTip("生成雪花式分卷层（最高层），需先完成梗概/世界观/人物")
        self._gen_volume_btn.setStyleSheet("background-color: #e65100; color: white; padding: 6px 16px; border-radius: 4px;")
        self._gen_volume_btn.clicked.connect(self._generate_volume_layer)
        self._gen_child_btn = QPushButton("生成下层")
        self._gen_child_btn.setToolTip("选中某单元后生成其下一层（大篇→中篇→小篇）")
        self._gen_child_btn.setStyleSheet("background-color: #f57c00; color: white; padding: 6px 16px; border-radius: 4px;")
        self._gen_child_btn.clicked.connect(self._generate_child_layer)
        self._batch_btn = QPushButton("AI分批生成大纲")
        self._batch_btn.setToolTip("按每批若干章依次生成，每批完成即时显示，避免整本一次生成超时")
        self._batch_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;")
        self._batch_btn.clicked.connect(self._ai_generate_batch)
        self._pause_btn = QPushButton("暂停")
        self._pause_btn.setEnabled(False)
        self._pause_btn.clicked.connect(self._on_batch_pause)
        self._resume_btn = QPushButton("续写")
        self._resume_btn.setEnabled(False)
        self._resume_btn.clicked.connect(self._on_batch_resume)
        self._check_btn = QPushButton("校验一致性")
        self._check_btn.setToolTip("分批校验大纲是否符合故事梗概/世界观，以及人物出场逻辑，输出可复制报告")
        self._check_btn.clicked.connect(self._check_consistency)
        self._generate_btn = QPushButton("AI整体生成大纲")
        self._generate_btn.setToolTip("一次性生成全书大纲，章节较多时容易超时，建议使用分批生成")
        self._generate_btn.clicked.connect(self._ai_generate_outline)
        self._save_btn = QPushButton("保存大纲")
        self._save_btn.clicked.connect(self._save_outline)
        self._edit_btn = QPushButton("编辑选中")
        self._edit_btn.clicked.connect(self._edit_selected)
        self._fill_appearing_btn = QPushButton("一键填充出场人物")
        self._fill_appearing_btn.setToolTip("对出场人物为空的章节，AI 智能匹配已确认人物清单（含代词/简称/别名），跳过已填写章节")
        self._fill_appearing_btn.setStyleSheet("background-color: #00897b; color: white; padding: 6px 16px; border-radius: 4px;")
        self._fill_appearing_btn.clicked.connect(self._fill_appearing)
        self._refine_scene_btn = QPushButton("细化场景")
        self._refine_scene_btn.setToolTip("选中章节后，AI生成场景级大纲（目标/角色/事件/情绪/字数）")
        self._refine_scene_btn.setStyleSheet(
            "background-color: #9c27b0; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._refine_scene_btn.clicked.connect(self._refine_scenes)
        self._batch_refine_scene_btn = QPushButton("批量细化场景")
        self._batch_refine_scene_btn.setToolTip("对所有未生成场景的章节逐章 AI 细化，可暂停/续写")
        self._batch_refine_scene_btn.setStyleSheet(
            "background-color: #7b1fa2; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._batch_refine_scene_btn.clicked.connect(self._batch_refine_scenes)
        self._batch_scene_pause_btn = QPushButton("暂停批量场景")
        self._batch_scene_pause_btn.setEnabled(False)
        self._batch_scene_pause_btn.clicked.connect(self._on_batch_scene_pause)
        self._delete_btn = QPushButton("清空大纲")
        self._delete_btn.clicked.connect(self._delete_outline)
        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.setToolTip("重新加载大纲列表中的最新生成内容")
        self._refresh_btn.setStyleSheet("background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;")
        self._refresh_btn.clicked.connect(self._load_outline)

        btn_layout.addWidget(self._layer_mode_btn)
        btn_layout.addWidget(self._gen_volume_btn)
        btn_layout.addWidget(self._gen_child_btn)
        btn_layout.addWidget(self._batch_btn)
        btn_layout.addWidget(self._pause_btn)
        btn_layout.addWidget(self._resume_btn)
        btn_layout.addWidget(self._check_btn)
        btn_layout.addWidget(self._generate_btn)
        btn_layout.addWidget(self._save_btn)
        btn_layout.addWidget(self._edit_btn)
        btn_layout.addWidget(self._fill_appearing_btn)
        btn_layout.addWidget(self._refine_scene_btn)
        btn_layout.addWidget(self._batch_refine_scene_btn)
        btn_layout.addWidget(self._batch_scene_pause_btn)
        btn_layout.addWidget(self._delete_btn)
        btn_layout.addWidget(self._refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._batch_progress_label = QLabel()
        self._batch_progress_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._batch_progress_label)

        self._check_progress_label = QLabel()
        self._check_progress_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._check_progress_label)

        self._batch_scene_progress_label = QLabel()
        self._batch_scene_progress_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._batch_scene_progress_label)

        self._repair_progress_label = QLabel()
        self._repair_progress_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._repair_progress_label)
        self._repair_pause_btn = QPushButton("暂停修复")
        self._repair_pause_btn.setEnabled(False)
        self._repair_pause_btn.clicked.connect(self._on_repair_pause)
        repair_btn_layout = QHBoxLayout()
        repair_btn_layout.addWidget(self._repair_pause_btn)
        repair_btn_layout.addStretch()
        layout.addLayout(repair_btn_layout)


    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self._project_id = project_id
        self._load_outline()

    def _load_outline(self) -> None:
        if not self._project_id:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/outlines/{self._project_id}")
        worker.result.connect(self._on_load_done)
        worker.error.connect(self._on_load_error)
        self._workers.append(worker)
        worker.start()

    def _on_load_done(self, data: dict | None) -> None:
        self._outline_tree.clear()
        if not data:
            self._status_label.setText("暂无大纲，可点击AI生成大纲")
            return
        for vol in data.get("volumes", []):
            vol_scene_total = sum(ch.get("scene_count", 0) for ch in vol.get("chapters", []))
            vol_item = QTreeWidgetItem([
                f"第{vol['volume_no']}卷",
                vol.get("volume_name", ""),
                "",
                "",
                str(vol_scene_total),
            ])
            vol_item.setData(0, Qt.UserRole, {"type": "volume", "volume_no": vol["volume_no"]})
            for ch in vol.get("chapters", []):
                synopsis = ch.get("synopsis_points", "")
                appearing = ch.get("characters_appearing", "") or ""
                preview = synopsis[:20] + "..." if len(synopsis) > 20 else synopsis
                scene_count = ch.get("scene_count", 0)
                ch_item = QTreeWidgetItem([
                    f"  第{ch['chapter_no']}章",
                    ch.get("chapter_name", ""),
                    appearing,
                    preview,
                    str(scene_count),
                ])
                ch_item.setTextAlignment(4, Qt.AlignmentFlag.AlignCenter)
                ch_item.setToolTip(3, synopsis)
                ch_item.setData(0, Qt.UserRole, {
                    "type": "chapter",
                    "chapter_id": ch.get("chapter_id", ""),
                    "volume_no": vol["volume_no"],
                    "chapter_no": ch["chapter_no"],
                    "synopsis_points": synopsis,
                    "characters_appearing": appearing,
                })
                vol_item.addChild(ch_item)
            self._outline_tree.addTopLevelItem(vol_item)
        self._outline_tree.expandAll()
        self._status_label.setText(f"大纲状态：{data.get('gen_status', '')}")

    def _on_load_error(self, msg: str) -> None:
        self._status_label.setText(f"加载大纲失败: {msg}")

    def _on_layer_mode_toggle(self) -> None:
        self._layer_mode = self._layer_mode_btn.isChecked()
        if self._layer_mode:
            self._layer_mode_btn.setText("分层模式(开)")
            self._gen_volume_btn.setEnabled(True)
            self._gen_child_btn.setEnabled(True)
            self._load_story_unit_tree()
        else:
            self._layer_mode_btn.setText("分层模式")
            self._gen_volume_btn.setEnabled(False)
            self._gen_child_btn.setEnabled(False)
            self._load_outline()

    def _load_story_unit_tree(self) -> None:
        if not self._project_id:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/story-units/tree/{self._project_id}")
        worker.result.connect(self._on_story_unit_tree_loaded)
        worker.error.connect(self._on_story_unit_tree_error)
        self._workers.append(worker)
        worker.start()

    def _on_story_unit_tree_loaded(self, data: dict | None) -> None:
        self._story_unit_tree_data = data
        self._outline_tree.clear()
        if not data or not data.get("units"):
            self._status_label.setText("分层模式：暂无分层数据，可点击「生成分卷层」开始")
            return
        units = data.get("units", [])
        unit_map: dict[str | None, list[dict]] = {}
        for u in units:
            unit_map.setdefault(u.get("parent_unit_id"), []).append(u)
        level_label = {"volume": "分卷", "major": "大篇", "middle": "中篇", "minor": "小篇"}
        for vol in unit_map.get(None, []):
            vol_item = QTreeWidgetItem([
                f"【分卷】",
                vol.get("unit_name", ""),
                "",
                vol.get("synopsis", "")[:20] + "..." if len(vol.get("synopsis", "")) > 20 else vol.get("synopsis", ""),
                str(vol.get("chapter_count", 0)),
            ])
            vol_item.setData(0, Qt.UserRole, {"type": "story_unit", "unit": vol})
            self._add_child_units(vol_item, vol.get("story_unit_id"), unit_map, level_label)
            self._outline_tree.addTopLevelItem(vol_item)
        self._outline_tree.expandAll()
        self._status_label.setText(f"分层模式：共 {len(units)} 个故事单元")

    def _add_child_units(
        self,
        parent_item: QTreeWidgetItem,
        parent_unit_id: str,
        unit_map: dict[str | None, list[dict]],
        level_label: dict,
    ) -> None:
        for u in unit_map.get(parent_unit_id, []):
            lt = u.get("level_type", "")
            label = level_label.get(lt, lt)
            synopsis = u.get("synopsis", "")
            preview = synopsis[:20] + "..." if len(synopsis) > 20 else synopsis
            child_item = QTreeWidgetItem([
                f"  【{label}】",
                u.get("unit_name", ""),
                u.get("narrative_duty", "")[:20] if u.get("narrative_duty") else "",
                preview,
                str(u.get("chapter_count", 0)),
            ])
            child_item.setData(0, Qt.UserRole, {"type": "story_unit", "unit": u})
            child_item.setToolTip(3, synopsis)
            parent_item.addChild(child_item)
            self._add_child_units(child_item, u.get("story_unit_id"), unit_map, level_label)

    def _on_story_unit_tree_error(self, msg: str) -> None:
        self._status_label.setText(f"加载分层数据失败: {msg}")

    def _generate_volume_layer(self) -> None:
        if not self._project_id:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            "/api/story-units/generate-volume-layer",
            json={"project_id": self._project_id, "parent_unit_id": None, "level_type": "volume"},
        )
        worker.result.connect(self._on_volume_layer_done)
        worker.error.connect(self._on_layer_error)
        self._workers.append(worker)
        worker.start()
        self._status_label.setText("正在生成分卷层...")

    def _on_volume_layer_done(self, data: list) -> None:
        self._status_label.setText(f"分卷层生成完成，共 {len(data)} 个分卷")
        self._load_story_unit_tree()

    def _generate_child_layer(self) -> None:
        if not self._project_id:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        current = self._outline_tree.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选择一个故事单元")
            return
        item_data = current.data(0, Qt.UserRole)
        if not item_data or item_data.get("type") != "story_unit":
            QMessageBox.warning(self, "提示", "请选择一个故事单元节点")
            return
        unit = item_data.get("unit", {})
        parent_unit_id = unit.get("story_unit_id", "")
        level_type = unit.get("level_type", "")
        child_map = {"volume": "major", "major": "middle", "middle": "minor"}
        child_level = child_map.get(level_type)
        if not child_level:
            QMessageBox.information(self, "提示", "该单元已是最低层（小篇），无需再生成下层")
            return
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            "/api/story-units/generate-layer",
            json={
                "project_id": self._project_id,
                "parent_unit_id": parent_unit_id,
                "level_type": child_level,
            },
        )
        worker.result.connect(self._on_child_layer_done)
        worker.error.connect(self._on_layer_error)
        self._workers.append(worker)
        worker.start()
        self._status_label.setText(f"正在生成{child_level}层...")

    def _on_child_layer_done(self, data: list) -> None:
        self._status_label.setText(f"下层生成完成，共 {len(data)} 个子单元")
        self._load_story_unit_tree()

    def _on_layer_error(self, msg: str) -> None:
        self._status_label.setText(f"分层生成失败: {msg}")
        QMessageBox.warning(self, "分层生成失败", msg)

    def _on_outline_order_changed(self) -> None:
        """拖拽完成後收集新順序並調用後端 reorder 接口.

        支持單章與多章批量拖拽：按樹中當前順序收集 (volume_no, chapter_no) 列表。
        後端返回時間線衝突時彈出告警詢問是否保留調整。
        """
        if not self._project_id:
            return
        if self._outline_tree.topLevelItemCount() == 0:
            return
        new_order: list[dict] = []
        for i in range(self._outline_tree.topLevelItemCount()):
            vol_item = self._outline_tree.topLevelItem(i)
            vol_data = vol_item.data(0, Qt.UserRole)
            if not vol_data:
                continue
            volume_no = vol_data.get("volume_no", i + 1)
            for j in range(vol_item.childCount()):
                ch_item = vol_item.child(j)
                ch_data = ch_item.data(0, Qt.UserRole)
                if not ch_data:
                    continue
                new_order.append({
                    "chapter_id": ch_data.get("chapter_id", ""),
                    "volume_no": volume_no,
                    "chapter_no": ch_data.get("chapter_no", j + 1),
                    "new_volume_no": volume_no,
                    "new_chapter_no": j + 1,
                })
        if not new_order:
            return
        self._status_label.setText("正在保存拖拽排序...")
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            "/api/outline/reorder",
            # 后端 OutlineReorderRequest.new_order：[{chapter_id, volume_no, chapter_no}]
            # 其中 volume_no/chapter_no 为目标位置
            json={
                "project_id": self._project_id,
                "new_order": [
                    {
                        "chapter_id": item["chapter_id"],
                        "volume_no": item["new_volume_no"],
                        "chapter_no": item["new_chapter_no"],
                    }
                    for item in new_order
                ],
            },
        )
        worker.result.connect(self._on_reorder_done)
        worker.error.connect(self._on_reorder_error)
        self._workers.append(worker)
        worker.start()

    def _on_reorder_done(self, data: dict) -> None:
        timeline_conflict = data.get("timeline_conflict", False)
        if timeline_conflict:
            self._status_label.setText("檢測到時間線約束違反")
            reply = QMessageBox.question(
                self,
                "時間線衝突",
                "檢測到時間線約束違反，是否保留調整？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                # 不保留：重新加載後端順序
                self._load_outline()
                return
            # 保留：仍標記為未保存，等待用戶保存
            self._has_unsaved_changes = True
            self._status_label.setText("已保留拖拽調整（時間線有衝突，請保存後生效）")
        else:
            self._has_unsaved_changes = True
            self._status_label.setText("排序已更新，請保存大綱以生效")
        self.outline_saved.emit()

    def _on_reorder_error(self, msg: str) -> None:
        self._status_label.setText(f"排序失敗：{msg}")
        QMessageBox.warning(self, "排序失敗", f"拖拽排序保存失敗：{msg}\n已恢復原順序")
        self._load_outline()

    def _ai_generate_outline(self) -> None:
        if not self._project_id:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return

        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/outlines/{self._project_id}")
        worker.result.connect(lambda data: self._check_existing_and_generate(data))
        worker.error.connect(lambda msg: self._do_generate())
        self._workers.append(worker)
        worker.start()

    def _check_existing_and_generate(self, existing: dict | None) -> None:
        if existing:
            reply = QMessageBox.question(
                self, "确认覆盖",
                "已存在大纲，重新生成将覆盖当前大纲内容，是否继续？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return
        self._do_generate()

    def _do_generate(self) -> None:
        timer = self._get_progress_timer()
        timer.start("AI生成大纲")
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            f"/api/outlines/{self._project_id}/generate",
            json={
                "force_overwrite": True,
                "user_ideas": self._ideas_input.toPlainText().strip(),
            },
        )
        worker.result.connect(self._on_generate_done)
        worker.error.connect(self._on_generate_error)
        self._workers.append(worker)
        worker.start()

    def _on_generate_done(self, data: dict) -> None:
        timer = self._get_progress_timer()
        timer.stop()
        self._on_load_done(data)
        self.outline_saved.emit()
        self._has_unsaved_changes = False
        self._status_label.setText("大纲生成完成")

    def _on_generate_error(self, msg: str) -> None:
        timer = self._get_progress_timer()
        timer.show_error(msg)
        QMessageBox.warning(self, "生成失败", f"AI生成大纲失败：{msg}")

    def _get_batch_controller(self) -> OutlineBatchController:
        """懒加载分批生成控制器（复用实例，start 时重置内部状态）."""
        if self._batch_controller is None:
            controller = OutlineBatchController(self)
            controller.batch_done.connect(self._on_batch_done)
            controller.progress.connect(self._on_batch_progress)
            controller.all_done.connect(self._on_batch_all_done)
            controller.error.connect(self._on_batch_error)
            controller.paused.connect(self._on_batch_paused)
            controller.resumed_from_progress.connect(self._on_batch_resumed)
            self._batch_controller = controller
        return self._batch_controller

    def _ai_generate_batch(self) -> None:
        """AI分批生成大纲：先查询已有大纲以决定覆盖或续写."""
        if not self._project_id:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/outlines/{self._project_id}")
        worker.result.connect(self._check_existing_and_batch)
        worker.error.connect(lambda _: self._start_batch(reset=False))
        self._workers.append(worker)
        worker.start()

    def _check_existing_and_batch(self, existing: dict | None) -> None:
        reset = False
        if existing:
            reply = QMessageBox.question(
                self, "确认生成方式",
                "已存在大纲：\n"
                "选择“是” = 清空后重新分批生成；\n"
                "选择“否” = 保留已生成章节，仅补齐未生成章节。",
                QMessageBox.Yes | QMessageBox.No,
            )
            reset = reply == QMessageBox.Yes
        self._start_batch(reset)

    def _start_batch(self, reset: bool) -> None:
        if not self._project_id:
            return
        info = get_project_context().project_info
        volume_count = int(info.get("volume_count", 1) or 1)
        chapters_per_volume = int(info.get("chapters_per_volume", 10) or 10)
        controller = self._get_batch_controller()
        timer = self._get_progress_timer()
        timer.start("AI分批生成大纲")
        self._batch_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._resume_btn.setEnabled(False)
        self._batch_progress_label.setText("正在规划批次...")
        controller.start(
            project_id=self._project_id,
            volume_count=volume_count,
            chapters_per_volume=chapters_per_volume,
            reset=reset,
            user_ideas=self._ideas_input.toPlainText().strip(),
        )

    def _on_batch_done(self, data: dict) -> None:
        """每批返回后立即刷新树，实现边生成边显示."""
        self._on_load_done(data)
        self._has_unsaved_changes = False


    def _on_batch_progress(self, completed: int, total: int) -> None:
        self._batch_progress_label.setText(
            f"分批生成进度：已生成 {completed}/{total} 章"
        )

    def _on_batch_all_done(self, is_complete: bool) -> None:
        timer = self._get_progress_timer()
        timer.stop()
        self._batch_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(not is_complete)
        if is_complete:
            self._batch_progress_label.setText("全书大纲分批生成完成")
            self.outline_saved.emit()
        else:
            self._batch_progress_label.setText("仍有章节未生成，可点击“续写”补齐")

    def _on_batch_error(self, msg: str) -> None:
        timer = self._get_progress_timer()
        timer.show_error(msg)
        self._batch_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(True)
        self._load_outline()
        QMessageBox.warning(
            self, "生成失败",
            f"AI分批生成大纲失败：{msg}\n可点击“续写”重试该批次",
        )

    def _on_batch_paused(self, completed: int) -> None:
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(True)
        self._batch_progress_label.setText(
            f"已暂停，已生成 {completed} 章，可点击“续写”继续"
        )

    def _on_batch_resumed(self, skipped: int) -> None:
        self._batch_progress_label.setText(
            f"检测到已完成 {skipped} 批，自动跳过并继续"
        )

    def _on_batch_pause(self) -> None:
        if self._batch_controller:
            self._batch_controller.pause()

    def _on_batch_resume(self) -> None:
        if not self._batch_controller:
            # 切换项目或重开页面后控制器已释放，静默无反应会让用户以为按钮坏了
            QMessageBox.information(
                self, "提示",
                "当前没有进行中的分批生成任务。\n"
                "请点击「AI分批生成大纲」重新开始；已完成的部分会自动跳过。",
            )
            return
        self._resume_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._batch_controller.resume()

    def _get_check_controller(self) -> OutlineCheckController:
        """懒加载一致性校验控制器."""
        if self._check_controller is None:
            controller = OutlineCheckController(self)
            controller.progress.connect(self._on_check_progress)
            controller.all_done.connect(self._on_check_done)
            controller.error.connect(self._on_check_error)
            self._check_controller = controller
        return self._check_controller

    def _check_consistency(self) -> None:
        """分批校验大纲一致性，完成后弹出可复制的报告."""
        if not self._project_id:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        self._check_btn.setEnabled(False)
        self._check_progress_label.setText("正在校验大纲一致性...")
        self._get_check_controller().start(self._project_id)

    def _on_check_progress(self, done: int, total: int) -> None:
        self._check_progress_label.setText(f"一致性校验进度：{done}/{total} 批")

    def _on_check_done(self, report: dict) -> None:
        self._check_btn.setEnabled(True)
        issues = report.get("issues", []) or []
        self._check_progress_label.setText(
            f"一致性校验完成：评分 {report.get('score', 0)}/100，问题 {len(issues)} 条"
        )
        dialog = OutlineCheckReportDialog(report, self)
        dialog.repair_requested.connect(self._start_repair)
        dialog.exec()

    def _on_check_error(self, msg: str) -> None:
        self._check_btn.setEnabled(True)
        self._check_progress_label.setText("一致性校验失败")
        QMessageBox.warning(self, "校验失败", f"大纲一致性校验失败：{msg}")

    def _save_outline(self) -> None:
        if not self._project_id:
            return
        volumes = []
        for i in range(self._outline_tree.topLevelItemCount()):
            vol_item = self._outline_tree.topLevelItem(i)
            vol_data = vol_item.data(0, Qt.UserRole)
            chapters = []
            for j in range(vol_item.childCount()):
                ch_item = vol_item.child(j)
                ch_data = ch_item.data(0, Qt.UserRole)
                chapters.append({
                    "chapter_no": ch_data.get("chapter_no", j + 1),
                    "chapter_name": ch_item.text(1),
                    "synopsis_points": ch_data.get("synopsis_points", ""),
                    "characters_appearing": ch_data.get("characters_appearing", ""),
                })
            volumes.append({
                "volume_no": vol_data.get("volume_no", i + 1),
                "volume_name": vol_item.text(1),
                "chapters": chapters,
            })

        client = get_api_client()
        worker = ApiWorker(
            client.put,
            f"/api/outlines/{self._project_id}",
            json={"volumes": volumes},
        )
        worker.result.connect(self._on_save_done)
        worker.error.connect(self._on_save_error)
        self._workers.append(worker)
        worker.start()

    def _on_save_done(self, data: dict) -> None:
        self._has_unsaved_changes = False
        self.outline_saved.emit()
        self._status_label.setText("大纲保存成功")

    def _on_save_error(self, msg: str) -> None:
        QMessageBox.critical(self, "保存失败", msg)

    def _edit_selected(self) -> None:
        current = self._outline_tree.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选择要编辑的节点")
            return
        item_data = current.data(0, Qt.UserRole)
        if not item_data:
            return

        if item_data.get("type") == "volume":
            dialog = OutlineEditDialog(
                self, edit_type="volume",
                volume_name=current.text(1),
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                data = dialog.get_data()
                current.setText(1, data["volume_name"])
                self._has_unsaved_changes = True
        elif item_data.get("type") == "chapter":
            dialog = OutlineEditDialog(
                self, edit_type="chapter",
                chapter_name=current.text(1),
                synopsis=item_data.get("synopsis_points", ""),
                characters_appearing=item_data.get("characters_appearing", ""),
                chapter_id=item_data.get("chapter_id", ""),
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                data = dialog.get_data()
                current.setText(1, data["chapter_name"])
                synopsis = data["synopsis_points"]
                appearing = data["characters_appearing"]
                item_data["synopsis_points"] = synopsis
                item_data["characters_appearing"] = appearing
                current.setData(0, Qt.UserRole, item_data)
                preview = synopsis[:20] + "..." if len(synopsis) > 20 else synopsis
                current.setText(2, appearing)
                current.setText(3, preview)
                current.setToolTip(3, synopsis)
                scenes_changes = data.get("scenes_changes")
                if scenes_changes and (scenes_changes.get("modified") or scenes_changes.get("deleted")):
                    self._apply_scene_changes(item_data.get("chapter_id", ""), scenes_changes)
                    self._refresh_scene_count(current, item_data.get("chapter_id", ""))
                self._has_unsaved_changes = True

    def _apply_scene_changes(self, chapter_id: str, scenes_changes: dict) -> None:
        """提交场景修改/删除到后端."""
        client = get_api_client()
        failures: list[str] = []
        for sc in scenes_changes.get("modified", []):
            scene_id = sc.get("scene_id", "")
            if not scene_id:
                continue
            try:
                client.put(
                    f"/api/scene-outline/{scene_id}",
                    json={k: v for k, v in sc.items() if k != "scene_id"},
                )
            except Exception as e:
                failures.append(f"场景{scene_id[:8]}更新失败：{e}")
        for scene_id in scenes_changes.get("deleted", []):
            if not scene_id:
                continue
            try:
                client.delete(f"/api/scene-outline/{scene_id}")
            except Exception as e:
                failures.append(f"场景{scene_id[:8]}删除失败：{e}")
        if failures:
            QMessageBox.warning(self, "场景保存部分失败", "\n".join(failures))
        else:
            self._status_label.setText("场景保存成功")

    def _refresh_scene_count(self, ch_item: QTreeWidgetItem, chapter_id: str) -> None:
        """刷新大纲树中该章的场景数量列."""
        if not chapter_id:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/scene-outline/{chapter_id}/scenes")
        worker.result.connect(lambda scenes: ch_item.setText(4, str(len(scenes))))
        self._workers.append(worker)
        worker.start()

    def _delete_outline(self) -> None:
        if not self._project_id:
            return
        reply = QMessageBox.question(
            self, "确认清空",
            "确定清空当前大纲？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return
        client = get_api_client()
        worker = ApiWorker(client.delete, f"/api/outlines/{self._project_id}")
        worker.result.connect(lambda _: self._outline_tree.clear())
        worker.error.connect(lambda msg: QMessageBox.critical(self, "删除失败", msg))
        self._workers.append(worker)
        worker.start()

    def clear_page(self) -> None:
        self._outline_tree.clear()
        self._status_label.setText("")
        self._batch_progress_label.setText("")
        self._check_progress_label.setText("")
        self._ideas_input.clear()
        self._pause_btn.setEnabled(False)
        self._resume_btn.setEnabled(False)
        self._batch_btn.setEnabled(True)
        self._check_btn.setEnabled(True)
        self._fill_appearing_btn.setEnabled(True)
        self._batch_refine_scene_btn.setEnabled(True)
        self._batch_scene_pause_btn.setEnabled(False)
        self._batch_scene_progress_label.setText("")
        self._repair_progress_label.setText("")
        self._repair_pause_btn.setEnabled(False)
        if self._repair_sse_worker is not None:
            try:
                self._repair_sse_worker.stop()
            except Exception:
                pass
            self._repair_sse_worker = None
        if self._scene_sse_worker is not None:
            try:
                self._scene_sse_worker.stop()
            except Exception:
                pass
            self._scene_sse_worker = None
        if self._batch_scene_sse_worker is not None:
            try:
                self._batch_scene_sse_worker.stop()
            except Exception:
                pass
            self._batch_scene_sse_worker = None
        self._has_unsaved_changes = False

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _refine_scenes(self) -> None:
        """选中章节后调用SSE生成场景级大纲."""
        if not self._project_id:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        current = self._outline_tree.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选中要细化场景的章节")
            return
        item_data = current.data(0, Qt.UserRole)
        if not item_data or item_data.get("type") != "chapter":
            QMessageBox.warning(self, "提示", "请选中章节节点（非卷节点）")
            return
        volume_no = item_data.get("volume_no")
        chapter_no = item_data.get("chapter_no")
        client = get_api_client()
        try:
            chapters = client.get(
                f"/api/writing/{self._project_id}/chapters"
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"获取章节列表失败：{e}")
            return
        target_chapter = next(
            (
                c for c in chapters
                if c.get("volume_no") == volume_no
                and c.get("chapter_no") == chapter_no
            ),
            None,
        )
        if not target_chapter:
            QMessageBox.warning(
                self, "提示", "请先生成章节大纲再细化场景"
            )
            return
        chapter_id = target_chapter.get("chapter_id")
        if not chapter_id:
            QMessageBox.warning(self, "提示", "未找到章节ID，请先生成大纲")
            return
        self._refine_scene_btn.setEnabled(False)
        self._batch_progress_label.setText("场景生成中...")
        self._scene_results = []
        self._scene_sse_worker = SsePostWorker(
            "/api/scene-outline/split/stream",
            payload={"project_id": self._project_id, "chapter_id": chapter_id, "target_words": 3000, "user_ideas": ""},
        )
        self._scene_sse_worker.chunk.connect(
            lambda _: self._batch_progress_label.setText("场景生成中...")
        )
        self._scene_sse_worker.event.connect(self._on_scene_event)
        self._scene_sse_worker.error.connect(self._on_scene_error)
        self._scene_sse_worker.finished_ok.connect(self._on_scene_finished)
        self._scene_sse_worker.start()

    def _on_scene_event(self, data: dict) -> None:
        scene = data.get("scene")
        if scene:
            self._batch_progress_label.setText(
                f"场景生成：{scene.get('goal', '')}"
            )
            if not hasattr(self, "_scene_results"):
                self._scene_results = []
            self._scene_results.append(scene)

    def _on_scene_error(self, msg: str) -> None:
        self._refine_scene_btn.setEnabled(True)
        self._batch_progress_label.setText(f"场景生成失败：{msg}")
        self._scene_sse_worker = None
        QMessageBox.critical(self, "场景生成失败", msg)

    def _on_scene_finished(self) -> None:
        self._refine_scene_btn.setEnabled(True)
        self._batch_progress_label.setText("场景生成完成")
        self._scene_sse_worker = None
        self.scene_refined.emit()
        scenes = getattr(self, "_scene_results", [])
        if scenes:
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser
            dialog = QDialog(self)
            dialog.setWindowTitle(f"场景大纲（共{len(scenes)}个场景）")
            dialog.resize(600, 500)
            layout = QVBoxLayout(dialog)
            browser = QTextBrowser()
            html = "<h3>场景大纲</h3>"
            for i, s in enumerate(scenes, 1):
                html += f"<h4>场景{i}</h4>"
                html += f"<p><b>目标：</b>{s.get('goal', '')}</p>"
                html += f"<p><b>角色：</b>{s.get('characters', '')}</p>"
                html += f"<p><b>关键事件：</b>{s.get('key_event', '')}</p>"
                html += f"<p><b>情绪基调：</b>{s.get('mood', '')}</p>"
                html += f"<p><b>预计字数：</b>{s.get('est_words', '')}</p><hr>"
            browser.setHtml(html)
            layout.addWidget(browser)
            dialog.exec()
            self._scene_results = []
        else:
            QMessageBox.information(
                self, "完成", "场景大纲已生成，可在撰写进度页查看场景列表"
            )
    def _fill_appearing(self) -> None:
        """AI 智能填充出场人物为空的章节."""
        if not self._project_id:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        self._fill_appearing_btn.setEnabled(False)
        self._check_progress_label.setText("正在 AI 填充出场人物...")
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            f"/api/outlines/{self._project_id}/fill_appearing",
            json={},
        )
        worker.result.connect(self._on_fill_appearing_done)
        worker.error.connect(self._on_fill_appearing_error)
        self._workers.append(worker)
        worker.start()

    def _on_fill_appearing_done(self, data: dict) -> None:
        self._fill_appearing_btn.setEnabled(True)
        results = data.get("results", []) or []
        matched_count = sum(1 for r in results if r.get("matched"))
        pending_count = sum(len(r.get("pending", [])) for r in results)
        skipped_count = sum(1 for r in results if r.get("skipped"))
        pending_names = []
        for r in results:
            for n in r.get("pending", []):
                if n not in pending_names:
                    pending_names.append(n)
        summary = data.get("summary", "")
        detail = f"{summary}"
        if pending_names:
            detail += f"\n\n待确认人物：{'、'.join(pending_names[:20])}"
            if len(pending_names) > 20:
                detail += f" 等 {len(pending_names)} 人"
        self._check_progress_label.setText(f"出场人物填充完成：{summary}")
        QMessageBox.information(self, "填充完成", detail)
        self._load_outline()

    def _on_fill_appearing_error(self, msg: str) -> None:
        self._fill_appearing_btn.setEnabled(True)
        self._check_progress_label.setText("出场人物填充失败")
        QMessageBox.warning(self, "填充失败", f"AI 填充出场人物失败：{msg}")

    def _start_repair(self, issues: list) -> None:
        """AI 一键修复大纲 - SSE 流式逐章修复."""
        if not self._project_id:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        if not issues:
            QMessageBox.warning(self, "提示", "问题清单为空，无需修复")
            return
        self._check_btn.setEnabled(False)
        self._fill_appearing_btn.setEnabled(False)
        self._repair_pause_btn.setEnabled(True)
        self._repair_progress_label.setText("正在 AI 修复大纲...")
        self._repair_sse_worker = OutlineRepairSseWorker(
            self._project_id, issues, repair_scope="all"
        )
        self._repair_sse_worker.event.connect(self._on_repair_event)
        self._repair_sse_worker.finished_ok.connect(self._on_repair_finished)
        self._repair_sse_worker.error.connect(self._on_repair_error)
        self._repair_sse_worker.start()

    def _on_repair_event(self, data: dict) -> None:
        event_type = data.get("type", "")
        if event_type == "progress":
            self._repair_progress_label.setText(
                f"修复进度：{data.get('done', 0)}/{data.get('total', 0)}"
            )
        elif event_type == "chapter_done":
            self._load_outline()
            self._repair_progress_label.setText(
                f"第 {data.get('chapter_no', 0)} 章修复完成"
            )
        elif event_type == "chapter_skip":
            self._repair_progress_label.setText(
                f"第 {data.get('chapter_no', 0)} 章跳过：{data.get('fail_reason', '')}"
            )
        elif event_type == "chapter_rollback":
            self._repair_progress_label.setText(
                f"第 {data.get('chapter_no', 0)} 章回滚：{data.get('fail_reason', '')}"
            )
        elif event_type == "completed":
            self._repair_progress_label.setText(
                f"修复完成：成功 {data.get('success', 0)} / 失败 {data.get('failed', 0)} / 跳过 {data.get('skipped', 0)}"
            )
        elif event_type == "error":
            QMessageBox.warning(self, "修复错误", data.get("message", "未知错误"))

    def _on_repair_finished(self) -> None:
        self._check_btn.setEnabled(True)
        self._fill_appearing_btn.setEnabled(True)
        self._repair_pause_btn.setEnabled(False)
        if self._repair_sse_worker is not None:
            self._repair_sse_worker = None
        self._load_outline()

    def _on_repair_error(self, msg: str) -> None:
        self._check_btn.setEnabled(True)
        self._fill_appearing_btn.setEnabled(True)
        self._repair_pause_btn.setEnabled(False)
        self._repair_progress_label.setText("修复失败")
        QMessageBox.warning(self, "修复失败", msg)

    def _on_repair_pause(self) -> None:
        if self._repair_sse_worker is not None:
            try:
                self._repair_sse_worker.stop()
            except Exception:
                pass
            self._repair_sse_worker = None
        self._check_btn.setEnabled(True)
        self._fill_appearing_btn.setEnabled(True)
        self._repair_pause_btn.setEnabled(False)
        self._repair_progress_label.setText(
            "修复已暂停，已完成章节已保存，可续写"
        )

    def _batch_refine_scenes(self) -> None:
        """批量细化所有未细化场景的章节."""
        if not self._project_id:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        client = get_api_client()
        try:
            chapters = client.get(f"/api/writing/{self._project_id}/chapters")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"获取章节列表失败：{e}")
            return
        if not chapters:
            QMessageBox.warning(self, "提示", "请先生成大纲再批量细化场景")
            return
        self._batch_scene_results = []
        self._batch_scene_failed = []
        self._batch_scene_completed = 0
        self._batch_scene_total = 0
        self._batch_refine_scene_btn.setEnabled(False)
        self._batch_scene_pause_btn.setEnabled(True)
        self._batch_scene_progress_label.setText("批量细化场景启动中...")
        self._batch_scene_sse_worker = SsePostWorker(
            "/api/scene-outline/batch/stream",
            payload={
                "project_id": self._project_id,
                "target_words": 3000,
                "user_ideas": self._ideas_input.toPlainText(),
            },
        )
        self._batch_scene_sse_worker.event.connect(self._on_batch_scene_event)
        self._batch_scene_sse_worker.error.connect(self._on_batch_scene_error)
        self._batch_scene_sse_worker.finished_ok.connect(self._on_batch_scene_finished)
        self._batch_scene_sse_worker.start()

    def _on_batch_scene_event(self, data: dict) -> None:
        event_type = data.get("type", "")
        if event_type == "progress":
            self._batch_scene_total = data.get("total") or 0
            self._batch_scene_progress_label.setText(
                f"批量细化：{data.get('message', '')}（{data.get('current', 0)}/{data.get('total', 0)}）"
            )
        elif event_type == "chunk":
            scene = data.get("scene")
            if scene:
                self._batch_scene_results.append(scene)
            self._batch_scene_progress_label.setText(
                f"已收集 {len(self._batch_scene_results)} 个场景（当前章：{data.get('chapter_title', '')}）"
            )
        elif event_type == "failed":
            self._batch_scene_failed.append(
                {
                    "chapter_id": data.get("chapter_id"),
                    "title": data.get("chapter_title"),
                    "reason": data.get("message", ""),
                }
            )
            self._batch_scene_progress_label.setText(
                f"章 {data.get('chapter_title', '')} 失败：{data.get('message', '')}，已跳过"
            )
        elif event_type == "done":
            self._batch_scene_total_success = data.get("success_count", 0)
            self._batch_scene_total_failed = data.get("failed_count", 0)
            self._batch_scene_failed = data.get("failed_chapters", []) or []

    def _on_batch_scene_error(self, msg: str) -> None:
        self._batch_refine_scene_btn.setEnabled(True)
        self._batch_scene_pause_btn.setEnabled(False)
        self._batch_scene_progress_label.setText(f"批量细化失败：{msg}")
        QMessageBox.critical(self, "批量细化失败", msg)
        self._batch_scene_sse_worker = None

    def _on_batch_scene_finished(self) -> None:
        self._batch_refine_scene_btn.setEnabled(True)
        self._batch_scene_pause_btn.setEnabled(False)
        self._batch_scene_progress_label.setText("批量细化场景完成")
        self.scene_refined.emit()
        self._load_outline()
        success = getattr(self, "_batch_scene_total_success", 0)
        failed_list = self._batch_scene_failed or []
        if failed_list:
            detail = "\n".join(
                f"  · {f.get('title', '')}：{f.get('reason', '')}" for f in failed_list
            )
            QMessageBox.information(
                self,
                "批量细化完成",
                f"成功 {success} 章，失败 {len(failed_list)} 章\n\n失败详情：\n{detail}",
            )
        else:
            QMessageBox.information(
                self, "批量细化完成", f"成功 {success} 章，全部完成"
            )
        self._batch_scene_sse_worker = None
        self._batch_scene_results = []

    def _on_batch_scene_pause(self) -> None:
        if self._batch_scene_sse_worker is not None:
            try:
                self._batch_scene_sse_worker.stop()
            except Exception:
                pass
            self._batch_scene_sse_worker = None
        self._batch_refine_scene_btn.setEnabled(True)
        self._batch_scene_pause_btn.setEnabled(False)
        self._batch_scene_progress_label.setText(
            "批量细化已暂停，已完成章节已保存，可点击「批量细化场景」续写"
        )
