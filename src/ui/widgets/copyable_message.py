"""可复制的消息弹窗 - 全局接管 QMessageBox，让长文本可选中/一键复制.

背景：QMessageBox 的正文默认不可选中（textInteractionFlags 为
LinksAccessibleByMouse），AI 调用失败、堆栈、[SQL: ...] 等长报错无法复制出来反馈。

方案：install_copyable_message_boxes() 以自定义 QDialog 替换 QMessageBox 的
about/information/question/warning/critical 静态方法，调用处零改动：
- 正文用只读 QTextEdit 呈现，支持划选、Ctrl+A、Ctrl+C，长文本自动滚动
- 提供"复制全部"按钮，一键写入系统剪贴板
- 返回 QMessageBox.StandardButton，调用方 `== QMessageBox.Yes` 等判断不受影响
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QTextEdit,
    QVBoxLayout,
)

_STYLE_ICON: dict[Any, QStyle.StandardPixmap] = {
    QMessageBox.Icon.Information: QStyle.StandardPixmap.SP_MessageBoxInformation,
    QMessageBox.Icon.Warning: QStyle.StandardPixmap.SP_MessageBoxWarning,
    QMessageBox.Icon.Critical: QStyle.StandardPixmap.SP_MessageBoxCritical,
    QMessageBox.Icon.Question: QStyle.StandardPixmap.SP_MessageBoxQuestion,
}

# 标准按钮 -> (按钮文案, 按钮栏角色)，按展示顺序排列
_BUTTON_SPECS: list[tuple[Any, str, Any]] = [
    (QMessageBox.StandardButton.Ok, "确定", QDialogButtonBox.ButtonRole.AcceptRole),
    (QMessageBox.StandardButton.Yes, "是", QDialogButtonBox.ButtonRole.AcceptRole),
    (QMessageBox.StandardButton.Save, "保存", QDialogButtonBox.ButtonRole.AcceptRole),
    (QMessageBox.StandardButton.Apply, "应用", QDialogButtonBox.ButtonRole.ApplyRole),
    (QMessageBox.StandardButton.Retry, "重试", QDialogButtonBox.ButtonRole.AcceptRole),
    (QMessageBox.StandardButton.Ignore, "忽略", QDialogButtonBox.ButtonRole.AcceptRole),
    (QMessageBox.StandardButton.No, "否", QDialogButtonBox.ButtonRole.RejectRole),
    (QMessageBox.StandardButton.Cancel, "取消", QDialogButtonBox.ButtonRole.RejectRole),
    (QMessageBox.StandardButton.Close, "关闭", QDialogButtonBox.ButtonRole.RejectRole),
    (
        QMessageBox.StandardButton.Discard,
        "放弃",
        QDialogButtonBox.ButtonRole.DestructiveRole,
    ),
    (QMessageBox.StandardButton.Abort, "中止", QDialogButtonBox.ButtonRole.RejectRole),
    (QMessageBox.StandardButton.Reset, "重置", QDialogButtonBox.ButtonRole.ResetRole),
    (QMessageBox.StandardButton.Help, "帮助", QDialogButtonBox.ButtonRole.HelpRole),
]


class CopyableMessageDialog(QDialog):
    """正文可选中复制的消息对话框."""

    def __init__(
        self,
        parent: Any,
        icon: Any,
        title: str,
        text: str,
        buttons: int,
        default_button: int = 0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or "提示")
        self.setMinimumSize(620, 320)
        self._result: Any = QMessageBox.StandardButton.NoButton
        self._has_reject_button = False

        layout = QVBoxLayout(self)
        row = QHBoxLayout()

        icon_label = QLabel(self)
        pixmap = _STYLE_ICON.get(icon, QStyle.StandardPixmap.SP_MessageBoxInformation)
        icon_label.setPixmap(self.style().standardIcon(pixmap).pixmap(32, 32))
        icon_label.setFixedWidth(40)
        row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        # 只读 QTextEdit 承载正文：天然支持划选/全选/复制，长文本可滚动
        self._text_edit = QTextEdit(self)
        self._text_edit.setPlainText(text or "")
        self._text_edit.setReadOnly(True)
        self._text_edit.setMinimumHeight(160)
        self._text_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        row.addWidget(self._text_edit, 1)
        layout.addLayout(row)

        bottom = QHBoxLayout()
        self._copy_btn = QPushButton("复制全部", self)
        self._copy_btn.setToolTip("把弹窗内容整段复制到剪贴板")
        self._copy_btn.clicked.connect(self._copy_all)
        bottom.addWidget(self._copy_btn)
        bottom.addStretch()

        self._button_box = QDialogButtonBox(self)
        buttons_int = int(buttons) if buttons is not None else 0
        default_int = int(default_button) if default_button else 0
        for std_btn, label, role in _BUTTON_SPECS:
            if not buttons_int & int(std_btn):
                continue
            btn = self._button_box.addButton(label, role)
            btn.clicked.connect(lambda _checked=False, sb=std_btn: self._finish(sb))
            if role in (
                QDialogButtonBox.ButtonRole.RejectRole,
                QDialogButtonBox.ButtonRole.DestructiveRole,
            ):
                self._has_reject_button = True
            if int(std_btn) == default_int:
                btn.setDefault(True)
                btn.setFocus()
        if not self._button_box.buttons():
            ok_btn = self._button_box.addButton(
                "确定", QDialogButtonBox.ButtonRole.AcceptRole
            )
            ok_btn.clicked.connect(
                lambda _checked=False: self._finish(QMessageBox.StandardButton.Ok)
            )
        bottom.addWidget(self._button_box)
        layout.addLayout(bottom)

    @property
    def result_button(self) -> Any:
        """用户点击的标准按钮（未点击/直接关闭时为 NoButton）."""
        return self._result

    def _finish(self, standard_button: Any) -> None:
        self._result = standard_button
        self.accept()

    def reject(self) -> None:
        """Esc 或关闭窗口 - 映射为取消/否，保持与 QMessageBox 一致的行为."""
        if self._result == QMessageBox.StandardButton.NoButton and self._has_reject_button:
            self._result = QMessageBox.StandardButton.Cancel
        super().reject()

    def _copy_all(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._text_edit.toPlainText())
        self._copy_btn.setText("已复制")


def _show_copyable_box(
    parent: Any,
    icon: Any,
    title: str,
    text: str,
    buttons: Any,
    default_button: Any,
) -> Any:
    dialog = CopyableMessageDialog(parent, icon, title, text, buttons, default_button)
    dialog.exec()
    return dialog.result_button


_installed = False


def install_copyable_message_boxes() -> None:
    """全局接管 QMessageBox 静态方法（幂等，重复调用无副作用）."""
    global _installed
    if _installed:
        return

    ok = int(QMessageBox.StandardButton.Ok)
    yes = int(QMessageBox.StandardButton.Yes)
    yes_no = yes | int(QMessageBox.StandardButton.No)

    def warning(
        parent: Any = None,
        title: str = "",
        text: str = "",
        buttons: Any = ok,
        defaultButton: Any = 0,
        **_: Any,
    ) -> Any:
        return _show_copyable_box(
            parent, QMessageBox.Icon.Warning, title, text, buttons, defaultButton or ok
        )

    def critical(
        parent: Any = None,
        title: str = "",
        text: str = "",
        buttons: Any = ok,
        defaultButton: Any = 0,
        **_: Any,
    ) -> Any:
        return _show_copyable_box(
            parent, QMessageBox.Icon.Critical, title, text, buttons, defaultButton or ok
        )

    def information(
        parent: Any = None,
        title: str = "",
        text: str = "",
        buttons: Any = ok,
        defaultButton: Any = 0,
        **_: Any,
    ) -> Any:
        return _show_copyable_box(
            parent, QMessageBox.Icon.Information, title, text, buttons, defaultButton or ok
        )

    def question(
        parent: Any = None,
        title: str = "",
        text: str = "",
        buttons: Any = yes_no,
        defaultButton: Any = 0,
        **_: Any,
    ) -> Any:
        return _show_copyable_box(
            parent, QMessageBox.Icon.Question, title, text, buttons, defaultButton or yes
        )

    def about(
        parent: Any = None,
        title: str = "",
        text: str = "",
        **_: Any,
    ) -> Any:
        return _show_copyable_box(
            parent, QMessageBox.Icon.Information, title, text, ok, ok
        )

    QMessageBox.warning = staticmethod(warning)  # type: ignore[assignment]
    QMessageBox.critical = staticmethod(critical)  # type: ignore[assignment]
    QMessageBox.information = staticmethod(information)  # type: ignore[assignment]
    QMessageBox.question = staticmethod(question)  # type: ignore[assignment]
    QMessageBox.about = staticmethod(about)  # type: ignore[assignment]
    _installed = True
