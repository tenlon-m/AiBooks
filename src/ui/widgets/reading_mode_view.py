"""阅读模式视图 - 只读 QTextEdit，应用书籍排版样式表（字体/行距/背景色）."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit, QWidget

from src.config.settings import get_config


class ReadingModeView(QTextEdit):
    """阅读模式视图：只读、应用书籍排版样式（字体/行距/背景色）.

    style_changed(dict) 信号在样式参数变化时触发，
    外部（如 ReadingModeController）可连接该信号联动其他控件。
    """

    style_changed = Signal(dict)

    # 预设背景色（含护眼模式 #C7EDCC）
    PRESET_BACKGROUNDS: dict[str, str] = {
        "默认": "#FFFFFF",
        "护眼": "#C7EDCC",
        "米黄": "#F5F5DC",
        "深色": "#2B2B2B",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        cfg = get_config()
        self._font_size: int = cfg.reading_mode_default_font_size
        self._line_spacing: float = cfg.reading_mode_default_line_spacing
        self._background: str = self.PRESET_BACKGROUNDS["默认"]
        self._font_family: str = "Microsoft YaHei"
        self._apply_stylesheet()

    def set_content(self, text: str) -> None:
        """设置章节内容并应用当前行距."""
        self.setPlainText(text)
        self._apply_line_spacing()

    def set_font_size(self, size: int) -> None:
        size = max(12, min(36, size))
        if size == self._font_size:
            return
        self._font_size = size
        self._apply_stylesheet()
        self.style_changed.emit(self.current_style())

    def set_line_spacing(self, spacing: float) -> None:
        spacing = max(1.0, min(3.0, spacing))
        if abs(spacing - self._line_spacing) < 1e-3:
            return
        self._line_spacing = spacing
        self._apply_line_spacing()
        self.style_changed.emit(self.current_style())

    def set_background(self, color: str) -> None:
        if color == self._background:
            return
        self._background = color
        self._apply_stylesheet()
        self.style_changed.emit(self.current_style())

    def set_font_family(self, family: str) -> None:
        if family == self._font_family:
            return
        self._font_family = family
        self._apply_stylesheet()
        self.style_changed.emit(self.current_style())

    def current_style(self) -> dict:
        return {
            "font_family": self._font_family,
            "font_size": self._font_size,
            "line_spacing": self._line_spacing,
            "background": self._background,
        }

    def _apply_stylesheet(self) -> None:
        fg = self._pick_foreground(self._background)
        self.setStyleSheet(
            f"QTextEdit {{"
            f"  font-family: '{self._font_family}';"
            f"  font-size: {self._font_size}px;"
            f"  background-color: {self._background};"
            f"  color: {fg};"
            f"  border: none;"
            f"  padding: 24px 32px;"
            f"}}"
        )
        self._apply_line_spacing()

    def _apply_line_spacing(self) -> None:
        """对文档所有文本块设置行距（FixedHeight 模式，行高=字号×行距倍数）."""
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextBlockFormat()
        line_height_px = int(self._font_size * self._line_spacing)
        fmt.setLineHeight(line_height_px, 1)
        fmt.setTopMargin(0)
        fmt.setBottomMargin(0)
        cursor.mergeBlockFormat(fmt)

    @staticmethod
    def _pick_foreground(bg: str) -> str:
        """根据全局主题选择前景色；若全局主题不可用则按背景亮度二值回退."""
        try:
            from src.ui.theme.theme_manager import ThemeManager
            mgr = ThemeManager.instance()
            resolved = mgr.resolve_colors(mgr.current_theme().theme_id)
            return resolved.foreground
        except Exception:
            try:
                hex_str = bg.lstrip("#")
                r = int(hex_str[0:2], 16)
                g = int(hex_str[2:4], 16)
                b = int(hex_str[4:6], 16)
                luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
                return "#E0E0E0" if luminance < 0.5 else "#222222"
            except Exception:
                return "#222222"