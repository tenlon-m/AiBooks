"""主窗口 - QStackedWidget多页切换+菜单栏+状态栏+项目切换统一入口+定时自动保存."""
from __future__ import annotations

import sys
import time
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,

    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.config.settings import get_config
from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.pages.creation_params_page import CreationParamsPage
from src.ui.pages.character_page import CharacterPage
from src.ui.pages.outline_page import OutlinePage
from src.ui.pages.hook_page import HookPage
from src.ui.pages.style_library_page import StyleLibraryPage
from src.ui.pages.writing_progress_page import WritingProgressPage
from src.ui.pages.chapter_edit_page import ChapterEditPage
from src.ui.pages.validation_report_page import ValidationReportPage
from src.ui.pages.history_rollback_page import HistoryRollbackPage
from src.ui.pages.ai_source_config_page import AiSourceConfigPage
from src.ui.pages.backup_page import BackupPage
from src.ui.pages.export_page import ExportPage
from src.ui.pages.ai_call_log_page import AiCallLogPage
from src.ui.pages.project_manager_page import ProjectManagerPage
from src.ui.pages.shortcut_config_page import ShortcutConfigPage
from src.ui.pages.naming_generator_page import NamingGeneratorPage
from src.ui.pages.timeline_page import TimelinePage
from src.ui.pages.relationship_graph_page import RelationshipGraphPage
from src.ui.pages.emotion_curve_page import EmotionCurvePage
from src.ui.pages.item_page import ItemPage
from src.ui.pages.word_stats_page import WordStatsPage
from src.ui.pages.sensitive_word_page import SensitiveWordPage
from src.ui.pages.app_log_page import AppLogPage
from src.ui.project_context import get_project_context
from src.ui.shortcut_manager import ShortcutManager
from src.ui.usage_guide import UsageGuideDialog
from src.ui.widgets.auto_save_timer import AutoSaveTimer
from src.ui.widgets.settings_dialog import SettingsDialog
from src.ui.widgets.copyable_message import install_copyable_message_boxes
from src.ui.theme.theme_manager import ThemeManager
from src.ui.theme.theme_qss_builder import ThemeQssBuilder
from src.ui.theme.theme_palette import ThemePalette
from src.ui.theme.theme_settings_dialog import ThemeSettingsDialog
from src.utils.logger import get_logger

# 关闭窗口时等待后台请求收尾的预算（毫秒）
_CLOSE_WAIT_MS = 5000
# 用户选择"继续等待"时的追加预算
_CLOSE_WAIT_LONG_MS = 15000
# 保存工程的请求超时（秒）。
# 服务端 /api/creation/save 带 retry_on_locked 重试，单次等锁最长 busy_timeout(60s)，
# 3 次尝试合计可达 ~3 分钟。客户端超时必须大于该预算，否则服务端还会成功的请求
# 会被客户端提前判超时，误报成"自动保存失败"。
_SAVE_REQUEST_TIMEOUT_S = 240


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # 全局接管消息弹窗：失败详情可划选/一键复制，便于把长报错反馈出来排障
        install_copyable_message_boxes()
        self.logger = get_logger()
        self.ctx = get_project_context()
        self._workers: list[ApiWorker] = []
        self._projects_data: list = []
        # 页面导航历史：用于“← 返回”按钮回到上一个页面
        # ——例如正在大纲生成时切到 AI源配置查看/修改后，一键返回大纲页继续作业
        self._nav_history: list[str] = []
        self._widget_to_key: dict[int, str] = {}
        self._page_titles: dict[str, str] = {}
        self.setWindowTitle("AiBooks - AI全自动小说撰写软件")
        self.setMinimumSize(1200, 800)

        self._init_ui()
        self._init_menu()
        self._init_toolbar()
        self._init_statusbar()

        ThemeManager.instance()
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        self._apply_style()

        self.ctx.project_changed.connect(self._on_project_changed_global)
        self._load_project_list()

        self._auto_save_fail_count: int = 0
        # 周期性自动保存的并发保护：上一次尚未返回时跳过本次 tick
        self._auto_save_in_flight: bool = False
        self._init_auto_save_timer()
        self._init_key_node_signals()

    def _init_ui(self) -> None:
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.pages: dict[str, QWidget] = {}
        self._add_page("manager", "工程管理器", ProjectManagerPage())
        self._add_page("creation", "创作参数", CreationParamsPage())
        self._add_page("character", "人物管理", CharacterPage())
        self._add_page("outline", "大纲管理", OutlinePage())
        self._add_page("hook", "爽点钩子", HookPage())
        self._add_page("style", "风格库", StyleLibraryPage())
        self._add_page("writing", "撰写进度", WritingProgressPage())
        self._add_page("edit", "章节编辑", ChapterEditPage())
        self._add_page("validation", "校验报告", ValidationReportPage())
        self._add_page("history", "历史回滚", HistoryRollbackPage())
        self._add_page("ai_config", "AI源配置", AiSourceConfigPage())
        self._add_page("backup", "备份管理", BackupPage())
        self._add_page("export", "小说导出", ExportPage())
        self._add_page("ai_logs", "AI调用日志", AiCallLogPage())
        self._add_page("shortcut", "快捷键配置", ShortcutConfigPage())
        self._add_page("naming", "命名生成器", NamingGeneratorPage())
        self._add_page("timeline", "时间线管理", TimelinePage())
        self._add_page("relationship", "角色关系图谱", RelationshipGraphPage())
        self._add_page("emotion", "情感曲线分析", EmotionCurvePage())
        self._add_page("word_stats", "字数统计", WordStatsPage())
        self._add_page("sensitive", "敏感词检测", SensitiveWordPage())
        self._add_page("items", "物品管理", ItemPage())
        self._add_page("app_logs", "应用日志", AppLogPage())

        manager_page = self.pages["manager"]
        manager_page.request_open_project.connect(self._on_manager_open_project)

        manager_page.request_create_with_template.connect(self._on_manager_create_with_template)

        self.stack.setCurrentWidget(manager_page)

    def _add_page(self, key: str, title: str, widget: QWidget) -> None:
        self.pages[key] = widget
        self.stack.addWidget(widget)
        # 反查 widget -> key：用于导航历史正确入栈
        self._widget_to_key[id(widget)] = key
        self._page_titles[key] = title

    def _init_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件(&F)")
        file_menu.addAction(QAction("工程管理器", self, triggered=self._back_to_project_manager))
        file_menu.addAction(QAction("新建项目", self, triggered=lambda: self._switch_page("creation")))
        file_menu.addAction(QAction("保存工程", self, shortcut="Ctrl+S", triggered=self._save_project))
        file_menu.addAction(QAction("导出小说", self, triggered=lambda: self._switch_page("export")))
        file_menu.addSeparator()
        file_menu.addAction(QAction("退出", self, triggered=self.close))

        edit_menu = menubar.addMenu("编辑(&E)")
        edit_menu.addAction(QAction("章节编辑", self, triggered=lambda: self._switch_page("edit")))
        edit_menu.addAction(QAction("历史回滚", self, triggered=lambda: self._switch_page("history")))

        tool_menu = menubar.addMenu("工具(&T)")
        tool_menu.addAction(QAction("AI源配置", self, triggered=lambda: self._switch_page("ai_config")))
        tool_menu.addAction(QAction("全局主题", self, triggered=self._open_theme_dialog))
        tool_menu.addAction(QAction("AI调用日志", self, triggered=lambda: self._switch_page("ai_logs")))
        tool_menu.addAction(QAction("应用日志", self, triggered=lambda: self._switch_page("app_logs")))
        tool_menu.addAction(QAction("备份管理", self, triggered=lambda: self._switch_page("backup")))
        settings_menu = tool_menu.addMenu("设置")
        settings_menu.addAction(QAction("打开设置", self, triggered=self._open_settings_dialog))

        help_menu = menubar.addMenu("帮助(&H)")
        help_menu.addAction(QAction("使用指南", self, triggered=self._show_guide))
        help_menu.addAction(QAction("关于", self, triggered=self._show_about))

    def _init_toolbar(self) -> None:
        toolbar = QToolBar("导航")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.toolbar = toolbar

        # "← 返回"：一键回到上一个页面（带历史栈弹空时灰掉）
        self._back_action = QAction("← 返回", self)
        self._back_action.setShortcut("Alt+Left")
        self._back_action.setToolTip("返回上一个页面（Alt+Left）")
        self._back_action.triggered.connect(self._navigate_back)
        toolbar.addAction(self._back_action)
        toolbar.addSeparator()

        back_action = QAction("返回工程管理器", self, triggered=self._back_to_project_manager)
        toolbar.addAction(back_action)
        toolbar.addSeparator()

        self._toolbar_actions: dict[str, QAction] = {}

        # 第一行：撰写小说流程主按钮
        main_pages = [
            ("创作参数", "creation"), ("人物管理", "character"), ("大纲管理", "outline"),
            ("爽点钩子", "hook"), ("风格库", "style"), ("撰写", "writing"),
            ("章节编辑", "edit"), ("校验", "validation"), ("导出", "export"),
        ]
        for title, key in main_pages:
            action = QAction(title, self, triggered=lambda checked, k=key: self._switch_page(k))
            toolbar.addAction(action)
            self._toolbar_actions[key] = action

        # 第二行：辅助工具按钮
        self.addToolBarBreak()
        aux_toolbar = QToolBar("辅助工具")
        aux_toolbar.setMovable(False)
        self.addToolBar(aux_toolbar)
        self.aux_toolbar = aux_toolbar

        aux_pages = [
            ("命名生成器", "naming"), ("时间线", "timeline"), ("关系图谱", "relationship"),
            ("情感曲线", "emotion"), ("字数统计", "word_stats"), ("敏感词", "sensitive"),
            ("物品管理", "items"), ("历史回滚", "history"), ("AI源配置", "ai_config"),
            ("AI调用日志", "ai_logs"), ("应用日志", "app_logs"), ("备份管理", "backup"),
            ("快捷键", "shortcut"),
        ]
        for title, key in aux_pages:
            action = QAction(title, self, triggered=lambda checked, k=key: self._switch_page(k))
            aux_toolbar.addAction(action)
            self._toolbar_actions[key] = action

    def _init_statusbar(self) -> None:
        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage("就绪")
        from src.ui.widgets.status_bar_runtime_widget import StatusBarRuntimeWidget
        self._runtime_widget = StatusBarRuntimeWidget()
        status.addPermanentWidget(self._runtime_widget)

    def _current_page_is_busy(self) -> bool:
        """当前页面是否有异步操作正在运行."""
        widget = self.stack.currentWidget()
        if widget and hasattr(widget, "is_busy"):
            try:
                return widget.is_busy()
            except Exception:
                pass
        return False

    def _switch_page(self, key: str, record_history: bool = True) -> None:
        """切换页面，可选是否入栈历史（"返回"按钮走 record_history=False 避免循环）."""
        if key not in self.pages:
            return
        if self._current_page_is_busy():
            QMessageBox.warning(self, "提示", "当前页面有操作进行中，请等待完成后再切换页面")
            return
        if record_history:
            current_widget = self.stack.currentWidget()
            current_key = (
                self._widget_to_key.get(id(current_widget)) if current_widget else None
            )
            # 主页（工程管理器）不入栈，避免回到主页后“返回”无意义
            if (
                current_key is not None
                and current_key != key
                and current_key != "manager"
            ):
                self._nav_history.append(current_key)
                # 防止极端连跳场景导致栈无限增长
                if len(self._nav_history) > 30:
                    self._nav_history.pop(0)
        self.stack.setCurrentWidget(self.pages[key])
        self.statusBar().showMessage(f"切换到: {self._page_titles.get(key, key)}")
        self._update_toolbar_active_state(key)
        self._update_back_action_state()

    def _navigate_back(self) -> None:
        """返回上一个页面：从 _nav_history 弹出目标并切换（不入栈，防循环）."""
        if not self._nav_history:
            return
        if self._current_page_is_busy():
            QMessageBox.warning(self, "提示", "当前页面有操作进行中，请等待完成后再返回")
            return
        target_key = self._nav_history.pop()
        if target_key not in self.pages:
            # 历史项已被删除/重构则丢弃继续向上弹
            self._update_back_action_state()
            return
        self.stack.setCurrentWidget(self.pages[target_key])
        self.statusBar().showMessage(f"已返回: {self._page_titles.get(target_key, target_key)}")
        self._update_toolbar_active_state(target_key)
        self._update_back_action_state()

    def _update_back_action_state(self) -> None:
        """根据历史栈深度启用/置灰返回按钮."""
        if hasattr(self, "_back_action"):
            self._back_action.setEnabled(bool(self._nav_history))

    def _update_toolbar_active_state(self, active_key: str) -> None:
        mgr = ThemeManager.instance()
        resolved = mgr.resolve_colors(mgr.current_theme().theme_id)
        pal = ThemePalette.derive(resolved.foreground, resolved.background)
        for key, action in self._toolbar_actions.items():
            btn = self.toolbar.widgetForAction(action)
            if btn is None:
                btn = self.aux_toolbar.widgetForAction(action)
            if btn is None:
                continue
            if key == active_key:
                btn.setStyleSheet(
                    f"background-color: {pal.accent};"
                    f" color: {pal.button_text(pal.accent)};"
                    f" padding: 6px 12px; border-radius: 4px; font-weight: bold;"
                )
            else:
                btn.setStyleSheet("")

    def _load_project_list(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/creation")
        worker.result.connect(self._on_project_list_loaded)
        worker.error.connect(lambda msg: self.statusBar().showMessage(f"加载项目列表失败: {msg}"))
        self._workers.append(worker)
        worker.start()

    def _on_project_list_loaded(self, projects: list) -> None:
        self._projects_data = projects

    def _switch_project(self, target_id: str, info: dict) -> bool:
        if self.has_any_unsaved_changes():
            reply = QMessageBox.question(
                self, "提示",
                "当前项目有未保存的修改，是否放弃修改并切换项目？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False
        if self._is_writing_in_progress():
            QMessageBox.warning(self, "提示", "撰写进行中，请暂停或完成后再切换项目")
            return False
        self.clear_all_pages()
        self.ctx.set_project(target_id, info)
        return True

    def has_any_unsaved_changes(self) -> bool:
        for page in self.pages.values():
            if hasattr(page, "has_unsaved_changes"):
                try:
                    if page.has_unsaved_changes():
                        return True
                except Exception:
                    pass
        return False

    def _is_writing_in_progress(self) -> bool:
        writing_page = self.pages.get("writing")
        if writing_page and hasattr(writing_page, "is_writing"):
            try:
                if writing_page.is_writing():
                    return True
            except Exception:
                pass
        chapter_edit_page = self.pages.get("edit")
        if chapter_edit_page and hasattr(chapter_edit_page, "is_busy"):
            try:
                if chapter_edit_page.is_busy():
                    return True
            except Exception:
                pass
        return False

    def clear_all_pages(self) -> None:
        for page in self.pages.values():
            if hasattr(page, "clear_page"):
                try:
                    page.clear_page()
                except Exception as e:
                    self.logger.error(f"清除页面失败: {e}")

    def _on_project_changed_global(self, project_id: str, info: dict) -> None:

        self.statusBar().showMessage(f"已切换到项目: {info.get('book_title', project_id[:8])}")

    def _back_to_project_manager(self) -> None:
        if self.has_any_unsaved_changes():
            reply = QMessageBox.question(self, "提示", "有未保存的修改，确定返回工程管理器？")
            if reply != QMessageBox.StandardButton.Yes:
                return
        if self._is_writing_in_progress():
            QMessageBox.warning(self, "提示", "撰写进行中，请暂停或完成后再返回")
            return
        # 回主页时把历史清空——“返回工程管理器”是显式回家操作，
        # 此后“← 返回”应指向回到哪里由用户下一步动作决定
        self._nav_history.clear()
        self._switch_page("manager", record_history=False)
        manager_page = self.pages.get("manager")
        if manager_page and hasattr(manager_page, "refresh"):
            manager_page.refresh()

    def _on_manager_open_project(self, project_id: str) -> None:
        for p in self._projects_data:
            if p.get("project_id") == project_id:
                if self._switch_project(project_id, p):
                    self._switch_page("creation")
                return
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/creation/{project_id}")
        worker.result.connect(lambda info: self._on_open_project_loaded(project_id, info))
        worker.error.connect(lambda msg: QMessageBox.critical(self, "错误", f"打开项目失败: {msg}"))
        self._workers.append(worker)
        worker.start()

    def _on_open_project_loaded(self, project_id: str, info: dict) -> None:
        if self._switch_project(project_id, info):
            self._switch_page("creation")


    def _on_manager_create_with_template(self, params: dict) -> None:
        """带模板参数创建项目：设置创作参数页字段后切换过去."""
        self.ctx.clear()
        self.clear_all_pages()
        creation_page = self.pages.get("creation")
        if creation_page:
            if params.get("book_title"):
                creation_page.title_input.setText(params["book_title"])
            if params.get("volume_count"):
                creation_page.volume_spin.setValue(int(params["volume_count"]))
            if params.get("chapters_per_volume"):
                creation_page.chapter_spin.setValue(int(params["chapters_per_volume"]))
            if params.get("words_per_chapter"):
                creation_page.words_spin.setValue(int(params["words_per_chapter"]))
            if params.get("synopsis"):
                creation_page.synopsis_edit.setPlainText(params["synopsis"])
            if params.get("worldview"):
                creation_page.worldview_edit.setPlainText(params["worldview"])
        self._switch_page("creation")
        self.statusBar().showMessage("已应用项目参数，请确认后保存创建项目")

    def _save_project(self, trigger_type: str = "manual") -> None:
        creation_page = self.pages.get("creation")
        if not creation_page:
            return
        # 周期自动保存只保留一个在途请求：数据库/网络繁忙时不要堆请求，
        # 跳过本次不影响数据安全——下一次 tick 会保存最新内容。
        # 关键节点保存同理：分批生成大纲/爽点钩子时每批都会触发，
        # 若不在途则发起，在途则跳过，避免并发保存请求叠加。
        if trigger_type != "manual" and self._auto_save_in_flight:
            self.logger.debug("已有保存请求在途，跳过本次保存")
            return
        payload = self._collect_save_payload(creation_page)
        if payload is None:
            return
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            "/api/creation/save",
            json=payload,
            timeout=_SAVE_REQUEST_TIMEOUT_S,
        )
        if trigger_type == "manual":
            worker.result.connect(self._on_project_saved)
            worker.error.connect(self._on_save_error)
        else:
            # 自动保存与关键节点保存共用在途标记：分批生成大纲/爽点钩子时
            # 每批都可能触发 key_node 保存，若在途则已在上面提前返回。
            self._auto_save_in_flight = True
            if trigger_type == "key_node":
                worker.result.connect(self._on_key_node_saved)
                worker.error.connect(self._on_key_node_save_failed)
            else:
                worker.result.connect(self._on_auto_save_success)
                worker.error.connect(self._on_auto_save_failure)
        self._workers.append(worker)
        worker.start()
        if trigger_type == "manual":
            self.statusBar().showMessage("保存中...")
        else:
            self.statusBar().showMessage("自动保存中...")

    def _collect_save_payload(self, creation_page) -> dict | None:
        book_title = creation_page.title_input.text().strip()
        if not book_title:
            QMessageBox.warning(self, "提示", "请先设定创作参数或创建新项目")
            return None
        try:
            volume_count = int(creation_page.volume_spin.value())
            chapters_per_volume = int(creation_page.chapter_spin.value())
            words_per_chapter = int(creation_page.words_spin.value())
        except AttributeError:
            QMessageBox.warning(self, "提示", "无法获取创作参数")
            return None
        payload: dict = {
            "book_title": book_title,
            "volume_count": volume_count,
            "chapters_per_volume": chapters_per_volume,
            "words_per_chapter": words_per_chapter,
        }
        if self.ctx.has_project():
            payload["project_id"] = self.ctx.project_id
        synopsis = creation_page.synopsis_edit.toPlainText().strip()
        if synopsis:
            payload["synopsis"] = synopsis
        worldview = creation_page.worldview_edit.toPlainText().strip()
        if worldview:
            payload["worldview"] = worldview
        return payload

    def _on_project_saved(self, data: dict) -> None:
        project_id = data.get("project_id", "")
        info = {
            "book_title": data.get("book_title", ""),
            "has_synopsis": data.get("has_synopsis", False),
            "has_worldview": data.get("has_worldview", False),
        }
        self.ctx.set_project(project_id, info)
        self.statusBar().showMessage("工程已保存", 3000)
        if hasattr(self, "_runtime_widget"):
            self._runtime_widget.refresh_ai_source()

    def _on_save_error(self, msg: str) -> None:
        self.statusBar().showMessage(f"保存失败：{msg}")
        QMessageBox.critical(self, "保存失败", msg)

    def _show_guide(self) -> None:
        dialog = UsageGuideDialog(self)
        dialog.exec()

    def _show_about(self) -> None:
        QMessageBox.about(self, "关于 AiBooks", "AiBooks v0.1.0\nAI全自动小说撰写软件\n基于免费在线AI大模型")

    def _apply_style(self) -> None:
        mgr = ThemeManager.instance()
        resolved = mgr.resolve_colors(mgr.current_theme().theme_id)
        qss = ThemeQssBuilder.build_global_qss(resolved.foreground, resolved.background)
        self.setStyleSheet(qss)

        pal = QApplication.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(resolved.background))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(resolved.foreground))
        pal.setColor(QPalette.ColorRole.Base, QColor(resolved.background))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(resolved.background))
        pal.setColor(QPalette.ColorRole.Text, QColor(resolved.foreground))
        QApplication.setPalette(pal)

        self._set_title_bar_color(resolved.background, resolved.foreground)

        for page in self.pages.values():
            self._style_table_widgets(page)

    def _set_title_bar_color(self, background: str, foreground: str) -> None:
        """Windows 10+: 通过 DWM API 设置标题栏颜色."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            from src.ui.theme.contrast_checker import ContrastChecker

            hwnd = int(self.winId())
            is_dark = ContrastChecker.relative_luminance(background) <= 0.179

            dark_mode = wintypes.DWORD(1 if is_dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode)
            )

            bg_c = QColor(background)
            fg_c = QColor(foreground)
            bg_rgb = wintypes.DWORD(bg_c.red() | (bg_c.green() << 8) | (bg_c.blue() << 16))
            fg_rgb = wintypes.DWORD(fg_c.red() | (fg_c.green() << 8) | (fg_c.blue() << 16))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 35, ctypes.byref(bg_rgb), ctypes.sizeof(bg_rgb)
            )
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 36, ctypes.byref(fg_rgb), ctypes.sizeof(fg_rgb)
            )
        except Exception:
            pass

    def _on_theme_changed(self, theme_data: dict) -> None:
        """主题变更槽：重新应用 QSS 并联动阅读区与图表画布."""
        self._apply_style()
        from PySide6.QtWidgets import QTextEdit
        fg = theme_data.get("foreground", "#222222")
        bg = theme_data.get("background", "#FFFFFF")
        for page in self.pages.values():
            from src.ui.widgets.reading_mode_view import ReadingModeView
            for view in page.findChildren(ReadingModeView):
                view.set_background(bg)
            from src.ui.widgets.chart_canvas import ChartCanvas
            for canvas in page.findChildren(ChartCanvas):
                canvas.apply_theme(fg, bg)

    def _open_theme_dialog(self) -> None:
        """打开全局主题设置弹窗."""
        ThemeSettingsDialog.show_instance(self)

    def _open_settings_dialog(self) -> None:
        """打开统一设置窗口."""
        SettingsDialog.show_instance(self)

    @staticmethod
    def _style_table_widgets(page: QWidget) -> None:
        from PySide6.QtWidgets import QTableWidget
        tables = page.findChildren(QTableWidget)
        for table in tables:
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

            table.setAlternatingRowColors(True)
            table.setShowGrid(True)

    def _init_auto_save_timer(self) -> None:
        config = get_config()
        self._auto_save_timer = AutoSaveTimer(
            config.auto_save_enabled, config.auto_save_interval_minutes
        )
        self._auto_save_timer.timeout.connect(self._on_auto_save_tick)
        self._auto_save_timer.start()

    def _init_key_node_signals(self) -> None:
        creation_page = self.pages.get("creation")
        if creation_page and hasattr(creation_page, "save_completed"):
            creation_page.save_completed.connect(lambda: self._on_key_node_completed("创作参数"))
        character_page = self.pages.get("character")
        if character_page and hasattr(character_page, "merge_completed"):
            character_page.merge_completed.connect(lambda: self._on_key_node_completed("人物"))
        if character_page and hasattr(character_page, "request_open_naming"):
            character_page.request_open_naming.connect(lambda: self._switch_page("naming"))
        outline_page = self.pages.get("outline")
        if outline_page and hasattr(outline_page, "outline_saved"):
            outline_page.outline_saved.connect(lambda: self._on_key_node_completed("大纲"))
        hook_page = self.pages.get("hook")
        if hook_page and hasattr(hook_page, "hook_saved"):
            hook_page.hook_saved.connect(lambda: self._on_key_node_completed("爽点钩子"))
        naming_page = self.pages.get("naming")
        if naming_page and hasattr(naming_page, "naming_saved"):
            naming_page.naming_saved.connect(lambda: self._on_key_node_completed("命名收藏"))
        if naming_page and hasattr(naming_page, "characters_imported"):
            character_page = self.pages.get("character")
            if character_page and hasattr(character_page, "_load_characters"):
                naming_page.characters_imported.connect(character_page._load_characters)
        if outline_page and hasattr(outline_page, "scene_refined"):
            outline_page.scene_refined.connect(lambda: self._on_key_node_completed("场景细化"))
        writing_page = self.pages.get("writing")
        if writing_page and hasattr(writing_page, "chapter_completed"):
            writing_page.chapter_completed.connect(lambda: self._on_key_node_completed("每章撰写"))
        validation_page = self.pages.get("validation")
        if validation_page and hasattr(validation_page, "validation_completed"):
            validation_page.validation_completed.connect(lambda: self._on_key_node_completed("校验"))
        timeline_page = self.pages.get("timeline")
        if timeline_page and hasattr(timeline_page, "timeline_saved"):
            timeline_page.timeline_saved.connect(lambda: self._on_key_node_completed("时间线"))
        relationship_page = self.pages.get("relationship")
        if relationship_page and hasattr(relationship_page, "relationship_updated"):
            relationship_page.relationship_updated.connect(lambda: self._on_key_node_completed("关系图谱"))
        emotion_page = self.pages.get("emotion")
        if emotion_page and hasattr(emotion_page, "emotion_generated"):
            emotion_page.emotion_generated.connect(lambda: self._on_key_node_completed("情感曲线"))
        sensitive_page = self.pages.get("sensitive")
        if sensitive_page and hasattr(sensitive_page, "scan_completed"):
            sensitive_page.scan_completed.connect(lambda: self._on_key_node_completed("敏感词扫描"))
        chapter_edit_page = self.pages.get("edit")
        if chapter_edit_page and hasattr(chapter_edit_page, "polish_confirmed"):
            chapter_edit_page.polish_confirmed.connect(lambda: self._on_key_node_completed("润色确认"))
        if chapter_edit_page and hasattr(chapter_edit_page, "new_chapter_requested"):
            chapter_edit_page.new_chapter_requested.connect(self._on_new_chapter_requested)

        shortcut_page = self.pages.get("shortcut")
        if shortcut_page and hasattr(shortcut_page, "shortcut_changed"):
            shortcut_page.shortcut_changed.connect(self._on_shortcut_changed)

        self._init_global_shortcuts()

    def _on_auto_save_tick(self) -> None:
        if not self.ctx.has_project():
            return
        self._save_project(trigger_type="auto")

    def _on_auto_save_success(self, data: dict) -> None:
        self._auto_save_in_flight = False
        self._auto_save_fail_count = 0
        is_new = data.get("is_new", False)
        project_id = data.get("project_id", "")
        book_title = data.get("book_title", "")
        if is_new:
            self.ctx.set_project(project_id, {"book_title": book_title})
        self.statusBar().showMessage(f"已自动保存 {datetime.now().strftime('%H:%M:%S')}", 3000)

    def _on_key_node_saved(self, data: dict) -> None:
        self._auto_save_in_flight = False
        is_new = data.get("is_new", False)
        project_id = data.get("project_id", "")
        book_title = data.get("book_title", "")
        if is_new:
            self.ctx.set_project(project_id, {"book_title": book_title})

    def _on_key_node_save_failed(self, msg: str) -> None:
        # 关键节点保存失败不弹"自动保存告警"：分批生成时每批都可能触发一次，
        # 该告警面向定时自动保存的连续性，关键节点保存失败仅记录日志，避免误报。
        self._auto_save_in_flight = False
        self.logger.warning(f"关键节点保存失败: {msg}")

    def _on_auto_save_failure(self, msg: str) -> None:
        self._auto_save_in_flight = False
        # 区分可恢复错误（SQLite 锁冲突、超时）与不可恢复错误（422 请求格式
        # 错误、连接被拒绝）。不可恢复错误不会因重试而成功，计入失败计数
        # 只会导致误弹"自动保存多次失败"告警，打扰用户。
        # 422 和连接错误仅记日志 + 状态栏提示，不计入失败计数。
        is_unrecoverable = (
            "API 422" in msg
            or "无法连接后端服务" in msg
            or "WinError 10061" in msg
        )
        if is_unrecoverable:
            self.logger.warning(f"自动保存失败（不可恢复，不计入告警计数）: {msg}")
            self.statusBar().showMessage(f"自动保存失败：{msg}")
            return
        self._auto_save_fail_count += 1
        self.statusBar().showMessage(f"自动保存失败：{msg}")
        if self._auto_save_fail_count >= 3:
            QMessageBox.warning(
                self, "自动保存告警",
                f"自动保存多次失败，请检查存储空间与数据库状态。\n最近错误：{msg}",
            )
            self._auto_save_fail_count = 0

    def _on_key_node_completed(self, node_type: str) -> None:
        if not self.ctx.has_project():
            return
        self.logger.info(f"关键节点自动保存触发: {node_type}")
        self._save_project(trigger_type="key_node")

    def _init_global_shortcuts(self) -> None:
        """注册全局快捷键（Ctrl+Shift+D 触发 AI 对话等）.

        从 shortcut_configs 表加载用户自定义配置。
        """
        self._global_shortcut_manager = ShortcutManager(self)
        self._global_shortcut_manager.register("ai_chat", self._open_ai_chat)
        self._global_shortcut_manager.load()

    def _open_ai_chat(self) -> None:
        """Ctrl+Shift+D 触发 AI 对话：切换到章节编辑页并触发 AI 润色."""
        edit_page = self.pages.get("edit")
        if edit_page and hasattr(edit_page, "_polish"):
            self._switch_page("edit")
            if hasattr(edit_page, "_current_chapter_id") and edit_page._current_chapter_id:
                edit_page._polish()
            else:
                QMessageBox.information(
                    self, "AI 对话", "请先在章节编辑页选择章节，再使用 AI 对话功能"
                )

    def _on_new_chapter_requested(self) -> None:
        """Ctrl+N 触发新建章节：切换到撰写进度页."""
        if not self.ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return
        self._switch_page("writing")
        self.statusBar().showMessage("已切换到撰写进度页，可开始撰写新章节")

    def _on_shortcut_changed(self) -> None:
        """快捷键配置变更后刷新所有页面的快捷键绑定."""
        edit_page = self.pages.get("edit")
        if edit_page and hasattr(edit_page, "reload_shortcuts"):
            edit_page.reload_shortcuts()
        writing_page = self.pages.get("writing")
        if writing_page and hasattr(writing_page, "reload_shortcuts"):
            writing_page.reload_shortcuts()
        if hasattr(self, "_global_shortcut_manager"):
            self._global_shortcut_manager.reload()
        self.statusBar().showMessage("快捷键配置已刷新", 3000)

    def closeEvent(self, event) -> None:
        from src.ui.widgets.shutdown_dialog import ShutdownDialog

        dialog = ShutdownDialog(self)
        dialog.show()
        dialog.log("开始关闭程序，请稍候…")

        # Step 1: 停止自动保存定时器
        dialog.log("▸ 停止自动保存定时器…")
        if hasattr(self, "_auto_save_timer"):
            self._auto_save_timer.stop()
        dialog.log("✓ 自动保存定时器已停止")

        # Step 2: 清理状态栏运行时组件
        dialog.log("▸ 清理状态栏运行时组件…")
        if hasattr(self, "_runtime_widget"):
            self._runtime_widget.cleanup()
        dialog.log("✓ 状态栏运行时组件已清理")

        # Step 3: 通知所有后台任务停止（非阻塞）
        from src.ui.api_worker import _running_workers
        from src.ui.sse_worker import _running_sse_workers

        all_workers = list(_running_workers) + list(_running_sse_workers)
        worker_count = len(all_workers)
        if worker_count > 0:
            dialog.log(f"▸ 通知 {worker_count} 个后台任务停止…")
            for worker in all_workers:
                try:
                    if hasattr(worker, "stop"):
                        worker.stop()
                except Exception:
                    pass
            dialog.log(f"✓ 已发送停止信号给 {worker_count} 个后台任务")
        else:
            dialog.log("✓ 无后台任务运行")

        # Step 4: 等待后台任务逐个结束（带倒计时）
        if worker_count > 0:
            deadline = time.monotonic() + _CLOSE_WAIT_LONG_MS / 1000.0
            while True:
                remaining = len(_running_workers) + len(_running_sse_workers)
                if remaining == 0:
                    dialog.log("✓ 所有后台任务已结束")
                    break
                left = int(deadline - time.monotonic())
                if left <= 0:
                    dialog.log(f"⚠ {remaining} 个后台任务超时未结束，将强制退出")
                    self.logger.warning(
                        f"关闭时仍有 {remaining} 个后台任务未结束"
                    )
                    break
                dialog.log(f"  等待 {remaining} 个后台任务结束（剩余 {left}s）…")
                for w in list(_running_workers) + list(_running_sse_workers):
                    try:
                        if hasattr(w, "isRunning") and w.isRunning():
                            w.wait(100)
                    except RuntimeError:
                        pass
                QApplication.processEvents()

        # Step 5: 关闭 API 客户端
        dialog.log("▸ 关闭 API 客户端…")
        try:
            get_api_client().close()
            dialog.log("✓ API 客户端已关闭")
        except Exception as e:
            dialog.log(f"⚠ API 客户端关闭出错: {e}")

        # Step 6: 停止后端服务
        dialog.log("▸ 停止后端 FastAPI 服务…")
        try:
            from src.api.server import stop_server

            stop_server()
            dialog.log("✓ 后端服务已停止")
        except Exception as e:
            dialog.log(f"⚠ 后端服务停止出错: {e}")

        # Step 7: 停止异步任务桥
        dialog.log("▸ 停止异步任务桥…")
        try:
            from src.utils.async_bridge import stop_bridge

            stop_bridge()
            dialog.log("✓ 异步任务桥已停止")
        except Exception as e:
            dialog.log(f"⚠ 异步任务桥停止出错: {e}")

        # 完成
        dialog.log("")
        dialog.log("所有组件已关闭，程序即将退出")
        dialog.finish()
        dialog.close()
        self.logger.info("******程序退出******")
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
