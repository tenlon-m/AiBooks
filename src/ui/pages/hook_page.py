"""爽点钩子页 - AI设计爽点与钩子 + 查看列表."""
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.hook_chapter_controller import HookChapterController
from src.ui.project_context import get_project_context
from src.ui.sse_worker import HookRepairSseWorker
from src.ui.widgets.character_progress_timer import CharacterProgressTimer
from src.ui.widgets.cool_point_edit_dialog import CoolPointEditDialog
from src.ui.widgets.hook_check_report_dialog import HookCheckReportDialog
from src.ui.widgets.hook_edit_dialog import HookEditDialog


class HookPage(QWidget):
    hook_saved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._chapter_controller: HookChapterController | None = None
        self._progress_timer: CharacterProgressTimer | None = None
        self._has_unsaved_changes: bool = False
        self._repair_sse_worker: HookRepairSseWorker | None = None
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
        self.cool_table.setRowCount(0)
        self.hook_table.setRowCount(0)
        self.status_label.clear()
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")
        self._check_progress_label.setText("")
        self._repair_progress_label.setText("")
        self._repair_pause_btn.setEnabled(False)
        if self._repair_sse_worker is not None:
            try:
                self._repair_sse_worker.stop()
            except Exception:
                pass
            self._repair_sse_worker = None

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _mark_unsaved(self) -> None:
        self._has_unsaved_changes = True
        self.save_btn.setStyleSheet("border: 2px solid #ff9800;")

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self._ideas_input.clear()
        if project_id:
            self._load_all()
            self._check_chapter_progress()

    def _check_chapter_progress(self) -> None:
        """加载项目时检测逐章生成进度，自动恢复续写按钮状态."""
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/hooks/{pid}/progress_chapter")
        worker.result.connect(self._on_progress_check_done)
        worker.error.connect(self._on_progress_check_error)
        self._add_worker(worker)
        worker.start()

    def _on_progress_check_error(self, msg: str) -> None:
        """进度检测失败：不弹窗打断，但必须在进度条上可见（此前是静默吞掉）."""
        self._progress_label.setText(f"逐章生成进度检测失败：{msg}")

    def _on_progress_check_done(self, data: dict) -> None:
        """根据进度恢复按钮状态."""
        generated_count = data.get("total_generated", 0)
        if generated_count > 0:
            self.resume_btn.setEnabled(True)
            self._chapter_progress_label.setText(
                f"检测到已生成 {generated_count} 章爽点钩子，可点击续写继续"
            )

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("爽点钩子设计")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        ideas_label = QLabel("爽点钩子思路与想法（可选）：在此输入你对爽点钩子的思路和想法，AI 生成时会充分参考")
        ideas_label.setStyleSheet("color: #555; padding: 4px 8px;")
        layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText("例如：第一卷以逆袭爽点为主，每章埋设一个钩子，第三卷集中回收……")
        self._ideas_input.setMaximumHeight(80)
        self._ideas_input.setStyleSheet("padding: 4px;")
        layout.addWidget(self._ideas_input)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("爽点列表："))
        self.cool_table = QTableWidget(0, 5)
        self.cool_table.setHorizontalHeaderLabels(["卷", "章", "类型", "描述", "来源"])
        self.cool_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.cool_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.cool_table, 1)

        layout.addWidget(QLabel("钩子列表："))
        self.hook_table = QTableWidget(0, 6)
        self.hook_table.setHorizontalHeaderLabels(["卷", "章", "钩子内容", "回收卷", "回收章", "回收状态"])
        self.hook_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.hook_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.hook_table, 1)

        self.cool_table.cellDoubleClicked.connect(self._on_cool_double_clicked)
        self.hook_table.cellDoubleClicked.connect(self._on_hook_double_clicked)

        btn_layout = QHBoxLayout()

        self.chapter_btn = QPushButton("AI逐章生成爽点钩子")
        self.chapter_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;")
        self.chapter_btn.clicked.connect(self._ai_design_chapter_wise)
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        self.resume_btn = QPushButton("续写")
        self.resume_btn.setEnabled(False)
        self.resume_btn.clicked.connect(self._on_resume_clicked)
        self.check_btn = QPushButton("校验一致性")
        self.check_btn.clicked.connect(self._check_consistency)
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self._save_all)
        self.edit_btn = QPushButton("编辑选中")
        self.edit_btn.clicked.connect(self._edit_selected)
        self.delete_btn = QPushButton("批量删除")
        self.delete_btn.clicked.connect(self._batch_delete)
        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.clicked.connect(self._load_all)

        btn_layout.addWidget(self.chapter_btn)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.resume_btn)
        btn_layout.addWidget(self.check_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._chapter_progress_label = QLabel()
        self._chapter_progress_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._chapter_progress_label)

        self._check_progress_label = QLabel()
        self._check_progress_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._check_progress_label)

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

    def _get_project_id(self) -> str | None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return None
        return ctx.project_id

    def _load_all(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(self._fetch_all, client, pid)
        worker.result.connect(self._on_all_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    @staticmethod
    def _fetch_all(client, project_id: str) -> dict:
        result = {}
        try:
            result["cool_points"] = client.get(f"/api/hooks/{project_id}/cool_points")
        except Exception:
            result["cool_points"] = []
        try:
            result["hooks"] = client.get(f"/api/hooks/{project_id}/hooks")
        except Exception:
            result["hooks"] = []
        return result

    def _on_all_loaded(self, data: dict) -> None:
        cool_points = data.get("cool_points", [])
        self.cool_table.setRowCount(0)
        for cp in cool_points:
            row = self.cool_table.rowCount()
            self.cool_table.insertRow(row)
            vol_item = QTableWidgetItem(str(cp.get("volume_no", "")))
            vol_item.setData(Qt.ItemDataRole.UserRole, cp.get("cool_id"))
            self.cool_table.setItem(row, 0, vol_item)
            self.cool_table.setItem(row, 1, QTableWidgetItem(str(cp.get("chapter_no", ""))))
            self.cool_table.setItem(row, 2, QTableWidgetItem(cp.get("cool_type", "")))
            self.cool_table.setItem(row, 3, QTableWidgetItem(cp.get("content_desc", "")))
            self.cool_table.setItem(row, 4, QTableWidgetItem(cp.get("source", "")))

        hooks = data.get("hooks", [])
        self.hook_table.setRowCount(0)
        for h in hooks:
            row = self.hook_table.rowCount()
            self.hook_table.insertRow(row)
            vol_item = QTableWidgetItem(str(h.get("volume_no", "")))
            vol_item.setData(Qt.ItemDataRole.UserRole, h.get("hook_id"))
            self.hook_table.setItem(row, 0, vol_item)
            self.hook_table.setItem(row, 1, QTableWidgetItem(str(h.get("chapter_no", ""))))
            self.hook_table.setItem(row, 2, QTableWidgetItem(h.get("hook_content", "")))
            self.hook_table.setItem(row, 3, QTableWidgetItem(str(h.get("recycle_volume_no", ""))))
            self.hook_table.setItem(row, 4, QTableWidgetItem(str(h.get("recycle_chapter_no", ""))))
            status = h.get("recycle_status", "pending")
            cn_status = {"pending": "未回收", "recycled": "已回收", "unrecycled": "未回收"}.get(status, status)
            self.hook_table.setItem(row, 5, QTableWidgetItem(cn_status))
        self.status_label.setText(f"共 {len(cool_points)} 个爽点，{len(hooks)} 个钩子")

    def _on_error(self, msg: str) -> None:
        timer = self._get_progress_timer()
        timer.stop()
        self.status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)

    def _ai_design_chapter_wise(self) -> None:
        """逐章生成爽点钩子."""
        pid = self._get_project_id()
        if not pid:
            return

        client = get_api_client()
        try:
            outline = client.get(f"/api/outlines/{pid}")
        except Exception:
            outline = None
        if not outline:
            QMessageBox.warning(self, "提示", "请先在大纲管理中生成大纲")
            return

        ctx = get_project_context()
        info = ctx.project_info
        vol_count = info.get("volume_count", 1)
        ch_count = info.get("chapters_per_volume", 10)
        chapter_list = [
            (v, c)
            for v in range(1, vol_count + 1)
            for c in range(1, ch_count + 1)
        ]

        self._chapter_controller = HookChapterController(self)
        self._chapter_controller.chapter_generated.connect(self._on_chapter_generated)
        self._chapter_controller.all_done.connect(self._on_all_chapters_done)
        self._chapter_controller.error.connect(self._on_chapter_error)
        self._chapter_controller.paused.connect(self._on_paused)

        timer = self._get_progress_timer()
        timer.start("AI逐章生成爽点钩子")
        self.chapter_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self._chapter_controller.start(pid, chapter_list, user_ideas=self._ideas_input.toPlainText().strip())

    def _on_chapter_generated(self, chapter_info: dict) -> None:
        vol = chapter_info.get("volume_no", 0)
        ch = chapter_info.get("chapter_no", 0)
        self._chapter_progress_label.setText(
            f"逐章生成中... 第{vol}卷第{ch}章完成"
        )

    def _on_all_chapters_done(self) -> None:
        timer = self._get_progress_timer()
        timer.stop()
        self.chapter_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)
        self.save_btn.setEnabled(True)
        self._chapter_progress_label.setText("全书爽点钩子逐章生成完成")
        self._load_all()
        self.hook_saved.emit()

    def _on_chapter_error(self, msg: str) -> None:
        timer = self._get_progress_timer()
        timer.show_error(msg)
        self.chapter_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        QMessageBox.warning(self, "生成失败", f"{msg}\n可重试/跳过/手动设定")

    def _on_paused(self, completed_count: int) -> None:
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self._chapter_progress_label.setText(
            f"已暂停，已生成 {completed_count} 章爽点钩子，可续写"
        )

    def _on_pause_clicked(self) -> None:
        if self._chapter_controller:
            self._chapter_controller.pause()

    def _on_resume_clicked(self) -> None:
        if not self._chapter_controller:
            # 切换项目或重开页面后控制器已释放，静默无反应会让用户以为按钮坏了
            QMessageBox.information(
                self, "提示",
                "当前没有进行中的逐章生成任务。\n"
                "请点击「AI逐章生成」重新开始；已生成的章节会自动跳过。",
            )
            return
        self._chapter_controller.resume()
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)
    def _batch_delete(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        cool_ids = []
        for row in self.cool_table.selectedItems():
            if row.column() == 0:
                cool_id = self.cool_table.item(row.row(), 0).data(Qt.ItemDataRole.UserRole)
                if cool_id:
                    cool_ids.append(cool_id)
        hook_ids = []
        for row in self.hook_table.selectedItems():
            if row.column() == 0:
                hook_id = self.hook_table.item(row.row(), 0).data(Qt.ItemDataRole.UserRole)
                if hook_id:
                    hook_ids.append(hook_id)
        cool_ids = list(set(cool_ids))
        hook_ids = list(set(hook_ids))
        if not cool_ids and not hook_ids:
            QMessageBox.warning(self, "提示", "请先选中要删除的爽点或钩子")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"将删除 {len(cool_ids)} 个爽点和 {len(hook_ids)} 个钩子，确认继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        if cool_ids:
            worker = ApiWorker(client.delete, f"/api/hooks/{pid}/cool_points", json={"cool_ids": cool_ids})
            worker.result.connect(lambda _: self._on_delete_done("爽点"))
            worker.error.connect(self._on_error)
            self._add_worker(worker)
            worker.start()
        if hook_ids:
            worker = ApiWorker(client.delete, f"/api/hooks/{pid}/hooks", json={"hook_ids": hook_ids})
            worker.result.connect(lambda _: self._on_delete_done("钩子"))
            worker.error.connect(self._on_error)
            self._add_worker(worker)
            worker.start()

    def _on_delete_done(self, kind: str) -> None:
        self._load_all()
        QMessageBox.information(self, "成功", f"批量删除{kind}完成")

    def _collect_cool_points(self) -> list[dict]:
        result = []
        for row in range(self.cool_table.rowCount()):
            result.append({
                "volume_no": int(self.cool_table.item(row, 0).text() or "1"),
                "chapter_no": int(self.cool_table.item(row, 1).text() or "1"),
                "cool_type": self.cool_table.item(row, 2).text() if self.cool_table.item(row, 2) else "",
                "content_desc": self.cool_table.item(row, 3).text() if self.cool_table.item(row, 3) else "",
                "source": self.cool_table.item(row, 4).text() if self.cool_table.item(row, 4) else "manual",
            })
        return result

    def _collect_hooks(self) -> list[dict]:
        status_map = {"未回收": "pending", "已回收": "recycled"}
        result = []
        for row in range(self.hook_table.rowCount()):
            status_text = self.hook_table.item(row, 5).text() if self.hook_table.item(row, 5) else "pending"
            result.append({
                "volume_no": int(self.hook_table.item(row, 0).text() or "1"),
                "chapter_no": int(self.hook_table.item(row, 1).text() or "1"),
                "hook_content": self.hook_table.item(row, 2).text() if self.hook_table.item(row, 2) else "",
                "recycle_volume_no": int(self.hook_table.item(row, 3).text() or "1"),
                "recycle_chapter_no": int(self.hook_table.item(row, 4).text() or "1"),
                "recycle_status": status_map.get(status_text, status_text),
                "source": "manual",
            })
        return result

    def _save_all(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        cool_points = self._collect_cool_points()
        hooks = self._collect_hooks()
        client = get_api_client()
        worker = ApiWorker(self._save_all_impl, client, pid, cool_points, hooks)
        worker.result.connect(self._on_save_done)
        worker.error.connect(self._on_save_error)
        self._add_worker(worker)
        worker.start()

    @staticmethod
    def _save_all_impl(client, project_id: str, cool_points: list[dict], hooks: list[dict]) -> dict:
        result = {}
        try:
            result["cool_points"] = client.put(f"/api/hooks/{project_id}/cool_points", json={"cool_points": cool_points})
        except Exception as e:
            result["cool_error"] = str(e)
        try:
            result["hooks"] = client.put(f"/api/hooks/{project_id}/hooks", json={"hooks": hooks})
        except Exception as e:
            result["hook_error"] = str(e)
        return result

    def _on_save_done(self, data: dict) -> None:
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")
        self._load_all()
        if data.get("cool_error") or data.get("hook_error"):
            errors = []
            if data.get("cool_error"):
                errors.append(f"爽点: {data['cool_error']}")
            if data.get("hook_error"):
                errors.append(f"钩子: {data['hook_error']}")
            QMessageBox.warning(self, "部分保存失败", f"保存失败：{', '.join(errors)}，请检查后重试")
        else:
            QMessageBox.information(self, "成功", "保存成功")

    def _on_save_error(self, msg: str) -> None:
        QMessageBox.critical(self, "错误", f"保存失败：{msg}，请检查后重试")

    def _check_consistency(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        self.check_btn.setEnabled(False)
        self._check_progress_label.setText("正在校验爽点钩子一致性，请稍候...")
        timer = self._get_progress_timer()
        timer.start("校验一致性")
        client = get_api_client()
        worker = ApiWorker(client.post, f"/api/hooks/{pid}/check_consistency", timeout=300)
        worker.result.connect(self._on_check_consistency_done)
        worker.error.connect(self._on_check_consistency_error)
        self._add_worker(worker)
        worker.start()

    def _on_check_consistency_done(self, data: dict) -> None:
        self.check_btn.setEnabled(True)
        timer = self._get_progress_timer()
        timer.stop()
        issues = data.get("issues", []) or []
        self._check_progress_label.setText(
            f"校验完成：评分 {data.get('score', 0)}/100，问题 {len(issues)} 条"
        )
        dialog = HookCheckReportDialog(data, self)
        dialog.repair_requested.connect(self._start_repair)
        dialog.exec()

    def _on_check_consistency_error(self, msg: str) -> None:
        self.check_btn.setEnabled(True)
        timer = self._get_progress_timer()
        timer.stop()
        self._check_progress_label.setText("校验失败")
        QMessageBox.critical(self, "错误", f"一致性校验失败：{msg}")

    def _start_repair(self, issues: list) -> None:
        """AI 一键修复爽点钩子 - SSE 流式逐章修复."""
        pid = self._get_project_id()
        if not pid:
            return
        if not issues:
            QMessageBox.warning(self, "提示", "问题清单为空，无需修复")
            return
        self.check_btn.setEnabled(False)
        self.chapter_btn.setEnabled(False)
        self._repair_pause_btn.setEnabled(True)
        self._repair_progress_label.setText("正在 AI 修复爽点钩子，请稍候...")
        timer = self._get_progress_timer()
        timer.start("AI修复爽点钩子")
        self._repair_sse_worker = HookRepairSseWorker(pid, issues, repair_scope="all")
        self._repair_sse_worker.event.connect(self._on_repair_event)
        self._repair_sse_worker.finished_ok.connect(self._on_repair_finished)
        self._repair_sse_worker.error.connect(self._on_repair_error)
        self._repair_sse_worker.start()

    def _on_repair_event(self, data: dict) -> None:
        event_type = data.get("type", "")
        if event_type == "progress":
            self._repair_progress_label.setText(
                f"修复进度：{data.get('done', 0)}/{data.get('total', 0)}（正在修复第 {data.get('volume_no', 0)} 卷第 {data.get('chapter_no', 0)} 章）"
            )
        elif event_type == "chapter_done":
            self._load_all()
            self._repair_progress_label.setText(
                f"第 {data.get('volume_no', 0)} 卷第 {data.get('chapter_no', 0)} 章修复完成"
            )
        elif event_type == "chapter_skip":
            self._repair_progress_label.setText(
                f"第 {data.get('volume_no', 0)} 卷第 {data.get('chapter_no', 0)} 章跳过：{data.get('fail_reason', '')}"
            )
        elif event_type == "completed":
            self._repair_progress_label.setText(
                f"修复完成：成功 {data.get('success', 0)} / 失败 {data.get('failed', 0)} / 跳过 {data.get('skipped', 0)}"
            )
        elif event_type == "error":
            QMessageBox.warning(self, "修复错误", data.get("message", "未知错误"))

    def _on_repair_finished(self) -> None:
        self.check_btn.setEnabled(True)
        self.chapter_btn.setEnabled(True)
        self._repair_pause_btn.setEnabled(False)
        timer = self._get_progress_timer()
        timer.stop()
        if self._repair_sse_worker is not None:
            self._repair_sse_worker = None
        self._load_all()

    def _on_repair_error(self, msg: str) -> None:
        self.check_btn.setEnabled(True)
        self.chapter_btn.setEnabled(True)
        self._repair_pause_btn.setEnabled(False)
        timer = self._get_progress_timer()
        timer.stop()
        self._repair_progress_label.setText("修复失败")
        QMessageBox.warning(self, "修复失败", msg)

    def _on_repair_pause(self) -> None:
        if self._repair_sse_worker is not None:
            try:
                self._repair_sse_worker.stop()
            except Exception:
                pass
            self._repair_sse_worker = None
        self.check_btn.setEnabled(True)
        self.chapter_btn.setEnabled(True)
        self._repair_pause_btn.setEnabled(False)
        timer = self._get_progress_timer()
        timer.stop()
        self._repair_progress_label.setText(
            "修复已暂停，已完成章节已保存，可重新校验后继续修复"
        )

    def _edit_selected(self, table: QTableWidget | None = None) -> None:
        if table is None:
            if self.cool_table.hasFocus():
                table = self.cool_table
            elif self.hook_table.hasFocus():
                table = self.hook_table
            else:
                table = self.cool_table
        if table is self.cool_table:
            self._edit_cool_selected()
        else:
            self._edit_hook_selected()

    def _edit_cool_selected(self) -> None:
        rows = set(item.row() for item in self.cool_table.selectedItems())
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择要编辑的爽点")
            return
        row = sorted(rows)[0]
        volume_no = int(self.cool_table.item(row, 0).text() or "1")
        chapter_no = int(self.cool_table.item(row, 1).text() or "1")
        cool_type = self.cool_table.item(row, 2).text() if self.cool_table.item(row, 2) else ""
        content_desc = self.cool_table.item(row, 3).text() if self.cool_table.item(row, 3) else ""
        dialog = CoolPointEditDialog(self, volume_no, chapter_no, cool_type, content_desc)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            self.cool_table.setItem(row, 0, QTableWidgetItem(str(data["volume_no"])))
            self.cool_table.setItem(row, 1, QTableWidgetItem(str(data["chapter_no"])))
            self.cool_table.setItem(row, 2, QTableWidgetItem(data["cool_type"]))
            self.cool_table.setItem(row, 3, QTableWidgetItem(data["content_desc"]))
            self._mark_unsaved()

    def _edit_hook_selected(self) -> None:
        rows = set(item.row() for item in self.hook_table.selectedItems())
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择要编辑的钩子")
            return
        row = sorted(rows)[0]
        volume_no = int(self.hook_table.item(row, 0).text() or "1")
        chapter_no = int(self.hook_table.item(row, 1).text() or "1")
        hook_content = self.hook_table.item(row, 2).text() if self.hook_table.item(row, 2) else ""
        recycle_volume_no = int(self.hook_table.item(row, 3).text() or "1")
        recycle_chapter_no = int(self.hook_table.item(row, 4).text() or "1")
        recycle_status = self.hook_table.item(row, 5).text() if self.hook_table.item(row, 5) else "pending"
        status_map = {"未回收": "pending", "已回收": "recycled"}
        en_status = status_map.get(recycle_status, recycle_status)
        dialog = HookEditDialog(self, volume_no, chapter_no, hook_content, recycle_volume_no, recycle_chapter_no, en_status)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            cn_status = {"pending": "未回收", "recycled": "已回收"}.get(data["recycle_status"], data["recycle_status"])
            self.hook_table.setItem(row, 0, QTableWidgetItem(str(data["volume_no"])))
            self.hook_table.setItem(row, 1, QTableWidgetItem(str(data["chapter_no"])))
            self.hook_table.setItem(row, 2, QTableWidgetItem(data["hook_content"]))
            self.hook_table.setItem(row, 3, QTableWidgetItem(str(data["recycle_volume_no"])))
            self.hook_table.setItem(row, 4, QTableWidgetItem(str(data["recycle_chapter_no"])))
            self.hook_table.setItem(row, 5, QTableWidgetItem(cn_status))
            self._mark_unsaved()

    def _on_cool_double_clicked(self, row: int, col: int) -> None:
        self._edit_cool_selected()

    def _on_hook_double_clicked(self, row: int, col: int) -> None:
        self._edit_hook_selected()
