"""一键拆书页面 - 文件上传、AI拆解、大纲树形展示、要素展示、二创工程."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker


class BookTeardownPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._teardown_id: str | None = None
        self._active_btn: QPushButton | None = None
        self._init_ui()

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

        title = QLabel("一键拆书工具")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        upload_layout = QHBoxLayout()
        self.upload_btn = QPushButton("选择书籍文件")
        self.upload_btn.clicked.connect(self._on_upload_clicked)
        upload_layout.addWidget(self.upload_btn)
        self.file_label = QLabel("未选择文件")
        upload_layout.addWidget(self.file_label, 1)
        layout.addLayout(upload_layout)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.teardown_btn = QPushButton("拆解多级大纲")
        self.teardown_btn.clicked.connect(self._on_teardown_clicked)
        self.teardown_btn.setEnabled(False)
        layout.addWidget(self.teardown_btn)

        layout.addWidget(QLabel("多级大纲："))
        self.outline_tree = QTreeWidget()
        self.outline_tree.setHeaderHidden(True)
        layout.addWidget(self.outline_tree, 2)

        self.extract_btn = QPushButton("提取五类要素")
        self.extract_btn.clicked.connect(self._on_extract_clicked)
        self.extract_btn.setEnabled(False)
        layout.addWidget(self.extract_btn)

        self.elements_tabs = QTabWidget()
        self.characters_tab = QTextEdit()
        self.characters_tab.setReadOnly(True)
        self.elements_tabs.addTab(self.characters_tab, "人物")
        self.time_places_tab = QTextEdit()
        self.time_places_tab.setReadOnly(True)
        self.elements_tabs.addTab(self.time_places_tab, "时间地点")
        self.worldview_tab = QTextEdit()
        self.worldview_tab.setReadOnly(True)
        self.elements_tabs.addTab(self.worldview_tab, "世界观")
        self.items_tab = QTextEdit()
        self.items_tab.setReadOnly(True)
        self.elements_tabs.addTab(self.items_tab, "物品")
        self.events_tab = QTextEdit()
        self.events_tab.setReadOnly(True)
        self.elements_tabs.addTab(self.events_tab, "事件")
        layout.addWidget(self.elements_tabs, 2)

        create_layout = QHBoxLayout()
        create_layout.addWidget(QLabel("二创书名："))
        self.book_title_input = QLineEdit()
        self.book_title_input.setPlaceholderText("请输入二创书名")
        create_layout.addWidget(self.book_title_input, 1)
        self.create_btn = QPushButton("基于结果二创")
        self.create_btn.clicked.connect(self._on_create_clicked)
        self.create_btn.setEnabled(False)
        create_layout.addWidget(self.create_btn)
        layout.addLayout(create_layout)

    def _on_upload_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择书籍文件", "", "书籍文件 (*.txt *.pdf *.epub *.docx)"
        )
        if not path:
            return
        self.file_label.setText(path)
        self.progress.setValue(10)
        self.upload_btn.setEnabled(False)
        self._active_btn = self.upload_btn
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/book-teardown/upload", json={"file_path": path})
        worker.result.connect(self._on_upload_done)
        worker.error.connect(self._on_error)
        worker.start()
        self._add_worker(worker)

    def _on_upload_done(self, result: dict) -> None:
        self._active_btn = None
        self.upload_btn.setEnabled(True)
        self._teardown_id = result.get("teardown_id")
        self.progress.setValue(30)
        self.teardown_btn.setEnabled(True)
        QMessageBox.information(self, "成功", "文件解析完成，可以开始拆解")

    def _on_teardown_clicked(self) -> None:
        if not self._teardown_id:
            return
        self.progress.setValue(40)
        self.teardown_btn.setEnabled(False)
        self._active_btn = self.teardown_btn
        client = get_api_client()
        worker = ApiWorker(
            client.post, f"/api/book-teardown/{self._teardown_id}/teardown-outline"
        )
        worker.result.connect(self._on_teardown_done)
        worker.error.connect(self._on_error)
        worker.start()
        self._add_worker(worker)

    def _on_teardown_done(self, result: dict) -> None:
        self._active_btn = None
        self.teardown_btn.setEnabled(True)
        outline = result.get("multi_level_outline", "")
        self._populate_outline_tree(outline)
        self.progress.setValue(60)
        self.extract_btn.setEnabled(True)
        QMessageBox.information(self, "成功", "大纲拆解完成，可以提取要素")

    def _populate_outline_tree(self, outline: str) -> None:
        self.outline_tree.clear()
        lines = outline.strip().split("\n")
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for line in lines:
            if not line.strip():
                continue
            stripped = line.lstrip("　 \t")
            indent = len(line) - len(stripped)
            level = indent // 2
            text = stripped.strip()
            item = QTreeWidgetItem([text])
            while stack and stack[-1][0] >= level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(item)
            else:
                self.outline_tree.addTopLevelItem(item)
            stack.append((level, item))

    def _on_extract_clicked(self) -> None:
        if not self._teardown_id:
            return
        self.progress.setValue(70)
        self.extract_btn.setEnabled(False)
        self._active_btn = self.extract_btn
        client = get_api_client()
        worker = ApiWorker(
            client.post, f"/api/book-teardown/{self._teardown_id}/extract-elements"
        )
        worker.result.connect(self._on_extract_done)
        worker.error.connect(self._on_error)
        worker.start()
        self._add_worker(worker)

    def _on_extract_done(self, result: dict) -> None:
        self._active_btn = None
        self.extract_btn.setEnabled(True)
        self.characters_tab.setPlainText(result.get("characters") or "")
        self.time_places_tab.setPlainText(result.get("time_places") or "")
        self.worldview_tab.setPlainText(result.get("worldview") or "")
        self.items_tab.setPlainText(result.get("special_items") or "")
        self.events_tab.setPlainText(result.get("events") or "")
        self.progress.setValue(90)
        self.create_btn.setEnabled(True)
        QMessageBox.information(self, "成功", "要素提取完成，可以创建二创工程")

    def _on_create_clicked(self) -> None:
        if not self._teardown_id:
            return
        book_title = self.book_title_input.text().strip()
        if not book_title:
            QMessageBox.warning(self, "提示", "请输入二创书名")
            return
        self.create_btn.setEnabled(False)
        self._active_btn = self.create_btn
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            f"/api/book-teardown/{self._teardown_id}/create-project",
            json={"teardown_id": self._teardown_id, "book_title": book_title},
        )
        worker.result.connect(self._on_create_done)
        worker.error.connect(self._on_error)
        worker.start()
        self._add_worker(worker)

    def _on_create_done(self, result: dict) -> None:
        self._active_btn = None
        self.create_btn.setEnabled(True)
        self.progress.setValue(100)
        QMessageBox.information(self, "成功", f"已创建工程：{result.get('book_title', '')}")

    def _on_error(self, msg: str) -> None:
        self.progress.setValue(0)
        if self._active_btn is not None:
            self._active_btn.setEnabled(True)
            self._active_btn = None
        QMessageBox.critical(self, "错误", msg)