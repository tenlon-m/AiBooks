"""章节合并对话框 - 勾选相邻章节合并为一章（后端已实现，此前无UI入口）."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker


class ChapterMergeDialog(QDialog):
    """选择 2 个及以上**相邻**章节合并为一章。

    合并后原章节都会生成自动版本快照再删除，可在版本管理中回滚。

    信号:
        merge_done(dict): 合并成功，携带后端 ChapterMergeResponse
    """

    merge_done = Signal(dict)

    def __init__(self, chapters: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chapters = sorted(
            chapters or [],
            key=lambda c: (int(c.get("volume_no", 0) or 0), int(c.get("chapter_no", 0) or 0)),
        )
        self._workers: list[ApiWorker] = []
        self.setWindowTitle("合并章节")
        self.setMinimumSize(560, 460)
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

        tip = QLabel(
            "勾选需要合并的章节（至少 2 章，必须相邻）。\n"
            "同卷内要求章号连续；跨卷仅支持「上一卷最后一章 + 下一卷第一章」。\n"
            "合并前会为原章节自动生成版本快照，可在「版本管理」中回滚。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #555; padding: 4px;")
        layout.addWidget(tip)

        self._list = QListWidget()
        for c in self._chapters:
            item = QListWidgetItem(
                f"第{c.get('volume_no')}卷第{c.get('chapter_no')}章  {c.get('title', '')}"
            )
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, c.get("chapter_id", ""))
            self._list.addItem(item)
        self._list.itemChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list, 1)

        self._selected_label = QLabel("已选择 0 章")
        self._selected_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._selected_label)

        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel("合并后标题："))
        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("留空则由 AI 根据合并内容自动生成")
        title_layout.addWidget(self._title_input, 1)
        layout.addLayout(title_layout)

        btn_layout = QHBoxLayout()
        self._merge_btn = QPushButton("合并")
        self._merge_btn.setStyleSheet(
            "background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._merge_btn.clicked.connect(self._do_merge)
        self._merge_btn.setEnabled(False)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self._merge_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._status_label)

    # ------------------------------------------------------------------ 内部
    def _selected_chapter_ids(self) -> list[str]:
        ids: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                cid = item.data(Qt.ItemDataRole.UserRole)
                if cid:
                    ids.append(cid)
        return ids

    def _on_selection_changed(self, _item: QListWidgetItem) -> None:
        ids = self._selected_chapter_ids()
        self._selected_label.setText(f"已选择 {len(ids)} 章")
        self._merge_btn.setEnabled(len(ids) >= 2)

    def _do_merge(self) -> None:
        chapter_ids = self._selected_chapter_ids()
        if len(chapter_ids) < 2:
            QMessageBox.warning(self, "提示", "请至少勾选 2 个章节")
            return

        # 按列表（即卷/章号）顺序提交，后端按此顺序校验相邻性
        order = {c.get("chapter_id", ""): i for i, c in enumerate(self._chapters)}
        chapter_ids.sort(key=lambda cid: order.get(cid, 0))

        reply = QMessageBox.question(
            self, "确认合并",
            f"将把 {len(chapter_ids)} 个章节合并为 1 章，原章节将被删除（已生成版本快照）。\n确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        new_title = self._title_input.text().strip() or None
        self._merge_btn.setEnabled(False)
        self._status_label.setText("合并中...")
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            "/api/chapters/merge",
            json={"chapter_ids": chapter_ids, "new_title": new_title},
        )
        worker.result.connect(self._on_merge_done)
        worker.error.connect(self._on_merge_error)
        self._add_worker(worker)
        worker.start()

    def _on_merge_done(self, data: dict) -> None:
        title = data.get("new_title", "") if isinstance(data, dict) else ""
        self._status_label.setText(f"合并完成：{title}")
        QMessageBox.information(
            self, "成功",
            f"已合并为：{title}\n"
            f"第{data.get('volume_no')}卷第{data.get('chapter_no')}章，"
            f"共 {data.get('word_count', 0)} 字",
        )
        if isinstance(data, dict):
            self.merge_done.emit(data)
        self.accept()

    def _on_merge_error(self, msg: str) -> None:
        self._merge_btn.setEnabled(True)
        self._status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "合并失败", msg)
