"""小说导出页 - 多格式导出（TXT/DOCX/EPUB/Markdown/PDF）."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.config.settings import get_config
from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context

_FORMAT_PATHS = {
    "TXT": "",
    "DOCX": "/docx",
    "EPUB": "/epub",
    "Markdown": "/markdown",
    "PDF": "/pdf",
}


class ExportPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._templates: list[dict] = []
        self._init_ui()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)
        self._load_templates()

    def clear_page(self) -> None:
        self.dir_input.setText(str(get_config().exports_dir))
        self.result_label.clear()

    def has_unsaved_changes(self) -> bool:
        return False

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        if project_id:
            self.project_label.setText(info.get("book_title", project_id[:8]))
        else:
            self.project_label.setText("未选择")

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("小说导出")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        proj_layout = QHBoxLayout()
        proj_layout.addWidget(QLabel("当前项目："))
        self.project_label = QLabel("未选择")
        self.project_label.setStyleSheet("font-weight: bold;")
        proj_layout.addWidget(self.project_label, 1)
        layout.addLayout(proj_layout)

        fmt_layout = QHBoxLayout()
        fmt_layout.addWidget(QLabel("导出格式："))
        self.format_combo = QComboBox()
        self.format_combo.addItems(list(_FORMAT_PATHS.keys()))
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        fmt_layout.addWidget(self.format_combo, 1)
        layout.addLayout(fmt_layout)

        tpl_layout = QHBoxLayout()
        tpl_layout.addWidget(QLabel("排版模板："))
        self.template_combo = QComboBox()
        self.template_combo.addItem("默认（无模板）", "")
        tpl_layout.addWidget(self.template_combo, 1)
        self.reload_tpl_btn = QPushButton("刷新")
        self.reload_tpl_btn.clicked.connect(self._load_templates)
        tpl_layout.addWidget(self.reload_tpl_btn)
        layout.addLayout(tpl_layout)

        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("导出目录："))
        self.dir_input = QLineEdit()
        self.dir_input.setText(str(get_config().exports_dir))
        dir_layout.addWidget(self.dir_input, 1)
        self.browse_btn = QPushButton("浏览...")
        self.browse_btn.clicked.connect(self._browse_dir)
        dir_layout.addWidget(self.browse_btn)
        layout.addLayout(dir_layout)

        opts_label = QLabel("导出选项：")
        opts_label.setStyleSheet("font-weight: bold; padding-top: 4px;")
        layout.addWidget(opts_label)

        opts_row1 = QHBoxLayout()
        self.chk_pagination = QCheckBox("章节分页")
        self.chk_pagination.setChecked(True)
        opts_row1.addWidget(self.chk_pagination)
        self.chk_cover = QCheckBox("封面页")
        self.chk_cover.setChecked(True)
        opts_row1.addWidget(self.chk_cover)
        opts_row1.addStretch()
        layout.addLayout(opts_row1)

        opts_row2 = QHBoxLayout()
        self.chk_outline = QCheckBox("包含大纲")
        opts_row2.addWidget(self.chk_outline)
        self.chk_characters = QCheckBox("包含角色设定")
        opts_row2.addWidget(self.chk_characters)
        opts_row2.addStretch()
        layout.addLayout(opts_row2)

        self.export_btn = QPushButton("导出小说")
        self.export_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self.export_btn.clicked.connect(self._export)
        layout.addWidget(self.export_btn)

        self.result_label = QLabel("")
        self.result_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.result_label)

        layout.addStretch()

    def _on_format_changed(self, fmt: str) -> None:
        is_txt = fmt == "TXT"
        self.template_combo.setEnabled(not is_txt)
        self.reload_tpl_btn.setEnabled(not is_txt)
        self.chk_pagination.setEnabled(not is_txt)
        self.chk_outline.setEnabled(not is_txt)
        self.chk_characters.setEnabled(not is_txt)
        self.chk_cover.setEnabled(not is_txt)

        current = self.template_combo.currentData()
        self.template_combo.clear()
        self.template_combo.addItem("默认（无模板）", "")
        if not is_txt:
            fmt_lower = fmt.lower()
            for tpl in self._templates:
                if tpl.get("format") == fmt_lower:
                    label = f"{tpl['name']}{'（内置）' if tpl.get('is_builtin') else ''}"
                    self.template_combo.addItem(label, tpl["template_id"])
        if current:
            idx = self.template_combo.findData(current)
            if idx >= 0:
                self.template_combo.setCurrentIndex(idx)

    def _load_templates(self) -> None:
        """异步加载排版模板（原实现在UI线程发同步HTTP，失败还会静默置空）."""
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/layout-templates")
        worker.result.connect(self._on_templates_loaded)
        worker.error.connect(self._on_templates_error)
        self._workers.append(worker)
        worker.start()

    def _on_templates_loaded(self, data: dict) -> None:
        self._templates = data.get("templates", []) if isinstance(data, dict) else []
        self._on_format_changed(self.format_combo.currentText())

    def _on_templates_error(self, msg: str) -> None:
        self._templates = []
        self._on_format_changed(self.format_combo.currentText())
        self.result_label.setText(f"排版模板加载失败（已回退为默认排版）：{msg}")

    def _browse_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if d:
            self.dir_input.setText(d)

    def _export(self) -> None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先在创作参数页选择或创建项目")
            return
        target_dir = self.dir_input.text().strip()
        if not target_dir:
            QMessageBox.warning(self, "提示", "请输入导出目录")
            return

        fmt = self.format_combo.currentText()
        path_suffix = _FORMAT_PATHS[fmt]
        template_id = self.template_combo.currentData() or None

        if path_suffix == "":
            payload = {"project_id": ctx.project_id, "target_dir": target_dir}
        else:
            payload = {
                "project_id": ctx.project_id,
                "target_dir": target_dir,
                "template_id": template_id,
                "options": {
                    "chapter_pagination": self.chk_pagination.isChecked(),
                    "include_outline": self.chk_outline.isChecked(),
                    "include_characters": self.chk_characters.isChecked(),
                    "cover_page": self.chk_cover.isChecked(),
                },
            }

        client = get_api_client()
        self.export_btn.setEnabled(False)
        self.result_label.setText(f"正在导出 {fmt} ...")
        worker = ApiWorker(client.post, f"/api/export{path_suffix}", json=payload)
        worker.result.connect(self._on_export_done)
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.start()

    def _on_export_done(self, data: dict) -> None:
        self.export_btn.setEnabled(True)
        file_path = data.get("file_path", "")
        char_count = data.get("char_count", 0)
        self.result_label.setText(f"导出成功：{file_path}（{char_count}字）")
        QMessageBox.information(self, "成功", f"小说已导出：\n{file_path}\n共 {char_count} 字")

    def _on_error(self, msg: str) -> None:
        self.export_btn.setEnabled(True)
        self.result_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)
