"""章节编辑页 - 正文编辑+保存触发再校验+润色并排预览+确认/拒绝+阅读模式+快捷键+续写/扩写/缩写+批量替换+版本管理+锁定+批注."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QAction, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.config.settings import get_config
from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context
from src.ui.shortcut_manager import ShortcutManager
from src.ui.sse_worker import SsePostWorker
from src.ui.widgets.annotation_edit_dialog import AnnotationEditDialog
from src.ui.widgets.batch_replace_dialog import BatchReplaceDialog
from src.ui.widgets.chapter_merge_dialog import ChapterMergeDialog
from src.ui.widgets.chapter_split_dialog import ChapterSplitDialog
from src.ui.widgets.chapter_version_dialog import ChapterVersionDialog
from src.ui.widgets.connection_dialog import ConnectionDialog
from src.ui.widgets.reading_mode_controller import ReadingModeController
from src.ui.widgets.side_by_side_preview import SideBySidePreview
from src.ui.widgets.text_transform_dialog import TextTransformDialog


class _FindReplaceDialog(QDialog):
    """查找替换对话框."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("查找与替换")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("查找内容："))
        self.find_edit = QLineEdit()
        layout.addWidget(self.find_edit)

        layout.addWidget(QLabel("替换为："))
        self.replace_edit = QLineEdit()
        layout.addWidget(self.replace_edit)

        self.case_check = QCheckBox("区分大小写")
        layout.addWidget(self.case_check)

        btn_layout = QHBoxLayout()
        self.find_btn = QPushButton("查找下一个")
        self.replace_btn = QPushButton("替换")
        self.replace_all_btn = QPushButton("全部替换")
        self.close_btn = QPushButton("关闭")
        self.find_btn.clicked.connect(self.accept_find)
        self.replace_btn.clicked.connect(self.accept_replace)
        self.replace_all_btn.clicked.connect(self.accept_replace_all)
        self.close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.find_btn)
        btn_layout.addWidget(self.replace_btn)
        btn_layout.addWidget(self.replace_all_btn)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

        self._action: str = ""

    def accept_find(self) -> None:
        self._action = "find"
        self.accept()

    def accept_replace(self) -> None:
        self._action = "replace"
        self.accept()

    def accept_replace_all(self) -> None:
        self._action = "replace_all"
        self.accept()

    @property
    def action(self) -> str:
        return self._action

    def find_text(self) -> str:
        return self.find_edit.text()

    def replace_text(self) -> str:
        return self.replace_edit.text()

    def case_sensitive(self) -> bool:
        return self.case_check.isChecked()


class ChapterEditPage(QWidget):
    polish_confirmed = Signal()
    new_chapter_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._current_chapter_id: str | None = None
        self._polished_content: str | None = None
        self._saved_content: str = ""
        self._has_unsaved_changes: bool = False
        self._reading_mode: bool = False
        self._is_locked: bool = False
        self._annotations: list[dict] = []
        self._annotation_dock: QDockWidget | None = None
        self._annotation_table: QTableWidget | None = None
        self._annotation_filter: QComboBox | None = None
        # 章节列表缓存，供合并/拆分/衔接优化复用（后端接口一致）
        self._chapters_cache: list[dict] = []
        # 外部跳转（敏感词命中）落地后要高亮的目标词
        self._pending_find_word: str = ""
        self._pending_jump_chapter_id: str = ""
        self._annotation_check_timer = QTimer(self)
        self._annotation_check_timer.setSingleShot(True)
        self._annotation_check_timer.timeout.connect(self._check_and_invalidate_orphan_annotations)
        self._summary_sse_worker: SsePostWorker | None = None
        self._init_ui()
        self._init_shortcuts()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def _add_worker(self, worker: ApiWorker) -> None:
        """注册 ApiWorker 并在完成后自动清理，避免内存泄漏."""
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))

    def _cleanup_worker(self, worker: ApiWorker) -> None:
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    def is_busy(self) -> bool:
        """是否有本地异步操作正在运行."""
        return len(self._workers) > 0 or self._summary_sse_worker is not None

    def _check_no_running_op(self) -> bool:
        """检查本地和后端是否有操作正在运行."""
        if self.is_busy():
            QMessageBox.warning(self, "提示", "当前页面有操作进行中，请等待完成后再启动新操作")
            return False
        pid = self._get_project_id()
        if pid:
            try:
                client = get_api_client()
                status = client.get(f"/api/writing/{pid}/op_status")
                if status.get("is_busy"):
                    op = status.get("running_op", "未知")
                    QMessageBox.warning(
                        self, "提示",
                        f"项目正在执行{op}操作，请等待完成后再编辑章节内容",
                    )
                    return False
            except Exception:
                pass
        return True

    def clear_page(self) -> None:
        self.chapter_combo.clear()
        self.editor.clear()
        self.preview.setVisible(False)
        self.accept_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self._current_chapter_id = None
        self._polished_content = None
        self._saved_content = ""
        self.status_label.clear()
        self._progress_label.clear()
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")
        self._exit_reading_mode()
        self._is_locked = False
        self._update_lock_ui()
        self._annotations = []
        self._refresh_annotation_table()

    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _mark_unsaved(self) -> None:
        self._has_unsaved_changes = True
        self.save_btn.setStyleSheet("border: 2px solid #ff9800;")

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self.clear_page()
        self._ideas_input.clear()
        if project_id:
            self._load_chapters()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("章节编辑")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        # 编辑模式容器
        self._edit_container = QWidget()
        edit_layout = QVBoxLayout(self._edit_container)
        edit_layout.setContentsMargins(0, 0, 0, 0)

        ideas_label = QLabel(
            "章节编辑思路与想法（可选）：在此输入你对润色的思路和想法，AI润色时会充分参考"
        )
        ideas_label.setStyleSheet("color: #555; padding: 4px 8px;")
        edit_layout.addWidget(ideas_label)
        self._ideas_input = QPlainTextEdit()
        self._ideas_input.setPlaceholderText(
            "例如：保持原有叙事节奏，增强环境描写，减少AI感……"
        )
        self._ideas_input.setMaximumHeight(80)
        self._ideas_input.setStyleSheet("padding: 4px;")
        edit_layout.addWidget(self._ideas_input)

        status_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        self._word_count_label = QLabel("")
        self._word_count_label.setStyleSheet("color: #666; padding: 4px;")
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self._word_count_label)
        edit_layout.addLayout(status_row)

        nav_layout = QHBoxLayout()
        nav_layout.addWidget(QLabel("选择章节："))
        self.chapter_combo = QComboBox()
        self.chapter_combo.setMinimumWidth(400)
        self.chapter_combo.currentIndexChanged.connect(self._on_chapter_selected)
        nav_layout.addWidget(self.chapter_combo, 1)
        self._prev_chapter_btn = QPushButton("上一章")
        self._prev_chapter_btn.clicked.connect(self._go_prev_chapter)
        self._next_chapter_btn = QPushButton("下一章")
        self._next_chapter_btn.clicked.connect(self._go_next_chapter)
        nav_layout.addWidget(self._prev_chapter_btn)
        nav_layout.addWidget(self._next_chapter_btn)
        edit_layout.addLayout(nav_layout)

        self.editor = QPlainTextEdit()
        self.editor.setStyleSheet("font-size: 14px; line-height: 1.6;")
        self.editor.textChanged.connect(self._on_editor_text_changed)
        self.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.editor.customContextMenuRequested.connect(self._on_editor_context_menu)
        edit_layout.addWidget(self.editor, 1)

        self.preview = SideBySidePreview()
        self.preview.setVisible(False)
        edit_layout.addWidget(self.preview)

        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新章节列表")
        self.refresh_btn.clicked.connect(self._load_chapters)
        self.save_btn = QPushButton("保存并再校验")
        self.save_btn.setStyleSheet(
            "background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self.save_btn.clicked.connect(self._save_and_revalidate)
        self.polish_btn = QPushButton("AI润色")
        self.polish_btn.clicked.connect(self._polish)
        self.accept_btn = QPushButton("采纳润色")
        self.accept_btn.setEnabled(False)
        self.accept_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self.accept_btn.clicked.connect(self._accept_polish)
        self.reject_btn = QPushButton("拒绝润色")
        self.reject_btn.setEnabled(False)
        self.reject_btn.clicked.connect(self._reject_polish)
        self.check_btn = QPushButton("校验一致性")
        self.check_btn.clicked.connect(self._check_consistency)
        self._summary_btn = QPushButton("生成摘要")
        self._summary_btn.setStyleSheet(
            "background-color: #00838f; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._summary_btn.clicked.connect(self._generate_summary)
        self.reading_mode_btn = QPushButton("阅读模式")
        self.reading_mode_btn.setStyleSheet(
            "background-color: #9c27b0; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self.reading_mode_btn.clicked.connect(self._enter_reading_mode)
        self._batch_replace_btn = QPushButton("批量查找替换")
        self._batch_replace_btn.setStyleSheet(
            "background-color: #00838f; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._batch_replace_btn.clicked.connect(self._open_batch_replace)
        self._version_btn = QPushButton("版本管理")
        self._version_btn.clicked.connect(self._open_version_dialog)
        self._lock_btn = QPushButton("锁定")
        self._lock_btn.setCheckable(True)
        self._lock_btn.clicked.connect(self._on_lock_clicked)
        self._annotation_btn = QPushButton("批注侧栏")
        self._annotation_btn.clicked.connect(self._toggle_annotation_dock)
        self._merge_btn = QPushButton("合并章节")
        self._merge_btn.setToolTip("把多个相邻章节合并为一章（原章节会生成版本快照）")
        self._merge_btn.clicked.connect(self._open_merge_dialog)
        self._split_btn = QPushButton("拆分章节")
        self._split_btn.setToolTip("按字符偏移把当前章节拆成多章")
        self._split_btn.clicked.connect(self._open_split_dialog)
        self._connection_btn = QPushButton("衔接优化")
        self._connection_btn.setToolTip("分析相邻两章的衔接并生成过渡段")
        self._connection_btn.clicked.connect(self._open_connection_dialog)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.polish_btn)
        btn_layout.addWidget(self.accept_btn)
        btn_layout.addWidget(self.reject_btn)
        btn_layout.addWidget(self.check_btn)
        btn_layout.addWidget(self._summary_btn)
        btn_layout.addWidget(self.reading_mode_btn)
        btn_layout.addWidget(self._batch_replace_btn)
        btn_layout.addWidget(self._version_btn)
        btn_layout.addWidget(self._lock_btn)
        btn_layout.addWidget(self._annotation_btn)
        btn_layout.addWidget(self._merge_btn)
        btn_layout.addWidget(self._split_btn)
        btn_layout.addWidget(self._connection_btn)

        btn_layout.addStretch()
        edit_layout.addLayout(btn_layout)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color: #666; padding: 2px;")
        edit_layout.addWidget(self._progress_label)

        layout.addWidget(self._edit_container, 1)

        # 阅读模式控制器（默认隐藏）
        self._reading_controller = ReadingModeController()
        self._reading_controller.exit_reading.connect(self._exit_reading_mode)
        self._reading_controller.setVisible(False)
        layout.addWidget(self._reading_controller, 1)

    def _init_shortcuts(self) -> None:
        """注册本页面快捷键（从 shortcut_configs 表加载用户自定义配置）."""
        self._shortcut_manager = ShortcutManager(self)
        self._shortcut_manager.register("save", self._save_and_revalidate)
        self._shortcut_manager.register("find", self._open_find_dialog)
        self._shortcut_manager.register("replace", self._open_replace_dialog)
        self._shortcut_manager.register("new_chapter", self._request_new_chapter)
        self._shortcut_manager.load()

    def reload_shortcuts(self) -> None:
        """快捷键配置变更后重新加载."""
        self._shortcut_manager.reload()

    def _enter_reading_mode(self) -> None:
        """进入阅读模式：隐藏编辑工具栏，以 ReadingModeView 展示章节内容."""
        content = self.editor.toPlainText()
        if not content.strip():
            QMessageBox.information(self, "提示", "章节内容为空，无法进入阅读模式")
            return
        self._reading_mode = True
        self._edit_container.setVisible(False)
        self._reading_controller.set_content(content)
        self._reading_controller.setVisible(True)

    def _exit_reading_mode(self) -> None:
        """退出阅读模式，返回编辑模式."""
        if not self._reading_mode:
            return
        self._reading_mode = False
        self._reading_controller.setVisible(False)
        self._edit_container.setVisible(True)

    def _open_find_dialog(self) -> None:
        """Ctrl+F 触发查找."""
        if self._reading_mode:
            QMessageBox.information(
                self, "提示",
                "阅读模式不支持查找。\n请点击阅读模式工具栏的「退出阅读模式」返回编辑模式后再查找。",
            )
            return
        self._open_find_replace_dialog()

    def _open_find_replace_dialog(self) -> None:
        """统一走 _FindReplaceDialog（此前查找用的是 QInputDialog，不支持替换/区分大小写）."""
        dialog = _FindReplaceDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        find_text = dialog.find_text()
        if not find_text:
            return
        action = dialog.action
        if action == "find":
            self._do_find(find_text, dialog.case_sensitive())
        elif action == "replace":
            self._do_replace(find_text, dialog.replace_text(), dialog.case_sensitive())
        elif action == "replace_all":
            self._do_replace_all(find_text, dialog.replace_text(), dialog.case_sensitive())

    def _open_replace_dialog(self) -> None:
        """Ctrl+H 触发替换."""
        if self._reading_mode:
            QMessageBox.information(
                self, "提示",
                "阅读模式不支持替换。\n请点击阅读模式工具栏的「退出阅读模式」返回编辑模式后再操作。",
            )
            return
        dialog = _FindReplaceDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        action = dialog.action
        find_text = dialog.find_text()
        replace_text = dialog.replace_text()
        if not find_text:
            return
        if action == "find":
            self._do_find(find_text, dialog.case_sensitive())
        elif action == "replace":
            self._do_replace(find_text, replace_text, dialog.case_sensitive())
        elif action == "replace_all":
            self._do_replace_all(find_text, replace_text, dialog.case_sensitive())

    def _do_find(self, text: str, case_sensitive: bool = False) -> None:
        cursor = self.editor.textCursor()
        options = (
            QTextCursor.FindCaseSensitively if case_sensitive else 0
        )
        found = self.editor.find(text, options)
        if not found:
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.editor.setTextCursor(cursor)
            if not self.editor.find(text, options):
                QMessageBox.information(self, "查找", "未找到匹配内容")

    def _do_replace(
        self, find_text: str, replace_text: str, case_sensitive: bool = False
    ) -> None:
        cursor = self.editor.textCursor()
        options = (
            QTextCursor.FindCaseSensitively if case_sensitive else 0
        )
        selected = cursor.selectedText() if cursor.hasSelection() else ""
        match = selected == find_text if case_sensitive else selected.lower() == find_text.lower()
        if match and selected:
            cursor.insertText(replace_text)
        found = self.editor.find(find_text, options)
        if not found:
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.editor.setTextCursor(cursor)
            found = self.editor.find(find_text, options)
        if not found:
            QMessageBox.information(self, "替换", "未找到匹配内容")

    def _do_replace_all(
        self, find_text: str, replace_text: str, case_sensitive: bool = False
    ) -> None:
        content = self.editor.toPlainText()
        if case_sensitive:
            new_content = content.replace(find_text, replace_text)
            count = content.count(find_text)
        else:
            # 大小写不敏感：用 re 忽略大小写替换，并同步统计真实命中数
            new_content, count = re.subn(
                re.escape(find_text), replace_text.replace("\\", "\\\\"),
                content, flags=re.IGNORECASE,
            )
        if count == 0:
            QMessageBox.information(self, "全部替换", "未找到匹配内容")
            return
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(new_content)
        QMessageBox.information(self, "全部替换", f"已替换 {count} 处")

    def _request_new_chapter(self) -> None:
        """Ctrl+N 触发新建章节请求（由 main_window 处理跳转）."""
        self.new_chapter_requested.emit()

    def _on_editor_text_changed(self) -> None:
        self._mark_unsaved()
        text = self.editor.toPlainText()
        char_count = len(text)
        word_count = len(text.replace(" ", "").replace("\n", ""))
        self._word_count_label.setText(f"字数：{word_count}（字符：{char_count}）")
        self._annotation_check_timer.start(500)

    def _get_project_id(self) -> str | None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return None
        return ctx.project_id

    def _load_chapters(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/writing/{pid}/chapters")
        worker.result.connect(self._on_chapters_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_chapters_loaded(self, chapters: list) -> None:
        self._chapters_cache = list(chapters or [])
        self.chapter_combo.clear()
        self.chapter_combo.addItem("-- 选择章节 --", None)
        for c in self._chapters_cache:
            label = f"第{c['volume_no']}卷第{c['chapter_no']}章 {c['title']}"
            self.chapter_combo.addItem(label, c)
        # 处理「章节不在列表中时先刷新再跳转」的延迟跳转
        if self._pending_jump_chapter_id:
            target = self._pending_jump_chapter_id
            self._pending_jump_chapter_id = ""
            for i in range(self.chapter_combo.count()):
                info = self.chapter_combo.itemData(i)
                if info and info.get("chapter_id") == target:
                    self.chapter_combo.setCurrentIndex(i)
                    return

    def _on_chapter_selected(self, index: int) -> None:
        if index <= 0:
            return
        info = self.chapter_combo.itemData(index)
        if not info:
            return
        if self._has_unsaved_changes:
            ret = QMessageBox.question(
                self, "提示",
                "当前章节有未保存的修改，是否保存？",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if ret == QMessageBox.StandardButton.Save:
                self._save_and_revalidate()
            elif ret == QMessageBox.StandardButton.Cancel:
                return
        self._current_chapter_id = info["chapter_id"]
        client = get_api_client()
        worker = ApiWorker(
            client.get, f"/api/chapters/{self._current_chapter_id}/content"
        )
        worker.result.connect(self._on_content_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()
        self._load_lock_status()
        self._load_annotations()

    def _go_prev_chapter(self) -> None:
        idx = self.chapter_combo.currentIndex()
        if idx > 1:
            self.chapter_combo.setCurrentIndex(idx - 1)

    def _go_next_chapter(self) -> None:
        idx = self.chapter_combo.currentIndex()
        if idx < self.chapter_combo.count() - 1:
            self.chapter_combo.setCurrentIndex(idx + 1)

    # ---------- 章节合并 / 拆分 / 衔接优化 ----------
    def _open_merge_dialog(self) -> None:
        if not self._chapters_cache:
            QMessageBox.information(self, "提示", "章节列表尚未加载，请稍后重试")
            return
        dialog = ChapterMergeDialog(self._chapters_cache, self)
        dialog.merge_done.connect(self._on_chapter_structure_changed)
        dialog.exec()

    def _open_split_dialog(self) -> None:
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择要拆分的章节")
            return
        chapter = None
        idx = self.chapter_combo.currentIndex()
        if idx > 0:
            chapter = self.chapter_combo.itemData(idx)
        if not chapter:
            QMessageBox.warning(self, "提示", "未获取到章节信息")
            return
        if self._is_locked:
            QMessageBox.warning(self, "提示", "章节已锁定，请先解锁再拆分")
            return
        content = self.editor.toPlainText()
        if len(content) < 2:
            QMessageBox.warning(self, "提示", "章节正文为空，无法拆分")
            return
        dialog = ChapterSplitDialog(
            chapter, content, self.editor.textCursor().position(), self
        )
        dialog.split_done.connect(self._on_chapter_structure_changed)
        dialog.exec()

    def _open_connection_dialog(self) -> None:
        pid = self._get_project_id()
        if not pid:
            return
        if not self._chapters_cache:
            QMessageBox.information(self, "提示", "章节列表尚未加载，请稍后重试")
            return
        # 默认分析「当前章 + 它的下一章」
        prev_id = self._current_chapter_id or ""
        next_id = ""
        order = [c.get("chapter_id", "") for c in self._chapters_cache]
        if prev_id in order:
            pos = order.index(prev_id)
            if pos + 1 < len(order):
                next_id = order[pos + 1]
        dialog = ConnectionDialog(pid, self._chapters_cache, prev_id, next_id, self)
        dialog.transition_generated.connect(self._on_transition_generated)
        dialog.exec()

    def _on_transition_generated(self, transition: str) -> None:
        """把过渡段插入到当前编辑器光标处（用户可自行挪到目标章节）."""
        if not transition:
            return
        cursor = self.editor.textCursor()
        cursor.insertText(transition)
        self._mark_unsaved()
        self.status_label.setText("已插入过渡段，请点击「保存并再校验」落库")

    def _on_chapter_structure_changed(self, _data: dict) -> None:
        """合并/拆分后章节编号已变化，重新拉取列表."""
        self._current_chapter_id = None
        self._load_chapters()

    def _load_lock_status(self) -> None:
        """加載当前章节的锁定状态."""
        if not self._current_chapter_id:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.get, f"/api/chapters/{self._current_chapter_id}/lock"
        )
        worker.result.connect(self._on_lock_status_loaded)
        worker.error.connect(self._on_lock_status_error)
        self._add_worker(worker)
        worker.start()

    def _on_lock_status_error(self, msg: str) -> None:
        self._is_locked = False
        self._update_lock_ui()
        self.status_label.setText(f"锁定状态加载失败：{msg}")

    def _on_lock_status_loaded(self, data: dict) -> None:
        self._is_locked = bool(data.get("is_locked", False))
        self._update_lock_ui()

    def _on_content_loaded(self, data: dict) -> None:
        self.editor.setPlainText(data.get("content", ""))
        self._saved_content = data.get("content", "")
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")
        self.status_label.setText(
            f"已加载：{data.get('title', '')}（{data.get('word_count', 0)}字）"
        )
        if self._pending_find_word:
            self._locate_word(self._pending_find_word)
            self._pending_find_word = ""

    def _locate_word(self, word: str) -> None:
        """在编辑器中定位并高亮首个匹配项（敏感词命中跳转用）."""
        if not word:
            return
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.editor.setTextCursor(cursor)
        if self.editor.find(word):
            self.editor.setFocus()
            self.status_label.setText(f"已定位到「{word}」，可用 Ctrl+F 继续查找下一个")
        else:
            self.status_label.setText(f"章节已打开，但未在正文中找到「{word}」")

    def load_chapter(self, chapter_id: str, word: str = "") -> None:
        """外部跳转到指定章节并定位关键词（供敏感词页双击命中项调用）."""
        self._pending_find_word = word
        for i in range(self.chapter_combo.count()):
            info = self.chapter_combo.itemData(i)
            if info and info.get("chapter_id") == chapter_id:
                if i == self.chapter_combo.currentIndex():
                    # 已是当前章节：不会触发 currentIndexChanged，手动加载并定位
                    self._current_chapter_id = chapter_id
                    client = get_api_client()
                    worker = ApiWorker(
                        client.get, f"/api/chapters/{chapter_id}/content"
                    )
                    worker.result.connect(self._on_content_loaded)
                    worker.error.connect(self._on_error)
                    self._add_worker(worker)
                    worker.start()
                else:
                    self.chapter_combo.setCurrentIndex(i)
                return
        # 章节不在下拉框中：先刷新列表再跳转
        self._pending_jump_chapter_id = chapter_id
        self._load_chapters()

    def _get_garbled_config(self) -> dict | None:
        if not get_config().garbled_detection_enabled:
            return {"enabled": False}
        return None

    def _save_and_revalidate(self) -> None:
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择章节")
            return
        if not self._check_no_running_op():
            return
        if self._is_locked:
            QMessageBox.warning(
                self, "章节已锁定", "当前章节已锁定，请先解锁再编辑"
            )
            return
        content = self.editor.toPlainText()
        if not content.strip():
            QMessageBox.warning(self, "提示", "内容不能为空")
            return
        client = get_api_client()
        worker = ApiWorker(
            client.put,
            f"/api/chapters/{self._current_chapter_id}/content",
            json={"new_content": content, "garbled_config": self._get_garbled_config()},
        )
        worker.result.connect(self._on_saved)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        self.save_btn.setEnabled(False)
        worker.start()

    def _on_saved(self, data: dict) -> None:
        self._saved_content = data.get("content", "")
        self._has_unsaved_changes = False
        self.save_btn.setStyleSheet("")
        self.status_label.setText(
            f"已保存（{data.get('word_count', 0)}字），正在再校验..."
        )
        client = get_api_client()
        worker = ApiWorker(
            client.post, f"/api/chapters/{self._current_chapter_id}/revalidate"
        )
        worker.result.connect(self._on_revalidated)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_revalidated(self, data: dict) -> None:
        items = data.get("items", [])
        all_pass = data.get("all_pass", False)
        if all_pass:
            self.status_label.setText("再校验通过")
            QMessageBox.information(self, "校验结果", "再校验全部通过")
        else:
            lines = ["再校验发现问题："]
            for item in items:
                if item.get("result") == "fail":
                    lines.append(
                        f"  [{item.get('check_type', '')}] {item.get('problem_desc', '')}"
                    )
            self.status_label.setText("再校验发现问题，请查看详情")
            QMessageBox.warning(self, "校验结果", "\n".join(lines))

    def _polish(self) -> None:
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择章节")
            return
        if not self._check_no_running_op():
            return
        self.status_label.setText("AI润色中...")
        self._progress_label.setText("AI润色中...")
        self.polish_btn.setEnabled(False)
        client = get_api_client()
        user_ideas = self._ideas_input.toPlainText().strip()
        worker = ApiWorker(
            client.post,
            f"/api/chapters/{self._current_chapter_id}/polish",
            params={"user_ideas": user_ideas},
            json={"garbled_config": self._get_garbled_config()},
        )
        worker.result.connect(self._on_polished)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_polished(self, data: dict) -> None:
        self.polish_btn.setEnabled(True)
        self._polished_content = data.get("polished_content", "")
        original = self.editor.toPlainText()
        notes = data.get("adjust_notes", [])
        self.preview.set_content(original, self._polished_content, notes)
        self.preview.setVisible(True)
        self.accept_btn.setEnabled(True)
        self.reject_btn.setEnabled(True)
        self.status_label.setText("AI润色完成，请确认是否采纳")
        self._progress_label.setText("润色完成，请确认")

    def _accept_polish(self) -> None:
        if not self._current_chapter_id or not self._polished_content:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            f"/api/chapters/{self._current_chapter_id}/polish/confirm",
            json={"action": "accept", "garbled_config": self._get_garbled_config()},
        )
        worker.result.connect(self._on_accept_done)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _reject_polish(self) -> None:
        if not self._current_chapter_id:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            f"/api/chapters/{self._current_chapter_id}/polish/confirm",
            json={"action": "reject"},
        )
        worker.result.connect(self._on_reject_done)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_accept_done(self, data: dict) -> None:
        self.editor.setPlainText(data.get("content", ""))
        self.preview.setVisible(False)
        self.accept_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self._polished_content = None
        self.status_label.setText("已采纳润色")
        self._progress_label.clear()
        self._mark_unsaved()
        self.polish_confirmed.emit()

    def _on_reject_done(self, data: dict) -> None:
        self.preview.setVisible(False)
        self.accept_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self._polished_content = None
        self.status_label.setText("已拒绝润色")
        self._progress_label.clear()
        self.polish_confirmed.emit()

    def _check_consistency(self) -> None:
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择章节")
            return
        if not self._check_no_running_op():
            return
        self.check_btn.setEnabled(False)
        self.status_label.setText("校验中...")
        self._progress_label.setText("校验中...")
        client = get_api_client()
        user_ideas = self._ideas_input.toPlainText().strip()
        worker = ApiWorker(
            client.post,
            f"/api/chapters/{self._current_chapter_id}/check_consistency",
            params={"user_ideas": user_ideas},
            json={"garbled_config": self._get_garbled_config()},
        )
        worker.result.connect(self._on_check_consistency_done)
        worker.error.connect(self._on_check_consistency_error)
        self._add_worker(worker)
        worker.start()

    def _on_check_consistency_done(self, data: dict) -> None:
        self.check_btn.setEnabled(True)
        self.status_label.clear()
        score = data.get("score", 0)
        issues = data.get("issues", [])
        text = data.get("text", "")
        report_lines = [
            f"评分：{score}/100",
            f"发现问题：{len(issues)} 条",
            "",
        ]
        if issues:
            report_lines.append("问题清单：")
            for i, issue in enumerate(issues, 1):
                level = issue.get("level", "") if isinstance(issue, dict) else getattr(issue, "level", "")
                typ = issue.get("type", "") if isinstance(issue, dict) else getattr(issue, "type", "")
                detail = issue.get("detail", "") if isinstance(issue, dict) else getattr(issue, "detail", "")
                suggestion = issue.get("suggestion", "") if isinstance(issue, dict) else getattr(issue, "suggestion", "")
                report_lines.append(f"  {i}. [{level}] {typ}：{detail}")
                if suggestion:
                    report_lines.append(f"     建议：{suggestion}")
            report_lines.append("")
        report_lines.append("详细报告：")
        report_lines.append(text)
        report = "\n".join(report_lines)
        QMessageBox.information(self, "一致性校验报告", report)
        self._progress_label.setText(
            f"校验完成：评分 {score}/100，问题 {len(issues)} 条"
        )

    def _on_check_consistency_error(self, msg: str) -> None:
        self.check_btn.setEnabled(True)
        self.status_label.clear()
        self._progress_label.clear()
        if "API 404" in msg:
            tip = "章节不存在"
        elif "API 422" in msg:
            tip = "大纲不存在"
        elif "API 504" in msg:
            tip = "校验超时"
        elif "API 502" in msg:
            tip = "AI 调用失败"
        else:
            tip = msg
        QMessageBox.critical(self, "校验失败", f"一致性校验失败：{tip}")

    def _generate_summary(self) -> None:
        """为当前章节生成摘要 - SSE 流式."""
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择章节")
            return
        if not self._check_no_running_op():
            return
        self._summary_btn.setEnabled(False)
        self.status_label.setText("摘要生成中...")
        self._progress_label.setText("摘要生成中...")
        self._summary_sse_worker = SsePostWorker(
            "/api/summaries/generate/stream",
            payload={"chapter_id": self._current_chapter_id},
        )
        self._summary_sse_worker.event.connect(self._on_summary_event)
        self._summary_sse_worker.finished_ok.connect(self._on_summary_finished)
        self._summary_sse_worker.error.connect(self._on_summary_error)
        self._summary_sse_worker.start()

    def _on_summary_event(self, data: dict) -> None:
        summary = data.get("summary", "")
        event_type = data.get("type", "")
        if event_type == "error":
            QMessageBox.warning(self, "摘要生成失败", data.get("message", "未知错误"))
            return
        if summary:
            self._progress_label.setText(f"摘要生成中：{summary[:30]}...")

    def _on_summary_finished(self) -> None:
        self._summary_btn.setEnabled(True)
        self.status_label.setText("摘要生成完成")
        self._progress_label.clear()
        self._load_chapters()
        QMessageBox.information(self, "成功", "章节摘要生成完成")

    def _on_summary_error(self, msg: str) -> None:
        self._summary_btn.setEnabled(True)
        self.status_label.setText(f"摘要生成失败：{msg}")
        self._progress_label.clear()
        QMessageBox.critical(self, "摘要生成失败", msg)

    def _on_error(self, msg: str) -> None:
        self.save_btn.setEnabled(True)
        self.polish_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        self._progress_label.clear()
        self.status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)
    def _on_editor_context_menu(self, pos) -> None:
        """编辑器右键菜单：续写/扩写/缩写/添加批注."""
        cursor = self.editor.textCursor()
        has_selection = cursor.hasSelection()
        menu = QMenu(self)
        continue_action = QAction("续写", self)
        continue_action.triggered.connect(lambda: self._transform_text("continue"))
        expand_action = QAction("扩写", self)
        expand_action.triggered.connect(lambda: self._transform_text("expand"))
        condense_action = QAction("缩写", self)
        condense_action.triggered.connect(lambda: self._transform_text("condense"))
        annotation_action = QAction("添加批注", self)
        annotation_action.triggered.connect(self._add_annotation_from_selection)
        if not has_selection or not self._current_chapter_id:
            continue_action.setEnabled(False)
            expand_action.setEnabled(False)
            condense_action.setEnabled(False)
            annotation_action.setEnabled(False)
            hint = "请先选中段落" if not has_selection else "请先选择章节"
            menu.addAction(QAction(hint, self))
        else:
            menu.addAction(continue_action)
            menu.addAction(expand_action)
            menu.addAction(condense_action)
            menu.addSeparator()
            menu.addAction(annotation_action)
        menu.exec(self.editor.mapToGlobal(pos))

    def _transform_text(self, transform_type: str) -> None:
        """发起文本变换（续写/扩写/缩写）SSE请求."""
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择章节")
            return
        if not self._check_no_running_op():
            return
        project_id = self._get_project_id()
        if not project_id:
            return
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            QMessageBox.warning(self, "提示", "请先选中要变换的段落")
            return
        selected_text = cursor.selectedText()
        dialog = TextTransformDialog(
            project_id, self._current_chapter_id, selected_text, transform_type, self
        )
        dialog.replace_requested.connect(self._on_transform_replace)
        dialog.insert_requested.connect(self._on_transform_insert)
        dialog.exec()

    def _on_transform_replace(self, new_text: str) -> None:
        """用AI生成结果替换编辑器中选中的段落."""
        if not new_text:
            return
        reply = QMessageBox.question(
            self,
            "确认替换",
            "确定用AI生成结果替换选中段落？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            cursor.insertText(new_text)
            self._mark_unsaved()
            self.status_label.setText("已替换选中段落")

    def _on_transform_insert(self, new_text: str) -> None:
        """将AI生成结果插入到编辑器中选中段落之后."""
        if not new_text:
            return
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            end_pos = cursor.selectionEnd()
            cursor.setPosition(end_pos)
            cursor.insertText("\n" + new_text)
        else:
            self.editor.appendPlainText(new_text)
        self._mark_unsaved()
        self.status_label.setText("已插入AI生成结果到原文后")

    # ---------- T5-2: 批量查找替换 ----------
    def _open_batch_replace(self) -> None:
        """打开批量查找替换对话框，默认范围为当前章节."""
        pid = self._get_project_id()
        if not pid:
            return
        chapter_ids: list[str] = []
        if self._current_chapter_id:
            chapter_ids = [self._current_chapter_id]
        dialog = BatchReplaceDialog(pid, chapter_ids, self)
        dialog.replace_done.connect(self._on_batch_replace_done)
        dialog.exec()

    def _on_batch_replace_done(self, data: dict) -> None:
        """批量替换完成后刷新当前章节内容並顯示報告."""
        replaced = data.get("replaced_count", 0)
        affected = data.get("affected_chapters", 0)
        failed = data.get("failed_count", 0)
        report_lines = [
            "批量替换報告：",
            f"  已替换：{replaced} 处",
            f"  影響章节：{affected} 章",
            f"  失敗：{failed} 处",
        ]
        details = data.get("details", [])
        if details:
            report_lines.append("")
            report_lines.append("明細：")
            for d in details[:20]:
                report_lines.append(
                    f"  • {d.get('chapter_title', '')}: {d.get('count', 0)} 处"
                )
            if len(details) > 20:
                report_lines.append(f"  ...（共 {len(details)} 章）")
        QMessageBox.information(self, "替换報告", "\n".join(report_lines))
        # 若当前章节受影響，重新加載内容
        if self._current_chapter_id:
            affected_ids = data.get("affected_chapter_ids", [])
            if self._current_chapter_id in affected_ids:
                self._reload_current_content()

    def _reload_current_content(self) -> None:
        """重新加載当前章节内容."""
        if not self._current_chapter_id:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.get, f"/api/chapters/{self._current_chapter_id}/content"
        )
        worker.result.connect(self._on_content_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    # ---------- T5-5: 版本管理 + 锁定 ----------
    def _open_version_dialog(self) -> None:
        """打开章节版本管理对话框."""
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择章节")
            return
        title = ""
        idx = self.chapter_combo.currentIndex()
        if idx > 0:
            info = self.chapter_combo.itemData(idx)
            if info:
                title = info.get("title", "")
        dialog = ChapterVersionDialog(
            self._current_chapter_id, title, self
        )
        dialog.rollback_done.connect(self._on_version_rollback_done)
        dialog.exec()

    def _on_version_rollback_done(self, data: dict) -> None:
        """版本回滚完成后刷新编辑器内容."""
        content = data.get("content", "")
        if content:
            self.editor.setPlainText(content)
            self._saved_content = content
            self._has_unsaved_changes = False
            self.save_btn.setStyleSheet("")
        self.status_label.setText("已回滚到目标版本")
        self._load_annotations()

    def _on_lock_clicked(self, checked: bool) -> None:
        """锁定/解锁按鈕点擊."""
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择章节")
            self._lock_btn.setChecked(False)
            return
        if checked:
            # 锁定：直接执行
            self._toggle_lock(True)
        else:
            # 解锁：彈确认框
            reply = QMessageBox.question(
                self,
                "确认解锁",
                "确定解锁当前章节？解锁后可繼續编辑。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._lock_btn.setChecked(True)
                return
            self._toggle_lock(False)

    def _toggle_lock(self, lock: bool) -> None:
        """調用后端切换锁定状态."""
        client = get_api_client()
        worker = ApiWorker(
            client.patch,
            f"/api/chapters/{self._current_chapter_id}/lock",
            json={"is_locked": lock},
        )
        worker.result.connect(lambda d: self._on_lock_toggled(lock, d))
        worker.error.connect(self._on_lock_error)
        self._add_worker(worker)
        worker.start()

    def _on_lock_toggled(self, lock: bool, data: dict) -> None:
        self._is_locked = lock
        self._update_lock_ui()
        self.status_label.setText("已锁定" if lock else "已解锁")

    def _on_lock_error(self, msg: str) -> None:
        self._lock_btn.setChecked(self._is_locked)
        QMessageBox.critical(self, "错误", f"锁定操作失敗：{msg}")

    def _update_lock_ui(self) -> None:
        """根據锁定状态更新编辑器只讀与按鈕圖标/文字."""
        self.editor.setReadOnly(self._is_locked)
        if self._is_locked:
            self._lock_btn.setText("🔒 解锁")
            self._lock_btn.setChecked(True)
            self._lock_btn.setStyleSheet(
                "background-color: #f44336; color: white; padding: 6px 16px; border-radius: 4px;"
            )
            self.editor.setStyleSheet(
                "font-size: 14px; line-height: 1.6; background-color: #f5f5f5;"
            )
        else:
            self._lock_btn.setText("🔒 锁定")
            self._lock_btn.setChecked(False)
            self._lock_btn.setStyleSheet("")
            self.editor.setStyleSheet("font-size: 14px; line-height: 1.6;")

    # ---------- T5-7: 批注側欄 ----------
    def _toggle_annotation_dock(self) -> None:
        """切换批注側欄顯示."""
        if self._annotation_dock is None:
            self._build_annotation_dock()
        if self._annotation_dock is not None:
            self._annotation_dock.setVisible(
                not self._annotation_dock.isVisible()
            )
            if self._annotation_dock.isVisible() and self._current_chapter_id:
                self._load_annotations()

    def _build_annotation_dock(self) -> None:
        """構建批注側欄（停靠在右側）."""
        dock = QDockWidget("批注列表", self)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        container = QWidget()
        layout = QVBoxLayout(container)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("状态篩选："))
        self._annotation_filter = QComboBox()
        self._annotation_filter.addItem("全部", "all")
        self._annotation_filter.addItem("待处理", "pending")
        self._annotation_filter.addItem("已处理", "resolved")
        self._annotation_filter.currentIndexChanged.connect(
            self._refresh_annotation_table
        )
        filter_layout.addWidget(self._annotation_filter, 1)
        layout.addLayout(filter_layout)

        self._annotation_table = QTableWidget(0, 4)
        self._annotation_table.setHorizontalHeaderLabels(
            ["类型", "状态", "内容摘要", "annotation_id"]
        )
        self._annotation_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._annotation_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._annotation_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._annotation_table.setColumnWidth(3, 0)
        self._annotation_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._annotation_table.customContextMenuRequested.connect(
            self._on_annotation_context_menu
        )
        layout.addWidget(self._annotation_table, 1)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("添加批注")
        add_btn.clicked.connect(self._add_annotation_blank)
        edit_btn = QPushButton("编辑选中")
        edit_btn.clicked.connect(self._edit_selected_annotation)
        invalidate_btn = QPushButton("标记失效")
        invalidate_btn.setStyleSheet(
            "background-color: #ff9800; color: white; padding: 4px 12px; border-radius: 3px;"
        )
        invalidate_btn.clicked.connect(self._invalidate_selected_annotation)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(invalidate_btn)
        layout.addLayout(btn_layout)

        dock.setWidget(container)
        # 停靠到主窗口右側
        main_window = self.window()
        if hasattr(main_window, "addDockWidget"):
            main_window.addDockWidget(
                Qt.DockWidgetArea.RightDockWidgetArea, dock
            )
        else:
            dock.setFloating(True)
        self._annotation_dock = dock

    def _load_annotations(self) -> None:
        """加載当前章节的批注列表."""
        if not self._current_chapter_id:
            self._annotations = []
            self._refresh_annotation_table()
            return
        client = get_api_client()
        worker = ApiWorker(
            client.get,
            f"/api/chapters/annotations/{self._current_chapter_id}",
        )
        worker.result.connect(self._on_annotations_loaded)
        worker.error.connect(self._on_annotations_error)
        self._add_worker(worker)
        worker.start()

    def _on_annotations_error(self, msg: str) -> None:
        self._annotations = []
        self._refresh_annotation_table()
        self.status_label.setText(f"批注加载失败：{msg}")

    def _on_annotations_loaded(self, data: dict | list) -> None:
        anns = data if isinstance(data, list) else data.get("annotations", [])
        self._annotations = anns
        self._refresh_annotation_table()

    def _refresh_annotation_table(self) -> None:
        if self._annotation_table is None:
            return
        filter_status = (
            self._annotation_filter.currentData()
            if self._annotation_filter
            else "all"
        )
        type_map = {"note": "文字备注", "ai_suggestion": "AI建议"}
        status_map = {"pending": "待处理", "resolved": "已处理", "invalid": "已失效"}
        self._annotation_table.setRowCount(0)
        for ann in self._annotations:
            status = ann.get("status", "pending")
            if filter_status != "all" and status != filter_status:
                continue
            row = self._annotation_table.rowCount()
            self._annotation_table.insertRow(row)
            self._annotation_table.setItem(
                row, 0, QTableWidgetItem(type_map.get(ann.get("annotation_type", ""), "其他"))
            )
            self._annotation_table.setItem(
                row, 1, QTableWidgetItem(status_map.get(status, status))
            )
            content = ann.get("content", "")
            summary = content[:30] + "..." if len(content) > 30 else content
            self._annotation_table.setItem(row, 2, QTableWidgetItem(summary))
            aid_item = QTableWidgetItem(str(ann.get("annotation_id", "")))
            aid_item.setData(Qt.ItemDataRole.UserRole, ann.get("annotation_id"))
            self._annotation_table.setItem(row, 3, aid_item)

    def _add_annotation_from_selection(self) -> None:
        """从编辑器选中文本添加批注."""
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择章节")
            return
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            QMessageBox.warning(self, "提示", "请先选中要批注的段落")
            return
        anchor_text = cursor.selectedText()
        dialog = AnnotationEditDialog(
            self._current_chapter_id, anchor_text, parent=self
        )
        dialog.saved.connect(self._on_annotation_saved)
        dialog.exec()

    def _add_annotation_blank(self) -> None:
        """添加空白批注（無錨定段落）."""
        if not self._current_chapter_id:
            QMessageBox.warning(self, "提示", "请先选择章节")
            return
        dialog = AnnotationEditDialog(
            self._current_chapter_id, "", parent=self
        )
        dialog.saved.connect(self._on_annotation_saved)
        dialog.exec()

    def _edit_selected_annotation(self) -> None:
        """编辑选中的批注."""
        if self._annotation_table is None or not self._current_chapter_id:
            return
        row = self._annotation_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选中要编辑的批注")
            return
        aid_item = self._annotation_table.item(row, 3)
        if not aid_item:
            return
        annotation_id = aid_item.data(Qt.ItemDataRole.UserRole)
        existing = next(
            (a for a in self._annotations if a.get("annotation_id") == annotation_id),
            {},
        )
        dialog = AnnotationEditDialog(
            self._current_chapter_id,
            existing.get("anchor_text", ""),
            annotation_id=annotation_id,
            existing=existing,
            parent=self,
        )
        dialog.saved.connect(self._on_annotation_saved)
        dialog.exec()

    def _on_annotation_saved(self, data: dict) -> None:
        """批注保存完成后刷新列表."""
        self._load_annotations()
        self.status_label.setText("批注已保存")

    def _on_annotation_context_menu(self, pos) -> None:
        """批注表格右鍵菜單：编辑/标记失效."""
        if self._annotation_table is None:
            return
        menu = QMenu(self)
        edit_action = QAction("编辑", self)
        edit_action.triggered.connect(self._edit_selected_annotation)
        invalidate_action = QAction("标记失效", self)
        invalidate_action.triggered.connect(self._invalidate_selected_annotation)
        row = self._annotation_table.indexAt(pos).row()
        if row < 0:
            edit_action.setEnabled(False)
            invalidate_action.setEnabled(False)
        menu.addAction(edit_action)
        menu.addAction(invalidate_action)
        menu.exec(self._annotation_table.mapToGlobal(pos))

    def _invalidate_selected_annotation(self) -> None:
        """标记选中批注为失效."""
        if self._annotation_table is None:
            return
        row = self._annotation_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选中要标记失效的批注")
            return
        aid_item = self._annotation_table.item(row, 3)
        if not aid_item:
            return
        annotation_id = aid_item.data(Qt.ItemDataRole.UserRole)
        if not annotation_id:
            return
        reply = QMessageBox.question(
            self,
            "确认失效",
            "确定將該批注标记为失效？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.patch,
            f"/api/chapters/annotations/{annotation_id}/invalidate",
        )
        worker.result.connect(lambda _: self._on_annotation_invalidated())
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_annotation_invalidated(self) -> None:
        self._load_annotations()
        self.status_label.setText("批注已标记为失效")

    def _check_and_invalidate_orphan_annotations(self) -> None:
        """检测锚定段落是否被删除，自动调用 invalidate 端点.

        当编辑器内容变化时，检查所有有效批注的 anchor_text 是否仍存在于
        当前内容中，若不存在则自动标记为失效。本地立即标记为 invalid 避免重复请求。
        """
        if not self._current_chapter_id or not self._annotations:
            return
        current_content = self.editor.toPlainText()
        orphan_ids: list[str] = []
        for ann in self._annotations:
            if ann.get("status") in ("invalid", "resolved"):
                continue
            anchor = ann.get("anchor_text", "")
            if anchor and anchor not in current_content:
                orphan_ids.append(ann.get("annotation_id", ""))
                # 本地立即标记为 invalid，避免后續按鍵重複发送请求
                ann["status"] = "invalid"
        if not orphan_ids:
            return
        client = get_api_client()
        for aid in orphan_ids:
            if not aid:
                continue
            worker = ApiWorker(
                client.patch,
                f"/api/chapters/annotations/{aid}/invalidate",
            )
            worker.result.connect(lambda _: self._load_annotations())
            worker.error.connect(self._on_annotations_error)
            self._add_worker(worker)
            worker.start()
        self._refresh_annotation_table()

