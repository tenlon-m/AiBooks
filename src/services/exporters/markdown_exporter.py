"""Markdown 导出器 - 生成纯文本 Markdown 文件."""
from __future__ import annotations

from pathlib import Path

from src.utils.logger import get_logger


class MarkdownExporter:
    """按导出选项生成 Markdown 文件（正文原样写入）."""

    def __init__(self) -> None:
        self.logger = get_logger()

    def export(
        self,
        book_title: str,
        chapters: list,
        template: dict,
        options: dict,
        file_path: Path,
        outline_text: str = "",
        characters_text: str = "",
    ) -> int:
        """执行导出，返回总字数."""
        lines: list[str] = []

        if options.get("cover_page", True):
            lines.append(f"# {book_title}")
            lines.append("")
            lines.append("---")
            lines.append("")

        if options.get("include_outline", False) and outline_text:
            lines.append("## 大纲")
            lines.append("")
            lines.append(outline_text)
            lines.append("")

        if options.get("include_characters", False) and characters_text:
            lines.append("## 角色设定")
            lines.append("")
            lines.append(characters_text)
            lines.append("")

        current_volume = 0
        total_chars = 0
        for ch in chapters:
            if ch.volume_no != current_volume:
                current_volume = ch.volume_no
                lines.append(f"## 第{current_volume}卷")
                lines.append("")
            lines.append(f"### 第{ch.chapter_no}章 {ch.title}")
            lines.append("")
            content = ch.content or ""
            lines.append(content)
            lines.append("")
            total_chars += len(content)

        file_path.write_text("\n".join(lines), encoding="utf-8")
        self.logger.info(f"Markdown 导出成功: {file_path}, 共 {total_chars} 字")
        return total_chars