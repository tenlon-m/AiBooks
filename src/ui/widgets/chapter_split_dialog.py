"""章节拆分对话框 - 按字符偏移把一章拆成多章（后端已实现，此前无UI入口）."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker


class ChapterSplitDialog(QDialog):
    """按字符偏移把当前章节拆成多章。

    偏移量指「在该位置之前断开」，即第 1 段的字符区间为 [0, pos1)，
    最后一段为 [posN, 结尾)。后端要求偏移升序且不含 0 与文末。

    信号:
        split_done(dict): 拆分成功，携带后端 ChapterSplitResponse
    """

    split_done = Signal(dict)

    def __init__(
        self,
        chapter: dict,
        content: str,
        cursor_pos: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._chapter = chapter or {}
        self._content = content or ""
        self._cursor_pos = cursor_pos
        self._workers: list[ApiWorker] = []
        self.setWindowTitle("拆分章节")
        self.setMinimumSize(520, 420)
        self._init_ui()
        if cursor_pos > 0:
            self._add_position(cursor_pos)

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


    def _chapter_label(self) -> str:
        return (
            f"第{self._chapter.get('volume_no')}卷第{self._chapter.get('chapter_no')}章 "
            f"{self._chapter.get('title', '')}"
        )

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        tip = QLabel(
            f"当前章节：{self._chapter_label()}（共 {len(self._content)} 字）\n"
            "在下方添加拆分位置（字符偏移）。一个位置拆成 2 章，N 个位置拆成 N+1 章。\n"
            "拆分前会为原章节自动生成版本快照，可在「版本管理」中回滚。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #555; padding: 4px;")
        layout.addWidget(tip)

        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel("拆分位置："))
        self._pos_spin = QSpinBox()
        self._pos_spin.setRange(1, max(1, len(self._content) - 1))
        self._pos_spin.setSuffix(" 字处")
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._on_add_position)
        cursor_btn = QPushButton("使用光标位置")
        cursor_btn.setToolTip("把当前编辑器光标所在位置作为拆分点")
        cursor_btn.clicked.connect(self._on_use_cursor)
        pos_layout.addWidget(self._pos_spin, 1)
        pos_layout.addWidget(add_btn)
        pos_layout.addWidget(cursor_btn)
        layout.addLayout(pos_layout)

        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        remove_btn = QPushButton("删除选中位置")
        remove_btn.clicked.connect(self._on_remove_position)
        layout.addWidget(remove_btn)

        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel("各段标题："))
        self._titles_input = QLineEdit()
        self._titles_input.setPlaceholderText("可选，用英文逗号分隔；留空使用默认标题")
        title_layout.addWidget(self._titles_input, 1)
        layout.addLayout(title_layout)

        btn_layout = QHBoxLayout()
        self._split_btn = QPushButton("拆分")
        self._split_btn.setStyleSheet(
            "background-color: #2196f3; color: white; padding: 6px 16px; border-radius: 4px;"
        )
        self._split_btn.clicked.connect(self._do_split)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self._split_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #666; padding: 2px;")
        layout.addWidget(self._status_label)

    # ------------------------------------------------------------------ 内部
    def _positions(self) -> list[int]:
        positions: list[int] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            try:
                positions.append(int(item.text()))
            except ValueError:
                continue
        return sorted(set(positions))

    def _add_position(self, pos: int) -> None:
        if not 0 < pos < len(self._content):
            QMessageBox.warning(
                self, "提示",
                f"拆分位置必须在 1 ~ {len(self._content) - 1} 之间",
            )
            return
        if pos in self._positions():
            return
        self._list.addItem(str(pos))
        self._refresh_status()

    def _on_add_position(self) -> None:
        self._add_position(self._pos_spin.value())

    def _on_use_cursor(self) -> None:
        if self._cursor_pos <= 0:
            QMessageBox.information(self, "提示", "请先在编辑器中把光标放到要拆分的位置")
            return
        self._add_position(self._cursor_pos)

    def _on_remove_position(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        self._list.takeItem(row)
        self._refresh_status()

    def _refresh_status(self) -> None:
        n = self._list.count()
        self._status_label.setText(
            f"将拆分为 {n + 1} 章" if n else "尚未添加拆分位置"
        )

    def _do_split(self) -> None:
        positions = self._positions()
        if not positions:
            QMessageBox.warning(self, "提示", "请至少添加 1 个拆分位置")
            return
        chapter_id = self._chapter.get("chapter_id", "")
        if not chapter_id:
            QMessageBox.warning(self, "提示", "未获取到章节信息，请先选择章节")
            return

        raw_titles = self._titles_input.text().strip()
        new_titles = [t.strip() for t in raw_titles.split(",") if t.strip()] if raw_titles else []

        reply = QMessageBox.question(
            self, "确认拆分",
            f"将把《{self._chapter.get('title', '')}》拆分为 {len(positions) + 1} 章，"
            f"原章节将被删除（已生成版本快照）。\n确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._split_btn.setEnabled(False)
        self._status_label.setText("拆分中...")
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            "/api/chapters/split",
            json={
                "chapter_id": chapter_id,
                "split_positions": positions,
                "new_titles": new_titles,
            },
        )
        worker.result.connect(self._on_split_done)
        worker.error.connect(self._on_split_error)
        self._add_worker(worker)
        worker.start()

    def _on_split_done(self, data: dict) -> None:
        titles = data.get("titles", []) if isinstance(data, dict) else []
        self._status_label.setText(f"拆分完成，共 {len(titles)} 章")
        QMessageBox.information(
            self, "成功",
            f"已拆分为 {len(titles)} 章：\n" + "\n".join(f"  - {t}" for t in titles),
        )
        if isinstance(data, dict):
            self.split_done.emit(data)
        self.accept()

    def _on_split_error(self, msg: str) -> None:
        self._split_btn.setEnabled(True)
        self._status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "拆分失败", msg)
