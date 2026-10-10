"""校验报告页 - 全书校验 + 批量再校验."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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
from src.ui.sse_worker import WritingRepairSseWorker


class ValidationReportPage(QWidget):
    validation_completed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._has_unsaved_changes: bool = False
        self._repair_sse_worker: WritingRepairSseWorker | None = None
        self._init_ui()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def clear_page(self) -> None:
        self.table.setRowCount(0)
        self.ai_degree_edit.clear()
        self.status_label.clear()
        self._progress_label.clear()
        self.validate_btn.setEnabled(True)
        self.batch_btn.setEnabled(True)
        self._has_unsaved_changes = False

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _add_worker(self, worker: ApiWorker) -> None:
        """注册 ApiWorker 并在完成后自动清理，避免内存泄漏."""
        self._add_worker(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))

    def _cleanup_worker(self, worker: ApiWorker) -> None:
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    def is_busy(self) -> bool:
        """是否有本地异步操作正在运行."""
        return len(self._workers) > 0 or self._repair_sse_worker is not None

    def _check_no_running_op(self) -> bool:
        """检查是否有操作正在运行，有则弹窗提示并返回 False."""
        if self.is_busy():
            QMessageBox.warning(self, "提示", "已有操作进行中，请等待完成后再启动新操作")
            return False
        return True

    def _mark_unsaved(self) -> None:
        """校验报告是只读展示页，标脏仅用于提示「当前结果非最新」."""
        self._has_unsaved_changes = True
        self.status_label.setText("当前展示的校验结果不是最新的，可点击「刷新列表」重新拉取")

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self._ideas_input.clear()
        self.clear_page()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("内容校验报告")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        ideas_label = QLabel("校验思路与想法（可选）：在此输入你对校验的思路和想法，全书校验时会充分参考")
        ideas_label.setStyleSheet("color: #555; padding: 4px 8px;")
        layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText("例如：重点关注人物一致性，检查各章人物描写是否统一……")
        self._ideas_input.setMaximumHeight(80)
        self._ideas_input.setStyleSheet("padding: 4px;")
        layout.addWidget(self._ideas_input)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("校验结果："))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["检查类型", "结果", "问题描述", "卷", "章"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.table, 1)

        layout.addWidget(QLabel("AI化程度评估："))
        self.ai_degree_edit = QTextEdit()
        self.ai_degree_edit.setReadOnly(True)
        self.ai_degree_edit.setMaximumHeight(150)
        layout.addWidget(self.ai_degree_edit)

        btn_layout = QHBoxLayout()
        self.validate_btn = QPushButton("全书校验")
        self.validate_btn.setStyleSheet("background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;")
        self.validate_btn.clicked.connect(self._validate_full_book)
        self.batch_btn = QPushButton("批量再校验")
        self.batch_btn.setStyleSheet("background-color: #ff9800; color: white; padding: 6px 16px; border-radius: 4px;")
        self.batch_btn.setToolTip("对指定章节重新做一致性校验（一次最多 50 章）")
        self.batch_btn.clicked.connect(self._batch_revalidate)
        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.clicked.connect(self._refresh_list)
        self._repair_btn = QPushButton("AI修复")
        self._repair_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;")
        self._repair_btn.setToolTip("根据校验结果一键 AI 修复撰写内容")
        self._repair_btn.clicked.connect(self._start_repair_from_validation)
        btn_layout.addWidget(self.validate_btn)
        btn_layout.addWidget(self.batch_btn)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self._repair_btn)
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

    def _validate_full_book(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        if not self._check_no_running_op():
            return
        user_ideas = self._ideas_input.toPlainText().strip()
        self.status_label.setText("全书校验中，请稍候...")
        self._progress_label.setText("全书校验中，请稍候...")
        self.validate_btn.setEnabled(False)
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            "/api/validation/full_book",
            params={"project_id": pid, "user_ideas": user_ideas},
        )
        worker.result.connect(self._on_validated)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_validated(self, data: dict) -> None:
        self.validate_btn.setEnabled(True)
        items = data.get("items", [])
        self.table.setRowCount(0)
        for item in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(item.get("check_type", "")))
            self.table.setItem(row, 1, QTableWidgetItem(item.get("result", "")))
            self.table.setItem(row, 2, QTableWidgetItem(item.get("problem_desc", "") or ""))
            self.table.setItem(row, 3, QTableWidgetItem(str(item.get("volume_no", "") or "")))
            self.table.setItem(row, 4, QTableWidgetItem(str(item.get("chapter_no", "") or "")))

        ai_degree = data.get("ai_degree_score", "")
        problems = data.get("ai_degree_problems", [])
        lines = [f"AI化程度评分：{ai_degree}"]
        if problems:
            lines.append("问题列表：")
            for p in problems:
                lines.append(f"  - {p}")
        self.ai_degree_edit.setPlainText("\n".join(lines))
        self.status_label.setText(f"校验完成，共 {len(items)} 项")
        self._progress_label.setText(f"校验完成，共 {len(items)} 项")
        QMessageBox.information(self, "成功", f"全书校验完成，共 {len(items)} 项")
        self.validation_completed.emit()

    # ---------------------------------------------------------------- 批量再校验
    def _batch_revalidate(self) -> None:
        """批量再校验：先取章节列表，确定章节ID后调用 POST /api/validation/batch_revalidate."""
        pid = self._get_project_id()
        if not pid:
            return
        if not self._check_no_running_op():
            return
        self.batch_btn.setEnabled(False)
        self._progress_label.setText("正在读取章节列表...")
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/writing/{pid}/chapters")
        worker.result.connect(self._on_chapters_for_revalidate)
        worker.error.connect(self._on_batch_error)
        self._add_worker(worker)
        worker.start()

    def _on_chapters_for_revalidate(self, data: list | dict) -> None:
        self.batch_btn.setEnabled(True)
        chapters = data if isinstance(data, list) else data.get("chapters", [])
        candidates = [
            c for c in chapters
            if c.get("gen_status") == "completed" and c.get("chapter_id")
        ]
        if not candidates:
            QMessageBox.warning(self, "提示", "没有「已完成」的章节，请先完成撰写")
            self._progress_label.clear()
            return

        candidates.sort(key=lambda c: int(c.get("chapter_no", 0) or 0))
        # 后端限制一次最多 50 章
        limit = min(len(candidates), 50)
        if len(candidates) > limit:
            count, ok = QInputDialog.getInt(
                self,
                "批量再校验",
                f"共 {len(candidates)} 章已完成，一次最多校验 50 章。\n请输入要校验的章数（取最后 N 章）：",
                value=limit, minValue=1, maxValue=limit,
            )
            if not ok:
                self._progress_label.clear()
                return
        else:
            count = limit

        selected = candidates[-count:]
        chapter_ids = [c["chapter_id"] for c in selected]
        scope_text = (
            f"第{selected[0].get('chapter_no')}章 ~ 第{selected[-1].get('chapter_no')}章"
        )
        reply = QMessageBox.question(
            self, "确认批量再校验",
            f"将对 {len(chapter_ids)} 章（{scope_text}）重新做一致性校验，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._progress_label.clear()
            return

        pid = self._get_project_id()
        if not pid:
            return
        self.batch_btn.setEnabled(False)
        self.status_label.setText("批量再校验中，请稍候...")
        self._progress_label.setText(f"批量再校验中（{len(chapter_ids)} 章）...")
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            "/api/validation/batch_revalidate",
            json={"project_id": pid, "chapter_ids": chapter_ids},
            timeout=600,
        )
        worker.result.connect(self._on_batch_revalidated)
        worker.error.connect(self._on_batch_error)
        self._add_worker(worker)
        worker.start()

    def _on_batch_revalidated(self, data: dict) -> None:
        self.batch_btn.setEnabled(True)
        per_chapter = data.get("per_chapter", []) or []
        self.table.setRowCount(0)
        for entry in per_chapter:
            items = entry.get("items", []) or []
            for item in items:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(str(item.get("check_type", ""))))
                self.table.setItem(row, 1, QTableWidgetItem(str(item.get("result", ""))))
                self.table.setItem(row, 2, QTableWidgetItem(str(item.get("problem_desc", "") or "")))
                self.table.setItem(row, 3, QTableWidgetItem(""))
                self.table.setItem(
                    row, 4,
                    QTableWidgetItem(str(item.get("chapter_no", "") or entry.get("chapter_no", "") or "")),
                )
        summary_lines = []
        for key, label in (
            ("global_character_change", "全书人物变化汇总"),
            ("global_item_change", "全书物品变化汇总"),
            ("global_item_consistency", "全书物品一致性"),
        ):
            block = data.get(key) or {}
            if not block:
                continue
            summary_lines.append(
                f"【{label}】{block.get('result', '')} {block.get('problem_desc', '') or ''}".strip()
            )
        if summary_lines:
            self.ai_degree_edit.setPlainText("\n".join(summary_lines))
        self.status_label.setText(
            f"批量再校验完成：{len(per_chapter)} 章，共 {self.table.rowCount()} 条问题"
        )
        self._progress_label.clear()
        self._has_unsaved_changes = False
        QMessageBox.information(
            self, "成功",
            f"批量再校验完成：{len(per_chapter)} 章，共 {self.table.rowCount()} 条问题",
        )
        self.validation_completed.emit()

    def _on_batch_error(self, msg: str) -> None:
        self.batch_btn.setEnabled(True)
        self.status_label.setText(f"批量再校验失败：{msg}")
        self._progress_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", f"批量再校验失败：{msg}")

    def _refresh_list(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        self._progress_label.setText("刷新中...")
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/validation/{pid}/results")
        worker.result.connect(self._on_refresh_done)
        worker.error.connect(self._on_refresh_error)
        self._add_worker(worker)
        worker.start()

    def _on_refresh_done(self, data: dict) -> None:
        items = data.get("items", [])
        self.table.setRowCount(0)
        for item in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(item.get("check_type", "")))
            self.table.setItem(row, 1, QTableWidgetItem(item.get("result", "")))
            self.table.setItem(row, 2, QTableWidgetItem(item.get("problem_desc", "") or ""))
            self.table.setItem(row, 3, QTableWidgetItem(str(item.get("volume_no", "") or "")))
            self.table.setItem(row, 4, QTableWidgetItem(str(item.get("chapter_no", "") or "")))
        if items:
            self.status_label.setText(f"共 {len(items)} 项校验结果")
        else:
            self.status_label.setText("暂无校验结果")
        self._progress_label.clear()

    def _on_refresh_error(self, msg: str) -> None:
        self._progress_label.setText(f"刷新列表失败：{msg}")
        QMessageBox.critical(self, "错误", f"刷新列表失败：{msg}，请检查后重试")

    def _on_error(self, msg: str) -> None:
        self.validate_btn.setEnabled(True)
        self.status_label.setText(f"错误：{msg}")
        self._progress_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)
    def _start_repair_from_validation(self) -> None:
        """根据校验表格中的失败项触发 AI 一键修复."""
        pid = self._get_project_id()
        if not pid:
            return
        if not self._check_no_running_op():
            return
        issues: list[dict] = []
        for row in range(self.table.rowCount()):
            result_item = self.table.item(row, 1)
            if not result_item or result_item.text() != "fail":
                continue
            check_type = self.table.item(row, 0).text() if self.table.item(row, 0) else ""
            problem_desc = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
            vol_text = self.table.item(row, 3).text() if self.table.item(row, 3) else "0"
            ch_text = self.table.item(row, 4).text() if self.table.item(row, 4) else "0"
            try:
                vol_no = int(vol_text)
            except ValueError:
                vol_no = 0
            try:
                ch_no = int(ch_text)
            except ValueError:
                ch_no = 0
            issues.append({
                "level": "严重",
                "type": check_type,
                "detail": problem_desc,
                "suggestion": "",
                "volume_no": vol_no,
                "chapter_no": ch_no,
            })
        if not issues:
            QMessageBox.information(self, "提示", "没有需要修复的失败项")
            return
        self._repair_btn.setEnabled(False)
        self.validate_btn.setEnabled(False)
        self.batch_btn.setEnabled(False)
        self._progress_label.setText(f"正在 AI 修复 {len(issues)} 个问题，请稍候...")
        self._repair_sse_worker = WritingRepairSseWorker(pid, issues, repair_scope="all", garbled_config=None)
        self._repair_sse_worker.event.connect(self._on_repair_event)
        self._repair_sse_worker.finished_ok.connect(self._on_repair_finished)
        self._repair_sse_worker.error.connect(self._on_repair_error)
        self._repair_sse_worker.start()

    def _on_repair_event(self, data: dict) -> None:
        event_type = data.get("type", "")
        if event_type == "progress":
            self._progress_label.setText(
                f"修复进度：{data.get('done', 0)}/{data.get('total', 0)}"
                f"（正在修复第 {data.get('volume_no', 0)} 卷第 {data.get('chapter_no', 0)} 章）"
            )
        elif event_type == "chapter_done":
            self._progress_label.setText(
                f"第 {data.get('volume_no', 0)} 卷第 {data.get('chapter_no', 0)} 章修复完成"
            )
            char_details = data.get("char_repair_details")
            char_stat = data.get("char_repair_stat")
            if char_details:
                from src.ui.widgets.garbled_detail_window import GarbledDetailWindow
                GarbledDetailWindow(char_details, char_stat, self).exec()
        elif event_type == "chapter_skip":
            self._progress_label.setText(
                f"第 {data.get('volume_no', 0)} 卷第 {data.get('chapter_no', 0)} 章"
                f"跳过：{data.get('fail_reason', '')}"
            )
        elif event_type == "completed":
            text = (
                f"修复完成：成功 {data.get('success', 0)} / 失败 {data.get('failed', 0)}"
                f" / 跳过 {data.get('skipped', 0)}"
            )
            self._progress_label.setText(text)
            self.status_label.setText(text)
        elif event_type == "error":
            QMessageBox.warning(self, "修复错误", data.get("message", "未知错误"))

    def _on_repair_finished(self) -> None:
        self._repair_btn.setEnabled(True)
        self.validate_btn.setEnabled(True)
        self.batch_btn.setEnabled(True)
        if self._repair_sse_worker is not None:
            self._repair_sse_worker = None
        self._progress_label.clear()
        QMessageBox.information(self, "成功", "AI 修复流程已结束")
        self.validation_completed.emit()

    def _on_repair_error(self, msg: str) -> None:
        self._repair_btn.setEnabled(True)
        self.validate_btn.setEnabled(True)
        self.batch_btn.setEnabled(True)
        self._progress_label.setText(f"修复失败：{msg}")
        QMessageBox.warning(self, "修复失败", msg)
