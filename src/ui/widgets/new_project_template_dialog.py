"""新建项目模板选择对话框 - 写作模板下拉+模板应用+创建请求."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker


class NewProjectTemplateDialog(QDialog):
    """新建项目对话框 - 含写作模板下拉选择.

    选择模板后，创建请求会本地合并模板默认参数（卷数/章节/字数）。
    后端 POST /api/template-library/apply 需要已存在的项目ID，
    而本项目在创建前无法调用，故合并逻辑放在客户端完成。

    信号:
        create_requested(dict): 用户确认创建，携带项目参数与模板ID
    """

    create_requested = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._templates: list[dict] = []
        self.setWindowTitle("新建项目 - 选择写作模板")
        self.setMinimumWidth(560)
        self._init_ui()
        self._load_templates()

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


    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("新建项目")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        form = QFormLayout()

        self._template_combo = QComboBox()
        self._template_combo.addItem("空白模板（不使用模板）", None)
        self._template_combo.currentIndexChanged.connect(self._on_template_selected)
        form.addRow("写作模板：", self._template_combo)

        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("请输入书名（1-50字符）")
        form.addRow("书名：", self._title_input)

        self._volume_spin = QSpinBox()
        self._volume_spin.setRange(1, 20)
        self._volume_spin.setValue(1)
        form.addRow("卷数：", self._volume_spin)

        self._chapter_spin = QSpinBox()
        self._chapter_spin.setRange(1, 100)
        self._chapter_spin.setValue(10)
        form.addRow("每卷章节数：", self._chapter_spin)

        self._words_spin = QSpinBox()
        self._words_spin.setRange(500, 10000)
        self._words_spin.setSingleStep(500)
        self._words_spin.setValue(3000)
        form.addRow("每章字数：", self._words_spin)

        layout.addLayout(form)

        layout.addWidget(QLabel("故事梗概："))
        self._synopsis_edit = QPlainTextEdit()
        self._synopsis_edit.setPlaceholderText("输入故事梗概（可选，模板可能已填充）...")
        self._synopsis_edit.setMaximumHeight(100)
        layout.addWidget(self._synopsis_edit)

        layout.addWidget(QLabel("世界观设定："))
        self._worldview_edit = QPlainTextEdit()
        self._worldview_edit.setPlaceholderText("输入世界观设定（可选，模板可能已填充）...")
        self._worldview_edit.setMaximumHeight(100)
        layout.addWidget(self._worldview_edit)

        self._template_desc_label = QLabel("")
        self._template_desc_label.setStyleSheet(
            "color: #666; padding: 4px; background-color: #f5f5f5; border-radius: 4px;"
        )
        self._template_desc_label.setWordWrap(True)
        layout.addWidget(self._template_desc_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._create_btn = QPushButton("创建项目")
        self._create_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 20px; border-radius: 4px;"
        )
        self._create_btn.clicked.connect(self._on_create)
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._create_btn)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

    def _load_templates(self) -> None:
        """从后端加载写作模板列表（GET /api/template-library 返回全部模板）."""
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/template-library")
        worker.result.connect(self._on_templates_loaded)
        worker.error.connect(self._on_template_load_error)
        self._add_worker(worker)
        worker.start()

    def _on_templates_loaded(self, data: dict | list) -> None:
        templates = data if isinstance(data, list) else data.get("templates", [])
        for tpl in templates:
            skeleton = tpl.get("outline_skeleton", {}) or {}
            # 组装对话框需要的默认参数（模板 JSON 无 template_id，用 novel_type 标识）
            item = {
                "template_id": tpl.get("novel_type", ""),
                "name": tpl.get("name", ""),
                "description": "、".join(
                    s.get("name", "") for s in tpl.get("stages", [])[:3]
                ),
                "default_volume_count": skeleton.get("volumes"),
                "default_chapters_per_volume": skeleton.get("chapters_per_volume"),
                "default_words_per_chapter": skeleton.get("words_per_chapter"),
                "default_synopsis": "",
                "default_worldview": "",
            }
            self._templates.append(item)
            self._template_combo.addItem(item["name"], item)

    def _on_template_load_error(self, msg: str) -> None:
        self._template_desc_label.setText("模板列表加载失败，将使用空白模板")

    def _on_template_selected(self, index: int) -> None:
        tpl = self._template_combo.itemData(index)
        if not tpl:
            self._template_desc_label.setText("空白模板，不预设任何参数")
            return
        desc = tpl.get("description", "")
        self._template_desc_label.setText(f"模板说明：{desc}")
        if tpl.get("default_volume_count"):
            self._volume_spin.setValue(int(tpl["default_volume_count"]))
        if tpl.get("default_chapters_per_volume"):
            self._chapter_spin.setValue(int(tpl["default_chapters_per_volume"]))
        if tpl.get("default_words_per_chapter"):
            self._words_spin.setValue(int(tpl["default_words_per_chapter"]))
        if tpl.get("default_synopsis"):
            self._synopsis_edit.setPlainText(tpl["default_synopsis"])
        if tpl.get("default_worldview"):
            self._worldview_edit.setPlainText(tpl["default_worldview"])

    def _on_create(self) -> None:
        book_title = self._title_input.text().strip()
        if not book_title:
            QMessageBox.warning(self, "提示", "请输入书名")
            return
        if len(book_title) > 50:
            QMessageBox.warning(self, "提示", "书名不能超过50字符")
            return
        tpl = self._template_combo.currentData()
        template_id = tpl.get("template_id") if tpl else None
        payload = {
            "book_title": book_title,
            "volume_count": int(self._volume_spin.value()),
            "chapters_per_volume": int(self._chapter_spin.value()),
            "words_per_chapter": int(self._words_spin.value()),
            "synopsis": self._synopsis_edit.toPlainText().strip(),
            "worldview": self._worldview_edit.toPlainText().strip(),
            "template_id": template_id,
        }
        tpl = self._template_combo.currentData()
        if template_id and tpl:
            payload = self._merge_template_defaults(tpl, payload)
        self.create_requested.emit(payload)
        self.accept()

    @staticmethod
    def _merge_template_defaults(tpl: dict, payload: dict) -> dict:
        """把模板默认参数合并进创建请求（项目尚未创建，不能走后端 /apply）."""
        defaults = {
            "volume_count": tpl.get("default_volume_count"),
            "chapters_per_volume": tpl.get("default_chapters_per_volume"),
            "words_per_chapter": tpl.get("default_words_per_chapter"),
        }
        for key, value in defaults.items():
            if value:
                payload[key] = int(value)
        if tpl.get("default_synopsis") and not payload.get("synopsis"):
            payload["synopsis"] = tpl["default_synopsis"]
        if tpl.get("default_worldview") and not payload.get("worldview"):
            payload["worldview"] = tpl["default_worldview"]
        payload["template_id"] = tpl.get("template_id")
        return payload