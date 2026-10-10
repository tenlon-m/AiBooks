"""批注编辑对话框 - 创建/编辑章节段落批注.

后端 API:
    POST /api/chapters/annotations                  创建批注
    PUT  /api/chapters/annotations/{annotation_id}  更新批注
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker

# 类型/状态中英文映射
_TYPE_CN_TO_EN = {"文字备注": "note", "AI建议": "ai_suggestion"}
_TYPE_EN_TO_CN = {"note": "文字备注", "ai_suggestion": "AI建议"}
_STATUS_CN_TO_EN = {"待处理": "pending", "已处理": "resolved"}
_STATUS_EN_TO_CN = {"pending": "待处理", "resolved": "已处理"}


class AnnotationEditDialog(QDialog):
    """批注编辑对话框.

    用於创建新批注或编辑已有批注。创建時調用 POST，编辑時調用 PUT。
    完成后发射 saved(dict) 信号攜帶后端返回的批注对象。

    信号:
        saved(dict): 保存成功，攜帶批注數據
    """

    saved = Signal(dict)

    def __init__(
        self,
        chapter_id: str,
        anchor_text: str = "",
        annotation_id: str | None = None,
        existing: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._chapter_id = chapter_id
        self._anchor_text = anchor_text
        self._annotation_id = annotation_id
        self._existing = existing or {}
        self._workers: list[ApiWorker] = []
        self.setWindowTitle(
            "编辑批注" if annotation_id else "添加批注"
        )
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self._init_ui()
        self._fill_fields()

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

        # 錨定段落预览（只讀）
        if self._anchor_text:
            layout.addWidget(QLabel("錨定段落："))
            anchor_view = QPlainTextEdit()
            anchor_view.setReadOnly(True)
            anchor_view.setPlainText(self._anchor_text)
            anchor_view.setMaximumHeight(80)
            anchor_view.setStyleSheet("background-color: #f5f5f5;")
            layout.addWidget(anchor_view)

        form = QFormLayout()

        self._type_combo = QComboBox()
        self._type_combo.addItem("文字备注", "note")
        self._type_combo.addItem("AI建议", "ai_suggestion")
        form.addRow("类型：", self._type_combo)

        self._status_combo = QComboBox()
        self._status_combo.addItem("待处理", "pending")
        self._status_combo.addItem("已处理", "resolved")
        form.addRow("状态：", self._status_combo)

        layout.addLayout(form)

        layout.addWidget(QLabel("批注内容："))
        self._content_edit = QTextEdit()
        self._content_edit.setPlaceholderText("输入批注内容")
        layout.addWidget(self._content_edit, 1)

        # 字數提示
        self._char_label = QLabel()
        self._char_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._char_label)
        self._content_edit.textChanged.connect(self._update_char_count)
        self._update_char_count()

        # 状态
        self._status_label = QLabel("就緒")
        self._status_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._status_label)

        # 按鈕
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._save_btn = QPushButton("保存")
        self._save_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _fill_fields(self) -> None:
        if not self._existing:
            return
        ann_type = self._existing.get("annotation_type", "note")
        idx = self._type_combo.findData(ann_type)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)
        status = self._existing.get("status", "pending")
        sidx = self._status_combo.findData(status)
        if sidx >= 0:
            self._status_combo.setCurrentIndex(sidx)
        self._content_edit.setPlainText(self._existing.get("content", ""))

    def _update_char_count(self) -> None:
        count = len(self._content_edit.toPlainText().strip())
        self._char_label.setText(f"{count} 字")

    def _build_payload(self) -> dict:
        return {
            "chapter_id": self._chapter_id,
            "annotation_type": self._type_combo.currentData(),
            "status": self._status_combo.currentData(),
            "content": self._content_edit.toPlainText().strip(),
            "anchor_text": self._anchor_text,
        }

    def _save(self) -> None:
        content = self._content_edit.toPlainText().strip()
        if not content:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "提示", "批注内容不能为空")
            return
        self._status_label.setText("保存中...")
        self._save_btn.setEnabled(False)
        client = get_api_client()
        if self._annotation_id:
            # 编辑：PUT
            worker = ApiWorker(
                client.put,
                f"/api/chapters/annotations/{self._annotation_id}",
                json=self._build_payload(),
            )
        else:
            # 创建：POST
            worker = ApiWorker(
                client.post,
                "/api/chapters/annotations",
                json=self._build_payload(),
            )
        worker.result.connect(self._on_saved)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_saved(self, data: dict) -> None:
        self._save_btn.setEnabled(True)
        self._status_label.setText("已保存")
        self.saved.emit(data)
        self.accept()

    def _on_error(self, msg: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        self._save_btn.setEnabled(True)
        self._status_label.setText(f"保存失敗：{msg}")
        QMessageBox.critical(self, "错误", msg)