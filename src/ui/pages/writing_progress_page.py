"""撰写进度页 - 开始/暂停/续写 + 章节列表 + 进度显示 + AI对话侧栏 + 续写/扩写/缩写 + 场景大纲."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.config.settings import get_config
from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context
from src.ui.shortcut_manager import ShortcutManager
from src.ui.sse_worker import SsePostWorker, SseWritingWorker, WritingFillSseWorker, WritingRepairSseWorker
from src.ui.widgets.batch_replace_dialog import BatchReplaceDialog
from src.ui.widgets.garbled_config_dialog import GarbledConfigDialog
from src.ui.theme.theme_qss_builder import apply_theme_variant
from src.ui.widgets.scene_outline_panel import SceneOutlinePanel
from src.ui.widgets.text_transform_dialog import TextTransformDialog
from src.ui.widgets.writing_check_report_dialog import WritingCheckReportDialog
from src.ui.widgets.writing_chat_sidebar import WritingChatSidebar


class WritingProgressPage(QWidget):
    chapter_completed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._sse_worker: SseWritingWorker | None = None
        self._chat_sidebar: WritingChatSidebar | None = None
        self._scene_panel: SceneOutlinePanel | None = None
        self._current_chapter_id: str | None = None
        self._current_chapter_content: str = ""
        self._has_unsaved_changes: bool = False
        # 本地修改待落库的章节正文：{chapter_id: new_content}
        # （预览区是只读的，正文只能通过右键「替换/插入」AI结果被修改）
        self._chapter_local_content: dict[str, str] = {}
        self._summary_sse_worker: SsePostWorker | None = None
        self._batch_summary_sse_worker: SsePostWorker | None = None
        self._repair_sse_worker: WritingRepairSseWorker | None = None
        self._fill_sse_worker: WritingFillSseWorker | None = None
        self._init_ui()
        self._init_shortcuts()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def clear_page(self) -> None:
        if getattr(self, "_sse_worker", None) is not None:
            try:
                self._sse_worker.stop()
            except Exception:
                pass
            self._sse_worker = None
        if getattr(self, "_summary_sse_worker", None) is not None:
            try:
                self._summary_sse_worker.stop()
            except Exception:
                pass
            self._summary_sse_worker = None
        if getattr(self, "_batch_summary_sse_worker", None) is not None:
            try:
                self._batch_summary_sse_worker.stop()
            except Exception:
                pass
            self._batch_summary_sse_worker = None
        if getattr(self, "_repair_sse_worker", None) is not None:
            try:
                self._repair_sse_worker.stop()
            except Exception:
                pass
            self._repair_sse_worker = None
        if getattr(self, "_fill_sse_worker", None) is not None:
            try:
                self._fill_sse_worker.stop()
            except Exception:
                pass
            self._fill_sse_worker = None
        if getattr(self, "_chat_sidebar", None) is not None:
            self._chat_sidebar.clear()
            self._chat_sidebar.setVisible(False)
        if getattr(self, "_scene_panel", None) is not None:
            self._scene_panel.clear()
            self._scene_panel.setVisible(False)
        self.progress_bar.setValue(0)
        self.table.setRowCount(0)
        self.log_edit.clear()
        self._content_preview.clear()
        self.status_label.setText("就绪")
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)
        self._ideas_input.clear()
        self._progress_label.setText("")
        self._current_chapter_id = None
        self._current_chapter_content = ""
        self._has_unsaved_changes = False
        self._chapter_local_content = {}
        self._set_save_btn_unsaved(False)

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _set_save_btn_unsaved(self, unsaved: bool) -> None:
        """设置保存按钮的未保存指示样式（主题感知）."""
        self.save_btn.setProperty("unsaved", "true" if unsaved else "false")
        self.save_btn.style().unpolish(self.save_btn)
        self.save_btn.style().polish(self.save_btn)

    def _mark_unsaved(self) -> None:
        self._has_unsaved_changes = True
        self._set_save_btn_unsaved(True)

    def is_writing(self) -> bool:
        return (
            self._sse_worker is not None
            or self._repair_sse_worker is not None
            or self._fill_sse_worker is not None
            or self._summary_sse_worker is not None
            or self._batch_summary_sse_worker is not None
        )

    def is_busy(self) -> bool:
        """是否有本地异步操作正在运行（供 MainWindow 页面切换检查）."""
        return self.is_writing()

    def _check_no_running_op(self) -> bool:
        """检查是否有操作正在运行，有则弹窗提示并返回 False."""
        if self.is_writing():
            QMessageBox.warning(self, "提示", "已有操作进行中，请等待完成或停止后再启动新操作")
            return False
        return True

    def _init_shortcuts(self) -> None:
        """注册本页面快捷键（从 shortcut_configs 表加载用户自定义配置）."""
        self._shortcut_manager = ShortcutManager(self)
        self._shortcut_manager.register("continue_writing", self._resume_writing)
        self._shortcut_manager.load()

    def reload_shortcuts(self) -> None:
        """快捷键配置变更后重新加载."""
        self._shortcut_manager.reload()

    def _toggle_ideas_panel(self) -> None:
        visible = self._ideas_panel.isVisible()
        self._ideas_panel.setVisible(not visible)
        self._ideas_toggle_btn.setText(
            "▶ 撰写思路与风格设置" if visible else "▼ 撰写思路与风格设置"
        )
        self._save_ui_state()

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self._ideas_input.clear()
        if project_id:
            self._load_chapters()
            self._check_writing_progress()
        else:
            self.clear_page()

    def _check_writing_progress(self) -> None:
        """加载项目时检测撰写进度，自动恢复续写按钮状态."""
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/writing/{pid}/chapters")
        worker.result.connect(self._on_writing_progress_check)
        worker.error.connect(self._on_progress_check_error)
        self._workers.append(worker)
        worker.start()

    def _on_progress_check_error(self, msg: str) -> None:
        """进度检测失败：不弹窗打断，但必须在进度条上可见（此前是静默吞掉）."""
        self._progress_label.setText(f"撰写进度检测失败：{msg}")

    def _on_writing_progress_check(self, chapters: list) -> None:
        """根据章节状态恢复按钮状态."""
        if not chapters:
            return
        completed = sum(1 for c in chapters if c.get("gen_status") == "completed")
        total = len(chapters)
        has_writing = any(c.get("gen_status") == "writing" for c in chapters)
        if has_writing or (0 < completed < total):
            self.start_btn.setEnabled(False)
            self.resume_btn.setEnabled(True)
            self.status_label.setText(
                f"检测到已撰写 {completed}/{total} 章，可点击续写继续"
            )
            self.log_edit.append(
                f"检测到已撰写 {completed}/{total} 章，可点击续写继续后续章节"
            )

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("撰写进度")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        self._ideas_toggle_btn = QPushButton("▶ 撰写思路与风格设置")
        self._ideas_toggle_btn.setStyleSheet(
            "text-align: left; padding: 4px 8px; font-weight: bold;"
        )
        self._ideas_toggle_btn.clicked.connect(self._toggle_ideas_panel)
        layout.addWidget(self._ideas_toggle_btn)

        self._ideas_panel = QWidget()
        self._ideas_panel.setVisible(False)
        ideas_panel_layout = QVBoxLayout(self._ideas_panel)
        ideas_panel_layout.setContentsMargins(8, 0, 8, 0)

        ideas_label = QLabel("撰写思路与想法（可选）：在此输入你对撰写的思路和想法，开始撰写或续写时会充分参考")
        ideas_label.setProperty("role", "secondary")
        ideas_label.setStyleSheet("padding: 4px 0;")
        ideas_panel_layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText("例如：第一卷注重铺垫，节奏舒缓，第二卷加快节奏进入高潮……")
        self._ideas_input.setMaximumHeight(80)
        self._ideas_input.setStyleSheet("padding: 4px;")
        ideas_panel_layout.addWidget(self._ideas_input)

        config_layout = QHBoxLayout()
        config_layout.addWidget(QLabel("风格库："))
        self.style_combo = QComboBox()
        self.style_combo.addItem("默认", None)
        config_layout.addWidget(self.style_combo, 1)
        self.load_styles_btn = QPushButton("加载风格库")
        self.load_styles_btn.clicked.connect(self._load_styles)
        config_layout.addWidget(self.load_styles_btn)
        ideas_panel_layout.addLayout(config_layout)

        proofread_layout = QHBoxLayout()
        proofread_layout.addWidget(QLabel("纠错模式："))
        self._proofread_mode_combo = QComboBox()
        self._proofread_mode_combo.addItem("关闭", "off")
        self._proofread_mode_combo.addItem("AB接力", "ab")
        self._proofread_mode_combo.addItem("ABC接力", "abc")
        self._proofread_mode_combo.currentIndexChanged.connect(self._on_proofread_mode_changed)
        proofread_layout.addWidget(self._proofread_mode_combo)
        proofread_layout.addStretch()
        ideas_panel_layout.addLayout(proofread_layout)

        self._proofread_sources_widget = QWidget()
        self._proofread_sources_widget.setVisible(False)
        proofread_sources_layout = QHBoxLayout(self._proofread_sources_widget)
        proofread_sources_layout.setContentsMargins(0, 0, 0, 0)
        proofread_sources_layout.addWidget(QLabel("A源："))
        self._proofread_source_a = QComboBox()
        proofread_sources_layout.addWidget(self._proofread_source_a)
        proofread_sources_layout.addWidget(QLabel("B源："))
        self._proofread_source_b = QComboBox()
        proofread_sources_layout.addWidget(self._proofread_source_b)
        proofread_sources_layout.addWidget(QLabel("C源："))
        self._proofread_source_c = QComboBox()
        proofread_sources_layout.addWidget(self._proofread_source_c)
        proofread_sources_layout.addWidget(QLabel("评估源："))
        self._proofread_source_eval = QComboBox()
        proofread_sources_layout.addWidget(self._proofread_source_eval)
        self._load_ai_sources_btn = QPushButton("加载AI源")
        self._load_ai_sources_btn.clicked.connect(self._load_ai_sources)
        proofread_sources_layout.addWidget(self._load_ai_sources_btn)
        ideas_panel_layout.addWidget(self._proofread_sources_widget)

        iterate_layout = QHBoxLayout()
        self._iterate_btn = QPushButton("迭代生成")
        self._iterate_btn.setVisible(False)
        self._iterate_btn.clicked.connect(self._on_iterate_generate)
        iterate_layout.addWidget(self._iterate_btn)
        iterate_layout.addWidget(QLabel("迭代次数："))
        self._iterate_count_spin = QSpinBox()
        self._iterate_count_spin.setMinimum(1)
        self._iterate_count_spin.setMaximum(100)
        self._iterate_count_spin.setValue(1)
        self._iterate_count_spin.setVisible(False)
        iterate_layout.addWidget(self._iterate_count_spin)
        iterate_layout.addWidget(QLabel("迭代单位："))
        self._iterate_unit_combo = QComboBox()
        self._iterate_unit_combo.addItem("卷", "volume")
        self._iterate_unit_combo.addItem("阶段", "phase")
        self._iterate_unit_combo.addItem("章", "chapter")
        self._iterate_unit_combo.setVisible(False)
        iterate_layout.addWidget(self._iterate_unit_combo)
        iterate_layout.addStretch()
        ideas_panel_layout.addLayout(iterate_layout)

        layout.addWidget(self._ideas_panel)

        self.status_label = QLabel("就绪")
        self.status_label.setProperty("role", "secondary")
        self.status_label.setStyleSheet("padding: 4px;")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        layout.addWidget(QLabel("章节列表："))
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["章节ID", "卷", "章", "标题", "字数", "状态", "摘要"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setMinimumSectionSize(50)
        for i, w in enumerate([100, 50, 50, 200, 80, 80, 250]):
            self.table.setColumnWidth(i, w)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        self._splitter.addWidget(self.table)

        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(QLabel("章节内容预览（选中段落可右键续写/扩写/缩写）："))
        self._content_preview = QPlainTextEdit()
        self._content_preview.setReadOnly(True)
        self._content_preview.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._content_preview.customContextMenuRequested.connect(self._on_content_context_menu)
        preview_layout.addWidget(self._content_preview)
        self._splitter.addWidget(preview_container)

        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(QLabel("撰写日志："))
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        log_layout.addWidget(self.log_edit)
        self._splitter.addWidget(log_container)

        self._splitter.setSizes([300, 300, 200])
        layout.addWidget(self._splitter, 1)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始撰写")
        apply_theme_variant(self.start_btn, "success")
        self.start_btn.clicked.connect(self._start_writing)
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._pause_writing)
        self.resume_btn = QPushButton("续写")
        self.resume_btn.setEnabled(False)
        self.resume_btn.clicked.connect(self._resume_writing)
        self.check_btn = QPushButton("校验一致性")
        self.check_btn.clicked.connect(self._check_consistency)
        self._fill_btn = QPushButton("批量补写")
        self._fill_btn.setToolTip("一键为字数不足章节扩写补全，支持暂停/续写")
        apply_theme_variant(self._fill_btn, "deep_orange")
        self._fill_btn.clicked.connect(self._toggle_fill)
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self._save_writing)
        self.list_btn = QPushButton("刷新章节列表")
        self.list_btn.clicked.connect(self._load_chapters)
        self._chat_btn = QPushButton("AI对话")
        apply_theme_variant(self._chat_btn, "cyan")
        self._chat_btn.clicked.connect(self._open_chat_sidebar)
        self._scene_btn = QPushButton("查看场景")
        apply_theme_variant(self._scene_btn, "purple")
        self._scene_btn.clicked.connect(self._open_scene_panel)
        self._batch_replace_btn = QPushButton("批量查找替换")
        apply_theme_variant(self._batch_replace_btn, "cyan")
        self._batch_replace_btn.clicked.connect(self._open_batch_replace)
        self._gen_summary_btn = QPushButton("生成摘要")
        self._gen_summary_btn.setToolTip("选中章节后，AI生成单章摘要")
        apply_theme_variant(self._gen_summary_btn, "cyan")
        self._gen_summary_btn.clicked.connect(self._generate_summary)
        self._batch_summary_btn = QPushButton("批量生成摘要")
        self._batch_summary_btn.setToolTip("批量生成全书章节摘要，支持暂停/续写")
        self._batch_summary_btn.clicked.connect(self._batch_generate_summary)
        self._summary_pause_btn = QPushButton("暂停摘要")
        self._summary_pause_btn.setEnabled(False)
        self._summary_pause_btn.clicked.connect(self._on_summary_pause)
        self._stats_btn = QPushButton("统计图表")
        apply_theme_variant(self._stats_btn, "deep_purple")
        self._stats_btn.setToolTip("打开字数统计可视化页面")
        self._stats_btn.clicked.connect(self._open_stats_page)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.resume_btn)
        btn_layout.addWidget(self.check_btn)
        btn_layout.addWidget(self._fill_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.list_btn)
        btn_layout.addWidget(self._chat_btn)
        btn_layout.addWidget(self._scene_btn)
        btn_layout.addWidget(self._batch_replace_btn)
        btn_layout.addWidget(self._gen_summary_btn)
        btn_layout.addWidget(self._batch_summary_btn)
        btn_layout.addWidget(self._summary_pause_btn)
        btn_layout.addWidget(self._stats_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._progress_label = QLabel("")
        self._progress_label.setProperty("role", "secondary")
        self._progress_label.setStyleSheet("padding: 2px;")
        layout.addWidget(self._progress_label)

        self._settings = QSettings("AiBooks", "WritingProgressPage")
        self._splitter.splitterMoved.connect(self._save_ui_state)
        self._restore_ui_state()

    def _save_ui_state(self) -> None:
        self._settings.setValue("splitterSizes", self._splitter.sizes())
        self._settings.setValue("ideasPanelExpanded", self._ideas_panel.isVisible())

    def _restore_ui_state(self) -> None:
        splitter_sizes = self._settings.value("splitterSizes")
        if splitter_sizes is not None:
            try:
                sizes = [int(s) for s in splitter_sizes]
                if len(sizes) == 3 and all(s > 0 for s in sizes):
                    self._splitter.setSizes(sizes)
            except (TypeError, ValueError):
                pass
        ideas_visible = self._settings.value("ideasPanelExpanded")
        if ideas_visible is not None:
            try:
                visible = bool(ideas_visible)
                self._ideas_panel.setVisible(visible)
                self._ideas_toggle_btn.setText(
                    "▼ 撰写思路与风格设置" if visible else "▶ 撰写思路与风格设置"
                )
            except (TypeError, ValueError):
                pass

    def _get_project_id(self) -> str | None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return None
        return ctx.project_id

    def _load_styles(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/style-libraries")
        worker.result.connect(self._on_styles_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_styles_loaded(self, libraries: list) -> None:
        self.style_combo.clear()
        self.style_combo.addItem("默认", None)
        for lib in libraries:
            self.style_combo.addItem(lib.get("name", ""), lib.get("style_library_id"))

    def _start_writing(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        if not self._check_no_running_op():
            return

        client = get_api_client()
        try:
            outline = client.get(f"/api/outlines/{pid}")
        except Exception:
            outline = None
        if not outline:
            QMessageBox.warning(self, "提示", "请先在大纲管理中生成大纲")
            return

        style_id = self.style_combo.currentData()
        user_ideas = self._ideas_input.toPlainText().strip()
        proofread_mode = self._proofread_mode_combo.currentData()
        proofread_sources = self._collect_proofread_sources()
        payload = {
            "project_id": pid,
            "style_library_id": style_id,
            "user_ideas": user_ideas,
            "proofread_mode": proofread_mode,
            "proofread_sources": proofread_sources,
        }
        worker = ApiWorker(client.post, "/api/writing/start", json=payload)
        worker.result.connect(lambda d: self._on_start_done(d, pid, style_id, user_ideas, proofread_mode, proofread_sources))
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        self.start_btn.setEnabled(False)
        self.status_label.setText("正在启动撰写...")
        worker.start()

    def _on_start_done(
        self,
        data: dict,
        pid: str,
        style_id: str | None,
        user_ideas: str = "",
        proofread_mode: str = "off",
        proofread_sources: dict | None = None,
    ) -> None:
        self.status_label.setText("撰写已启动")
        self.log_edit.append("撰写已启动，正在生成章节...")
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.progress_bar.setValue(0)

        self._sse_worker = SseWritingWorker(
            pid, style_id, user_ideas,
            proofread_mode=proofread_mode, proofread_sources=proofread_sources,
        )
        self._sse_worker.event.connect(self._on_sse_event)
        self._sse_worker.error.connect(self._on_sse_error)
        self._sse_worker.finished_ok.connect(self._on_sse_finished)
        self._sse_worker.start()
        self.log_edit.append(f"已连接进度流: /api/writing/{pid}/progress")
        self._load_chapters()

    def _pause_writing(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.post, f"/api/writing/pause?project_id={pid}")
        worker.result.connect(lambda d: (self.status_label.setText("已暂停"), self.log_edit.append("撰写已暂停"), self.pause_btn.setEnabled(False), self.resume_btn.setEnabled(True)))
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _resume_writing(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        user_ideas = self._ideas_input.toPlainText().strip()
        worker = ApiWorker(
            client.post,
            f"/api/writing/resume?project_id={pid}&user_ideas={user_ideas}",
        )
        worker.result.connect(lambda d: self._on_resume_done(d, pid, user_ideas))
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_resume_done(self, data: dict, pid: str, user_ideas: str = "") -> None:
        self.status_label.setText("续写中")
        self.log_edit.append("撰写已恢复，正在生成章节...")
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)
        style_id = self.style_combo.currentData()
        proofread_mode = self._proofread_mode_combo.currentData()
        proofread_sources = self._collect_proofread_sources()
        self._sse_worker = SseWritingWorker(
            pid, style_id, user_ideas,
            proofread_mode=proofread_mode, proofread_sources=proofread_sources,
        )
        self._sse_worker.event.connect(self._on_sse_event)
        self._sse_worker.error.connect(self._on_sse_error)
        self._sse_worker.finished_ok.connect(self._on_sse_finished)
        self._sse_worker.start()

    def _on_sse_event(self, data: dict) -> None:
        status = data.get("status", "")
        current_volume = data.get("current_volume", 0)
        current_chapter = data.get("current_chapter", 0)
        total = data.get("total_chapters", 0)
        ratio = data.get("completed_ratio", 0.0)
        message = data.get("message", "")

        if total > 0:
            self.progress_bar.setValue(int(ratio * 100))

        if status == "writing":
            self.status_label.setText(f"撰写中：第{current_volume}卷第{current_chapter}章")
            self._progress_label.setText(f"撰写中：第{current_volume}卷第{current_chapter}章")
            self.log_edit.append(f"[{ratio*100:.0f}%] {message}" if message else f"[{ratio*100:.0f}%] 第{current_volume}卷第{current_chapter}章")
        elif status == "completed":
            self.status_label.setText("全书撰写完成！")
            self._progress_label.setText("全书撰写完成")
            self.log_edit.append("全书撰写完成！")
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(False)
        elif status == "paused":
            self.status_label.setText("撰写已暂停")
            self._progress_label.setText("撰写已暂停")
            self.log_edit.append("撰写已暂停")
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(True)
        elif status == "failed":
            self.status_label.setText(f"撰写失败：{message}")
            self._progress_label.setText(f"撰写失败：{message}")
            self.log_edit.append(f"撰写失败：{message}")
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(False)
        self._load_chapters()

    def _on_sse_error(self, msg: str) -> None:
        self.status_label.setText(f"错误：{msg}")
        self._progress_label.setText(f"错误：{msg}")
        self.log_edit.append(f"错误：{msg}")
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)

    def _on_sse_finished(self) -> None:
        self._load_chapters()
        self.chapter_completed.emit()

    def _load_chapters(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/writing/{pid}/chapters")
        worker.result.connect(self._on_chapters_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_chapters_loaded(self, chapters: list) -> None:
        _status_map = {
            "pending": "待撰写",
            "outlined": "已规划",
            "writing": "撰写中",
            "completed": "已完成",
            "failed": "失败",
            "paused": "已暂停",
            "生成中": "生成中",
            "已生成": "已生成",
            "已保存": "已保存",
        }
        self.table.setRowCount(0)
        total = len(chapters)
        completed = 0
        for c in chapters:
            row = self.table.rowCount()
            self.table.insertRow(row)
            chapter_id = c.get("chapter_id", "")
            title = c.get("title", "")
            gen_status = c.get("gen_status", "")
            summary = c.get("summary", "") or ""

            id_item = QTableWidgetItem(chapter_id)
            id_item.setToolTip(chapter_id)
            self.table.setItem(row, 0, id_item)
            self.table.setItem(row, 1, QTableWidgetItem(str(c.get("volume_no", ""))))
            self.table.setItem(row, 2, QTableWidgetItem(str(c.get("chapter_no", ""))))
            title_item = QTableWidgetItem(title)
            title_item.setToolTip(title)
            self.table.setItem(row, 3, title_item)
            word_count_item = QTableWidgetItem(str(c.get("word_count", 0)))
            if c.get("underfilled", False):
                word_count_item.setForeground(QBrush(QColor("#d32f2f")))
                wpc = c.get("words_per_chapter", 0)
                wc = c.get("word_count", 0)
                if wpc > 0:
                    word_count_item.setToolTip(f"字数不足（目标 {wpc}，当前 {wc}）")
                else:
                    word_count_item.setToolTip("字数不足")
            self.table.setItem(row, 4, word_count_item)
            status_item = QTableWidgetItem(_status_map.get(gen_status, gen_status))
            status_item.setData(Qt.ItemDataRole.UserRole, gen_status)
            self.table.setItem(row, 5, status_item)
            preview = summary[:30] + "..." if len(summary) > 30 else summary
            summary_item = QTableWidgetItem(preview)
            summary_item.setToolTip(summary)
            self.table.setItem(row, 6, summary_item)
            if gen_status == "completed":
                completed += 1
        if total > 0:
            self.progress_bar.setValue(int(completed / total * 100))
        self.status_label.setText(f"共 {total} 章，已完成 {completed} 章")

    def _collect_completed_chapter_ids(self) -> list[str]:
        """从章节列表表格收集「已完成」章节的 chapter_id."""
        result: list[str] = []
        for row in range(self.table.rowCount()):
            status_item = self.table.item(row, 5)
            status_text = status_item.data(Qt.ItemDataRole.UserRole) if status_item else ""
            if status_text != "completed":
                continue
            id_item = self.table.item(row, 0)
            chapter_id = id_item.text() if id_item else ""
            if chapter_id:
                result.append(chapter_id)
        return result

    def _collect_pending_saves(self) -> list[dict]:
        """收集待落库的章节正文，严格对齐后端 ChapterSaveItem{chapter_id, new_content}.

        只提交本地被修改过的章节，避免每次保存都全量回传整本书正文
        （后端会为每次保存生成版本快照，全量回传会迅速撑爆版本链）。
        """
        completed = set(self._collect_completed_chapter_ids())
        result: list[dict] = []
        for chapter_id, content in self._chapter_local_content.items():
            if chapter_id not in completed:
                continue
            if not content:
                continue
            result.append({"chapter_id": chapter_id, "new_content": content})
        return result

    def _save_writing(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        if not self._collect_completed_chapter_ids():
            QMessageBox.warning(self, "提示", "暂无已撰写章节可保存")
            return
        chapters = self._collect_pending_saves()
        if not chapters:
            QMessageBox.information(
                self, "提示",
                "没有待保存的正文修改。\n"
                "（在预览区右键使用续写/扩写/缩写并选择替换或插入后，才会产生待保存内容）",
            )
            return
        self._progress_label.setText("保存中...")
        client = get_api_client()
        worker = ApiWorker(
            client.put,
            f"/api/writing/{pid}/save",
            json={"chapters": chapters},
        )
        worker.result.connect(self._on_save_writing_done)
        worker.error.connect(self._on_save_writing_error)
        self._workers.append(worker)
        worker.start()

    def _on_save_writing_done(self, data: dict) -> None:
        saved_count = len(self._chapter_local_content)
        self._has_unsaved_changes = False
        self._chapter_local_content = {}
        self._set_save_btn_unsaved(False)
        self._progress_label.setText("")
        if isinstance(data, dict) and data.get("saved_count") is not None:
            saved_count = data["saved_count"]
        QMessageBox.information(self, "成功", f"保存成功，已保存 {saved_count} 章")

    def _on_save_writing_error(self, msg: str) -> None:
        self._progress_label.setText("保存失败")
        QMessageBox.critical(self, "错误", f"保存失败：{msg}，请检查后重试")

    def _get_garbled_config(self) -> dict | None:
        if not get_config().garbled_detection_enabled:
            return {"enabled": False}
        return None

    def _check_consistency(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        chapters = self._collect_completed_chapter_ids()
        if not chapters:
            QMessageBox.warning(self, "提示", "请先撰写章节后再校验")
            return
        self.check_btn.setEnabled(False)
        self.status_label.setText("校验中...")
        self._progress_label.setText("校验中...")
        client = get_api_client()
        user_ideas = self._ideas_input.toPlainText().strip()
        worker = ApiWorker(
            client.post,
            f"/api/writing/{pid}/check_consistency?user_ideas={user_ideas}",
            json={"garbled_config": self._get_garbled_config()},
            timeout=300,
        )
        worker.result.connect(self._on_check_consistency_done)
        worker.error.connect(self._on_check_consistency_error)
        self._workers.append(worker)
        worker.start()

    def _on_check_consistency_done(self, data: dict) -> None:
        self.check_btn.setEnabled(True)
        self.status_label.setText("就绪")
        score = data.get("score", 0)
        issues = data.get("issues", []) or []
        self._progress_label.setText(
            f"一致性校验完成：评分 {score}/100，不符合项 {len(issues)} 条"
        )
        dialog = WritingCheckReportDialog(data, self)
        dialog.repair_requested.connect(self._start_repair)
        dialog.exec()

    def _on_check_consistency_error(self, msg: str) -> None:
        self.check_btn.setEnabled(True)
        self.status_label.setText("就绪")
        self._progress_label.setText("一致性校验失败")
        if "422" in msg:
            hint = "前置依赖缺失，请先完成大纲与章节撰写"
        elif "504" in msg:
            hint = "一致性校验超时，请重试"
        elif "502" in msg:
            hint = "AI 调用失败，请稍后重试"
        else:
            hint = msg
        QMessageBox.critical(self, "错误", f"一致性校验失败：{hint}")

    def _start_repair(self, issues: list) -> None:
        """AI 一键修复撰写内容 - SSE 流式逐章修复."""
        pid = self._get_project_id()
        if not pid:
            return
        if not self._check_no_running_op():
            return
        if not issues:
            QMessageBox.warning(self, "提示", "问题清单为空，无需修复")
            return
        self.check_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self._progress_label.setText("正在 AI 修复撰写内容，请稍候...")
        self.log_edit.append("AI 一键修复已启动，正在逐章修复撰写内容...")
        self._repair_sse_worker = WritingRepairSseWorker(pid, issues, repair_scope="all", garbled_config=self._get_garbled_config())
        self._repair_sse_worker.event.connect(self._on_repair_event)
        self._repair_sse_worker.finished_ok.connect(self._on_repair_finished)
        self._repair_sse_worker.error.connect(self._on_repair_error)
        self._repair_sse_worker.start()

    def _on_repair_event(self, data: dict) -> None:
        event_type = data.get("type", "")
        if event_type == "progress":
            text = (
                f"修复进度：{data.get('done', 0)}/{data.get('total', 0)}"
                f"（正在修复第 {data.get('volume_no', 0)} 卷第 {data.get('chapter_no', 0)} 章）"
            )
            self._progress_label.setText(text)
            self.log_edit.append(text)
        elif event_type == "chapter_done":
            self._load_chapters()
            text = f"第 {data.get('volume_no', 0)} 卷第 {data.get('chapter_no', 0)} 章修复完成"
            self._progress_label.setText(text)
            self.log_edit.append(text)
        elif event_type == "chapter_skip":
            text = (
                f"第 {data.get('volume_no', 0)} 卷第 {data.get('chapter_no', 0)} 章"
                f"跳过：{data.get('fail_reason', '')}"
            )
            self._progress_label.setText(text)
            self.log_edit.append(text)
        elif event_type == "completed":
            text = (
                f"修复完成：成功 {data.get('success', 0)} / 失败 {data.get('failed', 0)}"
                f" / 跳过 {data.get('skipped', 0)}"
            )
            self._progress_label.setText(text)
            self.log_edit.append(text)
        elif event_type == "error":
            err_msg = data.get("message", "未知错误")
            self.log_edit.append(f"修复错误：{err_msg}")
            QMessageBox.warning(self, "修复错误", err_msg)

    def _on_repair_finished(self) -> None:
        self.check_btn.setEnabled(True)
        self.start_btn.setEnabled(True)
        if self._repair_sse_worker is not None:
            self._repair_sse_worker = None
        self._load_chapters()
        self.log_edit.append("AI 一键修复流程已结束。")

    def _on_repair_error(self, msg: str) -> None:
        self.check_btn.setEnabled(True)
        self.start_btn.setEnabled(True)
        self._progress_label.setText("修复失败")
        self.log_edit.append(f"修复失败：{msg}")
        QMessageBox.warning(self, "修复失败", msg)

    def _toggle_fill(self) -> None:
        if self._fill_sse_worker is not None:
            try:
                self._fill_sse_worker.stop()
            except Exception:
                pass
            self._fill_sse_worker = None
            self._fill_btn.setText("批量补写")
            apply_theme_variant(self._fill_btn, "deep_orange")
            self.start_btn.setEnabled(True)
            self.check_btn.setEnabled(True)
            self._progress_label.setText("补写已暂停")
            self._load_chapters()
        else:
            self._start_fill()

    def _start_fill(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        if not self._check_no_running_op():
            return
        if self._has_unsaved_changes:
            ret = QMessageBox.question(
                self, "提示",
                "有未保存的改动，补写前将自动保存。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
            self._save_writing()
        self._fill_btn.setText("暂停补写")
        apply_theme_variant(self._fill_btn, "warning")
        self.start_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self._progress_label.setText("正在批量补写字数不足章节，请稍候...")
        self.log_edit.append("批量补写已启动，正在补写字数不足的章节...")
        self._fill_sse_worker = WritingFillSseWorker(pid, garbled_config=self._get_garbled_config())
        self._fill_sse_worker.event.connect(self._on_fill_event)
        self._fill_sse_worker.finished_ok.connect(self._on_fill_finished)
        self._fill_sse_worker.error.connect(self._on_fill_error)
        self._fill_sse_worker.start()
        self.log_edit.append(f"已连接补写流: /api/writing/{pid}/fill/stream")

    def _on_fill_event(self, data: dict) -> None:
        event_type = data.get("type", "")
        if event_type == "progress":
            text = (
                f"补写进度：{data.get('done', 0)}/{data.get('total', 0)}"
                f"（正在补写第 {data.get('volume_no', 0)} 卷第 {data.get('chapter_no', 0)} 章）"
            )
            self._progress_label.setText(text)
            self.log_edit.append(text)
        elif event_type == "chapter_done":
            self._load_chapters()
            status = data.get("status", "")
            before = data.get("word_count_before", 0)
            after = data.get("word_count_after", 0)
            retries = data.get("retries", 0)
            text = (
                f"第 {data.get('volume_no', 0)} 卷第 {data.get('chapter_no', 0)} 章"
                f" {status}（{before} → {after} 字，重试 {retries} 次）"
            )
            self._progress_label.setText(text)
            self.log_edit.append(text)
        elif event_type == "chapter_skip":
            text = (
                f"第 {data.get('volume_no', 0)} 卷第 {data.get('chapter_no', 0)} 章"
                f" 跳过：{data.get('fail_reason', '')}"
            )
            self._progress_label.setText(text)
            self.log_edit.append(text)
        elif event_type == "completed":
            success = data.get("success", 0)
            skipped = data.get("skipped", 0)
            still = data.get("still_underfilled", 0)
            msg = data.get("message", "")
            summary = f"补写完成：成功 {success} / 跳过 {skipped} / 仍字数不足 {still}"
            if msg:
                summary = msg
            self._progress_label.setText(summary)
            self.log_edit.append(summary)
        elif event_type == "error":
            err_msg = data.get("message", "未知错误")
            self.log_edit.append(f"补写错误：{err_msg}")
            QMessageBox.warning(self, "补写错误", err_msg)

    def _on_fill_finished(self) -> None:
        self._fill_btn.setText("批量补写")
        apply_theme_variant(self._fill_btn, "deep_orange")
        self.start_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        if self._fill_sse_worker is not None:
            self._fill_sse_worker = None
        self._load_chapters()
        self.log_edit.append("批量补写流程已结束。")

    def _on_fill_error(self, msg: str) -> None:
        self._fill_btn.setText("批量补写")
        apply_theme_variant(self._fill_btn, "deep_orange")
        self.start_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        self._progress_label.setText("补写失败")
        self.log_edit.append(f"补写失败：{msg}")
        QMessageBox.warning(self, "补写失败", msg)

    def _on_error(self, msg: str) -> None:
        self.status_label.setText(f"错误：{msg}")
        self.log_edit.append(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)
    def _on_table_selection_changed(self) -> None:
        """选中章节行后加载章节内容到预览区."""
        row = self.table.currentRow()
        if row < 0:
            self._current_chapter_id = None
            self._current_chapter_content = ""
            self._content_preview.clear()
            return
        id_item = self.table.item(row, 0)
        if not id_item:
            return
        chapter_id = id_item.text()
        if not chapter_id or chapter_id == self._current_chapter_id:
            return
        self._current_chapter_id = chapter_id
        client = get_api_client()
        worker = ApiWorker(
            client.get, f"/api/chapters/{chapter_id}/content"
        )
        worker.result.connect(self._on_preview_content_loaded)
        worker.error.connect(lambda _: self._content_preview.clear())
        self._workers.append(worker)
        worker.start()

    def _on_preview_content_loaded(self, data: dict) -> None:
        """章节内容加载完成，填充预览区."""
        self._current_chapter_content = data.get("content", "")
        self._content_preview.setPlainText(self._current_chapter_content)

    def _get_selected_paragraph(self) -> str:
        """获取预览区中当前选中的文本，未选中则返回空."""
        cursor = self._content_preview.textCursor()
        if cursor.hasSelection():
            return cursor.selectedText()
        return ""

    def _open_chat_sidebar(self) -> None:
        """打开AI对话侧栏."""
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先在章节列表中选中章节")
            return
        selected_text = self._get_selected_paragraph()
        if not selected_text:
            reply = QMessageBox.question(
                self,
                "上下文模式",
                "未选中段落，是否以「整章模式」发起对话？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            context_mode = "whole_chapter"
        else:
            context_mode = "paragraph"
        project_id = self._get_project_id()
        if not project_id:
            return
        if self._chat_sidebar is None:
            self._chat_sidebar = WritingChatSidebar(project_id, self)
            self._chat_sidebar.message_received.connect(
                lambda _: self.log_edit.append("AI对话回复已接收")
            )
        self._chat_sidebar.set_project_id(project_id)
        self._chat_sidebar.set_chapter_context(
            self._current_chapter_id, selected_text, context_mode
        )
        self._chat_sidebar.setVisible(True)
        self._chat_sidebar.raise_()

    def _open_scene_panel(self) -> None:
        """打开场景大纲面板（独立窗口）."""
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先在章节列表中选中章节")
            return
        if self._scene_panel is None:
            self._scene_panel = SceneOutlinePanel(self)
            self._scene_panel.setWindowFlags(Qt.WindowType.Window)
            self._scene_panel.scenes_loaded.connect(
                lambda n: self.log_edit.append(f"场景列表已加载：{n} 个场景")
            )
        row = self.table.currentRow()
        title = self.table.item(row, 3).text() if row >= 0 and self.table.item(row, 3) else ""
        self._scene_panel.set_chapter(self._current_chapter_id, title)
        self._scene_panel.resize(720, 420)
        self._scene_panel.setVisible(True)
        self._scene_panel.raise_()

    def _on_content_context_menu(self, pos) -> None:
        """预览区右键菜单：续写/扩写/缩写."""
        selected_text = self._get_selected_paragraph()
        menu = QMenu(self)
        continue_action = QAction("续写", self)
        continue_action.triggered.connect(lambda: self._transform_text("continue"))
        expand_action = QAction("扩写", self)
        expand_action.triggered.connect(lambda: self._transform_text("expand"))
        condense_action = QAction("缩写", self)
        condense_action.triggered.connect(lambda: self._transform_text("condense"))
        if not selected_text:
            continue_action.setEnabled(False)
            expand_action.setEnabled(False)
            condense_action.setEnabled(False)
            menu.addAction(QAction("请先选中段落", self))
        else:
            menu.addAction(continue_action)
            menu.addAction(expand_action)
            menu.addAction(condense_action)
        menu.exec(self._content_preview.mapToGlobal(pos))

    def _transform_text(self, transform_type: str) -> None:
        """发起文本变换（续写/扩写/缩写）SSE请求."""
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选中章节")
            return
        project_id = self._get_project_id()
        if not project_id:
            return
        selected_text = self._get_selected_paragraph()
        if not selected_text:
            QMessageBox.warning(self, "提示", "请先在预览区选中段落")
            return
        dialog = TextTransformDialog(
            project_id, self._current_chapter_id, selected_text, transform_type, self,
            user_ideas=self._ideas_input.toPlainText().strip(),
        )
        dialog.replace_requested.connect(self._on_replace_text)
        dialog.insert_requested.connect(self._on_insert_text)
        dialog.exec()

    def _on_replace_text(self, new_text: str) -> None:
        """替换原文：将选中段落替换为AI生成结果."""
        if not self._current_chapter_id or not new_text:
            return
        reply = QMessageBox.question(
            self,
            "确认替换",
            "确定用AI生成结果替换选中段落？此操作需保存后生效。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        cursor = self._content_preview.textCursor()
        if cursor.hasSelection():
            cursor.insertText(new_text)
            self._current_chapter_content = self._content_preview.toPlainText()
            # 记录待落库正文，供「保存」提交给 PUT /api/writing/{pid}/save
            self._chapter_local_content[self._current_chapter_id] = self._current_chapter_content
            self._mark_unsaved()
            self.log_edit.append("已替换选中段落，请点击「保存」以生效")

    def _on_insert_text(self, new_text: str) -> None:
        """插入到原文后：将AI生成结果插入到选中段落之后."""
        if not self._current_chapter_id or not new_text:
            return
        cursor = self._content_preview.textCursor()
        if cursor.hasSelection():
            end_pos = cursor.selectionEnd()
            cursor.setPosition(end_pos)
            cursor.insertText("\n" + new_text)
        else:
            self._content_preview.appendPlainText(new_text)
        self._current_chapter_content = self._content_preview.toPlainText()
        # 记录待落库正文，供「保存」提交给 PUT /api/writing/{pid}/save
        self._chapter_local_content[self._current_chapter_id] = self._current_chapter_content
        self._mark_unsaved()
        self.log_edit.append("已插入AI生成结果到原文后，请点击「保存」以生效")

    def _open_batch_replace(self) -> None:
        """打开批量查找替换对话框.

        若选中了章节行，范围为选中章节；否则范围为全書。
        """
        pid = self._get_project_id()
        if not pid:
            return
        # 收集选中行的章节ID
        chapter_ids: list[str] = []
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())
        for row in selected_rows:
            id_item = self.table.item(row, 0)
            if id_item:
                cid = id_item.text()
                if cid:
                    chapter_ids.append(cid)
        dialog = BatchReplaceDialog(pid, chapter_ids, self)
        dialog.replace_done.connect(self._on_batch_replace_done)
        dialog.exec()

    def _on_batch_replace_done(self, data: dict) -> None:
        """批量替换完成后顯示報告並刷新章节列表."""
        replaced = data.get("replaced_count", 0)
        affected = data.get("affected_chapters", 0)
        failed = data.get("failed_count", 0)
        self.log_edit.append(
            f"批量替换完成：已替换 {replaced} 处，影響 {affected} 章，失敗 {failed} 处"
        )
        self._progress_label.setText(
            f"替换完成：{replaced} 处，影響 {affected} 章"
        )
        # 刷新章节列表与预览区
        self._load_chapters()
        if self._current_chapter_id:
            client = get_api_client()
            worker = ApiWorker(
                client.get, f"/api/chapters/{self._current_chapter_id}/content"
            )
            worker.result.connect(self._on_preview_content_loaded)
            worker.error.connect(lambda _: self._content_preview.clear())
            self._workers.append(worker)
            worker.start()

    def _generate_summary(self) -> None:
        """选中章节后调用SSE生成单章摘要."""
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先在章节列表中选中章节")
            return
        if not self._check_no_running_op():
            return
        self._gen_summary_btn.setEnabled(False)
        self._progress_label.setText("单章摘要生成中...")
        self.log_edit.append(f"单章摘要生成已启动（章节ID: {self._current_chapter_id}）...")
        self._summary_sse_worker = SsePostWorker(
            "/api/summaries/generate/stream",
            payload={"chapter_id": self._current_chapter_id},
        )
        self._summary_sse_worker.event.connect(self._on_summary_event)
        self._summary_sse_worker.error.connect(self._on_summary_error)
        self._summary_sse_worker.finished_ok.connect(self._on_summary_finished)
        self._summary_sse_worker.start()

    def _on_summary_event(self, data: dict) -> None:
        summary = data.get("summary", "")
        chapter_id = data.get("chapter_id", "")
        if summary:
            text = f"摘要生成中：{summary[:30]}..."
            self._progress_label.setText(text)
            self.log_edit.append(f"章节 {chapter_id} 摘要已生成（{len(summary)} 字）")
            self._update_chapter_summary_in_table(chapter_id, summary)

    def _on_summary_error(self, msg: str) -> None:
        self._gen_summary_btn.setEnabled(True)
        self._progress_label.setText(f"摘要生成失败：{msg}")
        self.log_edit.append(f"摘要生成失败：{msg}")
        QMessageBox.critical(self, "摘要生成失败", msg)

    def _on_summary_finished(self) -> None:
        self._gen_summary_btn.setEnabled(True)
        self._progress_label.setText("单章摘要生成完成")
        self.log_edit.append("单章摘要生成完成。")
        self._load_chapters()
        self.chapter_completed.emit()

    def _batch_generate_summary(self) -> None:
        """批量生成全书章节摘要（SSE，支持暂停/续写）."""
        pid = self._get_project_id()
        if not pid:
            return
        if not self._check_no_running_op():
            return
        client = get_api_client()
        try:
            chapters = client.get(f"/api/writing/{pid}/chapters")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"获取章节列表失败：{e}")
            return
        if not chapters:
            QMessageBox.warning(self, "提示", "请先撰写章节后再生成摘要")
            return
        chapter_ids = [c.get("chapter_id") for c in chapters if c.get("chapter_id")]
        if not chapter_ids:
            QMessageBox.warning(self, "提示", "未找到章节ID，请先生成大纲")
            return
        self._batch_summary_btn.setEnabled(False)
        self._summary_pause_btn.setEnabled(True)
        self._progress_label.setText("批量摘要生成中...")
        self.log_edit.append(f"批量摘要生成已启动（共 {len(chapter_ids)} 章）...")
        self._batch_summary_sse_worker = SsePostWorker(
            "/api/summaries/batch/stream",
            payload={"project_id": pid, "chapter_ids": chapter_ids},
        )
        self._batch_summary_sse_worker.event.connect(self._on_batch_summary_event)
        self._batch_summary_sse_worker.error.connect(self._on_batch_summary_error)
        self._batch_summary_sse_worker.finished_ok.connect(self._on_batch_summary_finished)
        self._batch_summary_sse_worker.start()

    def _on_batch_summary_event(self, data: dict) -> None:
        event_type = data.get("type", "")
        summary = data.get("summary", "")
        chapter_id = data.get("chapter_id", "")
        message = data.get("message", "")
        if event_type == "progress":
            self._progress_label.setText(message)
            self.log_edit.append(message)
        elif event_type == "skipped":
            self._progress_label.setText(message)
            self.log_edit.append(message)
        elif event_type == "done":
            if message:
                self._progress_label.setText(message)
                self.log_edit.append(message)
        if summary and chapter_id:
            self._update_chapter_summary_in_table(chapter_id, summary)

    def _on_batch_summary_error(self, msg: str) -> None:
        self._batch_summary_btn.setEnabled(True)
        self._summary_pause_btn.setEnabled(False)
        self._progress_label.setText(f"批量摘要失败：{msg}")
        self.log_edit.append(f"批量摘要失败：{msg}")
        QMessageBox.critical(self, "批量摘要失败", msg)

    def _on_batch_summary_finished(self) -> None:
        self._batch_summary_btn.setEnabled(True)
        self._summary_pause_btn.setEnabled(False)
        text = self._progress_label.text()
        if "完成" not in text:
            self._progress_label.setText("批量摘要生成完成")
        self.log_edit.append("批量摘要生成流程已结束。")
        self._load_chapters()
        self.chapter_completed.emit()

    def _on_summary_pause(self) -> None:
        if self._batch_summary_sse_worker is not None:
            try:
                self._batch_summary_sse_worker.stop()
            except Exception:
                pass
            self._batch_summary_sse_worker = None
        self._summary_pause_btn.setEnabled(False)
        self._batch_summary_btn.setEnabled(True)
        self._progress_label.setText("批量摘要已暂停，可点击批量生成摘要续写")

    def _update_chapter_summary_in_table(self, chapter_id: str, summary: str) -> None:
        """将生成的摘要更新到章节列表表格对应行的摘要列."""
        if not chapter_id:
            return
        preview = summary[:30] + "..." if len(summary) > 30 else summary
        for row in range(self.table.rowCount()):
            id_item = self.table.item(row, 0)
            if id_item and id_item.text() == chapter_id:
                self.table.setItem(row, 6, QTableWidgetItem(preview))
                return

    def _open_stats_page(self) -> None:
        """打开字数统计可视化页面."""
        main_window = self.window()
        if hasattr(main_window, "_switch_page"):
            main_window._switch_page("word_stats")
        else:
            QMessageBox.information(self, "提示", "请通过工具栏切换到字数统计页面")

    def _collect_proofread_sources(self) -> dict | None:
        mode = self._proofread_mode_combo.currentData()
        if mode == "off":
            return None
        sources: dict[str, str] = {}
        source_a = self._proofread_source_a.currentData()
        source_b = self._proofread_source_b.currentData()
        if source_a:
            sources["source_a"] = source_a
        if source_b:
            sources["source_b"] = source_b
        if mode == "abc":
            source_c = self._proofread_source_c.currentData()
            source_eval = self._proofread_source_eval.currentData()
            if source_c:
                sources["source_c"] = source_c
            if source_eval:
                sources["source_eval"] = source_eval
        return sources if sources else None

    def _on_proofread_mode_changed(self) -> None:
        mode = self._proofread_mode_combo.currentData()
        show_sources = mode != "off"
        self._proofread_sources_widget.setVisible(show_sources)
        self._iterate_btn.setVisible(show_sources)
        self._iterate_count_spin.setVisible(show_sources)
        self._iterate_unit_combo.setVisible(show_sources)

    def _load_ai_sources(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/ai-sources")
        worker.result.connect(self._on_ai_sources_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_ai_sources_loaded(self, sources: list) -> None:
        for combo in (
            self._proofread_source_a,
            self._proofread_source_b,
            self._proofread_source_c,
            self._proofread_source_eval,
        ):
            combo.clear()
            combo.addItem("请选择", None)
            for s in sources:
                combo.addItem(s.get("name", ""), s.get("ai_source_id"))

    def _on_iterate_generate(self) -> None:
        mode = self._proofread_mode_combo.currentData()
        if mode == "off":
            QMessageBox.warning(self, "提示", "请先选择纠错模式")
            return
        count = self._iterate_count_spin.value()
        unit = self._iterate_unit_combo.currentData()
        QMessageBox.information(
            self, "迭代生成",
            f"迭代生成已启动：纠错模式={mode}，迭代次数={count}，迭代单位={unit}",
        )

    def _on_table_context_menu(self, pos) -> None:
        menu = QMenu(self)
        batch_menu = menu.addMenu("批量操作")

        extract_menu = batch_menu.addMenu("批量提取")
        extract_char_action = QAction("按角色", self)
        extract_char_action.triggered.connect(self._batch_extract_by_character)
        extract_menu.addAction(extract_char_action)
        extract_loc_action = QAction("按地点", self)
        extract_loc_action.triggered.connect(self._batch_extract_by_location)
        extract_menu.addAction(extract_loc_action)

        rewrite_action = QAction("批量改写", self)
        rewrite_action.triggered.connect(self._batch_rewrite)
        batch_menu.addAction(rewrite_action)

        expand_action = QAction("批量扩写", self)
        expand_action.triggered.connect(self._batch_expand)
        batch_menu.addAction(expand_action)

        menu.exec(self.table.mapToGlobal(pos))

    def _batch_extract_by_character(self) -> None:
        QMessageBox.information(self, "批量提取", "批量提取（按角色）功能已触发")

    def _batch_extract_by_location(self) -> None:
        QMessageBox.information(self, "批量提取", "批量提取（按地点）功能已触发")

    def _batch_rewrite(self) -> None:
        QMessageBox.information(self, "批量改写", "批量改写功能已触发")

    def _batch_expand(self) -> None:
        QMessageBox.information(self, "批量扩写", "批量扩写功能已触发")

