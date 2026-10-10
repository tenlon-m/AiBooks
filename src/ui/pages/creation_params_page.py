"""创作参数设定页 - 创建项目/设定梗概与世界观/导入文件/项目切换联动."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context
from src.ui.theme.theme_qss_builder import apply_theme_variant


class CreationParamsPage(QWidget):
    save_completed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._saved_synopsis: str = ""
        self._saved_worldview: str = ""
        self._polish_syn_busy: bool = False
        self._polish_wv_busy: bool = False
        self._init_ui()


        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("创作参数设定")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        proj_layout = QHBoxLayout()
        proj_layout.addWidget(QLabel("当前项目："))
        self.project_name_label = QLabel("未选择")
        self.project_name_label.setProperty("role", "highlight")
        self.project_name_label.setStyleSheet("font-weight: bold; font-size: 14px; padding: 4px 8px; border-radius: 4px;")
        proj_layout.addWidget(self.project_name_label, 1)
        layout.addLayout(proj_layout)

        form = QFormLayout()
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("请输入书名（1-50字符）")
        form.addRow("书名：", self.title_input)

        self.volume_spin = QSpinBox()
        self.volume_spin.setRange(1, 20)
        self.volume_spin.setValue(1)
        form.addRow("卷数：", self.volume_spin)

        self.chapter_spin = QSpinBox()
        self.chapter_spin.setRange(1, 100)
        self.chapter_spin.setValue(10)
        form.addRow("每卷章节数：", self.chapter_spin)

        self.words_spin = QSpinBox()
        self.words_spin.setRange(500, 10000)
        self.words_spin.setSingleStep(500)
        self.words_spin.setValue(3000)
        form.addRow("每章字数：", self.words_spin)
        layout.addLayout(form)

        layout.addWidget(QLabel("故事梗概（≥50字）："))
        self.synopsis_edit = QTextEdit()
        self.synopsis_edit.setPlaceholderText("输入或导入故事梗概...")
        layout.addWidget(self.synopsis_edit)

        btn_syn_layout = QHBoxLayout()
        self.import_syn_btn = QPushButton("导入梗概文件")
        self.import_syn_btn.clicked.connect(lambda: self._import_file("synopsis"))
        self.save_syn_btn = QPushButton("保存梗概")
        apply_theme_variant(self.save_syn_btn, "info")
        self.save_syn_btn.clicked.connect(self._save_synopsis)
        self.polish_syn_btn = QPushButton("AI润色")
        apply_theme_variant(self.polish_syn_btn, "purple")
        self.polish_syn_btn.clicked.connect(self._polish_synopsis)
        btn_syn_layout.addWidget(self.import_syn_btn)
        btn_syn_layout.addWidget(self.polish_syn_btn)
        btn_syn_layout.addStretch()
        btn_syn_layout.addWidget(self.save_syn_btn)
        layout.addLayout(btn_syn_layout)

        layout.addWidget(QLabel("世界观设定（≥50字）："))
        self.worldview_edit = QTextEdit()
        self.worldview_edit.setPlaceholderText("输入或导入世界观设定...")
        layout.addWidget(self.worldview_edit)

        btn_wv_layout = QHBoxLayout()
        self.import_wv_btn = QPushButton("导入世界观文件")
        self.import_wv_btn.clicked.connect(lambda: self._import_file("worldview"))
        self.import_naming_btn = QPushButton("从命名收藏导入")
        apply_theme_variant(self.import_naming_btn, "warning")
        self.import_naming_btn.clicked.connect(self._import_naming_to_worldview)
        self.save_wv_btn = QPushButton("保存世界观")
        apply_theme_variant(self.save_wv_btn, "info")
        self.save_wv_btn.clicked.connect(self._save_worldview)
        self.polish_wv_btn = QPushButton("AI润色")
        apply_theme_variant(self.polish_wv_btn, "purple")
        self.polish_wv_btn.clicked.connect(self._polish_worldview)
        btn_wv_layout.addWidget(self.import_wv_btn)
        btn_wv_layout.addWidget(self.import_naming_btn)
        btn_wv_layout.addWidget(self.polish_wv_btn)
        btn_wv_layout.addStretch()
        btn_wv_layout.addWidget(self.save_wv_btn)
        layout.addLayout(btn_wv_layout)

        layout.addWidget(QLabel("人物设定（可选，导入后在人物管理页AI识别）："))
        self.character_edit = QTextEdit()
        self.character_edit.setPlaceholderText("输入或导入人物设定...")
        layout.addWidget(self.character_edit)

        btn_char_layout = QHBoxLayout()
        self.import_char_btn = QPushButton("导入人物设定文件")
        self.import_char_btn.clicked.connect(lambda: self._import_file("character"))
        btn_char_layout.addWidget(self.import_char_btn)
        btn_char_layout.addStretch()
        layout.addLayout(btn_char_layout)

        btn_layout = QHBoxLayout()
        self.create_btn = QPushButton("创建新项目")
        apply_theme_variant(self.create_btn, "success")
        self.create_btn.clicked.connect(self._create_project)
        self.save_project_btn = QPushButton("保存工程")
        apply_theme_variant(self.save_project_btn, "info")
        self.save_project_btn.clicked.connect(self._on_save_project_clicked)
        self.delete_btn = QPushButton("删除当前项目")
        apply_theme_variant(self.delete_btn, "danger")
        self.delete_btn.clicked.connect(self._delete_project)
        btn_layout.addWidget(self.create_btn)
        btn_layout.addWidget(self.save_project_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.delete_btn)
        layout.addLayout(btn_layout)

        self.status_label = QLabel("")
        self.status_label.setProperty("role", "secondary")
        self.status_label.setStyleSheet("padding: 4px;")
        layout.addWidget(self.status_label)

    def _load_projects(self) -> None:
        """刷新项目列表（创建/删除项目后调用）.

        主窗口持有项目列表缓存（供工程管理器与「打开项目」使用），
        优先复用主窗口的刷新逻辑；取不到主窗口时降级为直接请求后端。
        """
        main_window = self.window()
        if main_window is not None and hasattr(main_window, "_load_project_list"):
            try:
                main_window._load_project_list()
            except Exception as e:  # 刷新失败不影响刚刚完成的创建/删除结果
                self.status_label.setText(f"刷新项目列表失败：{e}")
            self._refresh_manager_page()
            return
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/creation")
        worker.result.connect(self._on_projects_reloaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_projects_reloaded(self, projects: list) -> None:
        main_window = self.window()
        if main_window is not None and hasattr(main_window, "_projects_data"):
            main_window._projects_data = projects or []
        self._refresh_manager_page()

    def _refresh_manager_page(self) -> None:
        """让工程管理器页同步最新项目列表."""
        main_window = self.window()
        pages = getattr(main_window, "pages", None)
        if not pages:
            return
        manager_page = pages.get("manager")
        if manager_page is not None and hasattr(manager_page, "refresh"):
            try:
                manager_page.refresh()
            except Exception as e:
                self.status_label.setText(f"刷新工程管理器失败：{e}")

    def clear_page(self) -> None:
        self.project_name_label.setText("未选择")
        self.title_input.clear()
        self.volume_spin.setValue(1)
        self.chapter_spin.setValue(10)
        self.words_spin.setValue(3000)
        self.synopsis_edit.clear()
        self.worldview_edit.clear()
        self.character_edit.clear()
        self._saved_synopsis = ""
        self._saved_worldview = ""
        self.status_label.clear()

    def has_unsaved_changes(self) -> bool:
        if not get_project_context().has_project():
            return False
        return (
            self.synopsis_edit.toPlainText() != self._saved_synopsis
            or self.worldview_edit.toPlainText() != self._saved_worldview
        )

    def _on_save_project_clicked(self) -> None:
        window = self.window()
        if hasattr(window, "_save_project"):
            window._save_project()
        self.save_completed.emit()

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        if not project_id:
            self.project_name_label.setText("未选择")
            return
        self.project_name_label.setText(info.get("book_title", project_id[:8]))
        self.title_input.setText(info.get("book_title", ""))
        self.volume_spin.setValue(info.get("volume_count", 1))
        self.chapter_spin.setValue(info.get("chapters_per_volume", 10))
        self.words_spin.setValue(info.get("words_per_chapter", 3000))
        self._load_synopsis_and_worldview(project_id)


    def _load_synopsis_and_worldview(self, project_id: str) -> None:
        client = get_api_client()
        worker = ApiWorker(self._fetch_synopsis_and_worldview, client, project_id)
        worker.result.connect(self._on_synopsis_worldview_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    @staticmethod
    def _fetch_synopsis_and_worldview(client, project_id: str) -> dict:
        result = {}
        try:
            result["synopsis"] = client.get(f"/api/creation/{project_id}/synopsis")
        except Exception as e:
            result["synopsis_error"] = str(e)
        try:
            result["worldview"] = client.get(f"/api/creation/{project_id}/worldview")
        except Exception as e:
            result["worldview_error"] = str(e)
        return result

    def _on_synopsis_worldview_loaded(self, data: dict) -> None:
        if "synopsis_error" in data:
            self.status_label.setText(f"加载梗概失败：{data['synopsis_error']}")
        elif "synopsis" in data:
            content = data["synopsis"].get("content", "")
            self.synopsis_edit.setPlainText(content)
            self._saved_synopsis = content
        if "worldview_error" in data:
            self.status_label.setText(f"加载世界观失败：{data['worldview_error']}")
        elif "worldview" in data:
            content = data["worldview"].get("content", "")
            self.worldview_edit.setPlainText(content)
            self._saved_worldview = content

    def _create_project(self) -> None:
        title = self.title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "提示", "请输入书名")
            return
        main_window = self.window()
        if hasattr(main_window, "has_any_unsaved_changes") and main_window.has_any_unsaved_changes():
            reply = QMessageBox.question(self, "提示", "当前有未保存的修改，是否放弃并创建新项目？")
            if reply != QMessageBox.StandardButton.Yes:
                return
        if hasattr(main_window, "_is_writing_in_progress") and main_window._is_writing_in_progress():
            QMessageBox.warning(self, "提示", "撰写进行中，请暂停或完成后再创建新项目")
            return
        payload = {
            "book_title": title,
            "volume_count": self.volume_spin.value(),
            "chapters_per_volume": self.chapter_spin.value(),
            "words_per_chapter": self.words_spin.value(),
        }
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/creation/params", json=payload)
        worker.result.connect(self._on_project_created)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_project_created(self, data: dict) -> None:
        main_window = self.window()
        if hasattr(main_window, "clear_all_pages"):
            main_window.clear_all_pages()
        ctx = get_project_context()
        ctx.set_project(data["project_id"], data)
        QMessageBox.information(self, "成功", f"项目已创建：{data['book_title']}\n项目ID：{data['project_id']}")
        self._load_projects()

    def _delete_project(self) -> None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先选择一个项目")
            return
        reply = QMessageBox.question(self, "确认", "确定删除当前项目？此操作不可恢复。")
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.delete, f"/api/creation/{ctx.project_id}")
        worker.result.connect(self._on_project_deleted)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_project_deleted(self, _: object) -> None:
        ctx = get_project_context()
        ctx.clear()
        main_window = self.window()
        if hasattr(main_window, "clear_all_pages"):
            main_window.clear_all_pages()
        self._load_projects()
        QMessageBox.information(self, "成功", "项目已删除")

    def _import_file(self, category: str) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择文件", "", "文本文件 (*.txt *.md);;Word文档 (*.docx);;Excel文件 (*.xlsx);;所有文件 (*)"
        )
        if not file_path:
            return
        client = get_api_client()
        payload = {"file_path": file_path, "category": category}
        worker = ApiWorker(client.post, "/api/import/parse", json=payload)
        if category == "synopsis":
            worker.result.connect(lambda d: self.synopsis_edit.setPlainText(d.get("content", "")))
        elif category == "worldview":
            worker.result.connect(lambda d: self.worldview_edit.setPlainText(d.get("content", "")))
        else:
            worker.result.connect(lambda d: self.character_edit.setPlainText(d.get("content", "")))
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _save_synopsis(self) -> None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先选择或创建项目")
            return
        content = self.synopsis_edit.toPlainText().strip()
        if len(content) < 50:
            QMessageBox.warning(self, "提示", "梗概内容至少50字")
            return
        client = get_api_client()
        worker = ApiWorker(client.put, f"/api/creation/{ctx.project_id}/synopsis", json={"content": content, "source": "manual_input"})
        worker.result.connect(self._on_synopsis_saved)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_synopsis_saved(self, _: object) -> None:
        self._saved_synopsis = self.synopsis_edit.toPlainText()
        self.status_label.setText("梗概已保存")

    def _save_worldview(self) -> None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先选择或创建项目")
            return
        content = self.worldview_edit.toPlainText().strip()
        if len(content) < 50:
            QMessageBox.warning(self, "提示", "世界观内容至少50字")
            return
        client = get_api_client()
        worker = ApiWorker(client.put, f"/api/creation/{ctx.project_id}/worldview", json={"content": content, "source": "manual_input"})
        worker.result.connect(self._on_worldview_saved)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_worldview_saved(self, _: object) -> None:
        self._saved_worldview = self.worldview_edit.toPlainText()
        self.status_label.setText("世界观已保存")

    def _import_naming_to_worldview(self) -> None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先选择或创建项目")
            return
        reply = QMessageBox.question(
            self,
            "确认导入",
            "将命名收藏中的地点/势力类名称追加到世界观设定？\n"
            "追加内容会添加到当前世界观文本末尾，之后仍需点击'保存世界观'。",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.post, f"/api/naming/{ctx.project_id}/append-to-worldview")
        worker.result.connect(self._on_naming_worldview_loaded)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_naming_worldview_loaded(self, data: dict) -> None:
        content = data.get("content", "")
        self.worldview_edit.setPlainText(content)
        self.status_label.setText("命名收藏已追加到世界观，请点击'保存世界观'")

    def _polish_synopsis(self) -> None:
        if self._polish_syn_busy:
            return
        raw = self.synopsis_edit.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "请先输入故事梗概的简单思路")
            return
        if len(raw) < 10:
            QMessageBox.warning(self, "提示", "思路过短，请补充更多想法后再润色")
            return
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先选择或创建项目")
            return
        project_id = ctx.project_id
        self._polish_syn_busy = True
        self.polish_syn_btn.setEnabled(False)
        self.polish_syn_btn.setText("润色中…")
        self.status_label.setText("故事梗概润色中…")
        payload = {
            "target": "synopsis",
            "raw_ideas": raw,
            "book_title": self.title_input.text().strip(),
            "volume_count": self.volume_spin.value(),
            "chapters_per_volume": self.chapter_spin.value(),
            "words_per_chapter": self.words_spin.value(),
            "synopsis": "",
            "worldview": "",
            "garbled_config": None,
        }
        client = get_api_client()
        worker = ApiWorker(client.post, f"/api/creation/{project_id}/polish", json=payload)
        worker.result.connect(lambda data, t="synopsis", pid=project_id: self._on_polish_result(data, t, pid))
        worker.error.connect(lambda msg, t="synopsis": self._on_polish_error(msg, t))
        self._workers.append(worker)
        worker.start()

    def _polish_worldview(self) -> None:
        if self._polish_wv_busy:
            return
        raw = self.worldview_edit.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "请先输入世界观设定的简单思路")
            return
        if len(raw) < 10:
            QMessageBox.warning(self, "提示", "思路过短，请补充更多想法后再润色")
            return
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先选择或创建项目")
            return
        project_id = ctx.project_id
        self._polish_wv_busy = True
        self.polish_wv_btn.setEnabled(False)
        self.polish_wv_btn.setText("润色中…")
        self.status_label.setText("世界观润色中…")
        payload = {
            "target": "worldview",
            "raw_ideas": raw,
            "book_title": self.title_input.text().strip(),
            "volume_count": self.volume_spin.value(),
            "chapters_per_volume": self.chapter_spin.value(),
            "words_per_chapter": self.words_spin.value(),
            "synopsis": self.synopsis_edit.toPlainText().strip(),
            "worldview": "",
            "garbled_config": None,
        }
        client = get_api_client()
        worker = ApiWorker(client.post, f"/api/creation/{project_id}/polish", json=payload)
        worker.result.connect(lambda data, t="worldview", pid=project_id: self._on_polish_result(data, t, pid))
        worker.error.connect(lambda msg, t="worldview": self._on_polish_error(msg, t))
        self._workers.append(worker)
        worker.start()

    def _on_polish_result(self, data: dict, target: str, request_project_id: str) -> None:
        if target == "synopsis":
            self._polish_syn_busy = False
            self.polish_syn_btn.setEnabled(True)
            self.polish_syn_btn.setText("AI润色")
        else:
            self._polish_wv_busy = False
            self.polish_wv_btn.setEnabled(True)
            self.polish_wv_btn.setText("AI润色")
        ctx = get_project_context()
        if request_project_id != ctx.project_id:
            self.status_label.setText("项目已切换，本次润色结果已忽略")
            return
        polished = data.get("polished_content", "")
        if target == "synopsis":
            self.synopsis_edit.setPlainText(polished)
        else:
            self.worldview_edit.setPlainText(polished)
        label = "故事梗概" if target == "synopsis" else "世界观"
        self.status_label.setText(f"{label}润色完成，请确认或修改后保存")

    def _on_polish_error(self, msg: str, target: str) -> None:
        if target == "synopsis":
            self._polish_syn_busy = False
            self.polish_syn_btn.setEnabled(True)
            self.polish_syn_btn.setText("AI润色")
        else:
            self._polish_wv_busy = False
            self.polish_wv_btn.setEnabled(True)
            self.polish_wv_btn.setText("AI润色")
        self.status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)

    def _on_error(self, msg: str) -> None:
        self.status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)
