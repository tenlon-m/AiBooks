"""EPUB 导出器 - 使用 EbookLib 生成电子书."""
from __future__ import annotations

from pathlib import Path

from ebooklib import epub

from src.utils.logger import get_logger


class EpubExporter:
    """按排版模板与导出选项生成 EPUB 文件."""

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
        font = template.get("font") or "SimHei"
        font_size = template.get("font_size") or 14
        line_spacing = template.get("line_spacing") or 1.5
        title_style = template.get("title_style") or "bold_center"
        first_indent = template.get("first_indent", True)

        book = epub.EpubBook()
        book.set_identifier(f"aibooks-{book_title}")
        book.set_title(book_title)
        book.set_language("zh-CN")

        title_align = "center" if "center" in title_style else "left"
        indent_css = "text-indent: 2em;" if first_indent else ""
        css_content = (
            f"body {{ font-family: '{font}'; font-size: {font_size}pt; "
            f"line-height: {line_spacing}; }}\n"
            f"p {{ {indent_css} margin: 0; }}\n"
            f"h1 {{ text-align: {title_align}; }}\n"
            f"h2 {{ text-align: {title_align}; }}\n"
        )
        css_item = epub.EpubItem(
            uid="style",
            file_name="style/default.css",
            media_type="text/css",
            content=css_content.encode("utf-8"),
        )
        book.add_item(css_item)

        spine_items: list[epub.EpubHtml] = []
        total_chars = 0

        if options.get("cover_page", True):
            cover_html = (
                f"<html><head><link rel='stylesheet' href='style/default.css'/></head>"
                f"<body><h1>{book_title}</h1></body></html>"
            )
            cover_item = epub.EpubHtml(title="封面", file_name="cover.xhtml", content=cover_html)
            cover_item.add_item(css_item)
            book.add_item(cover_item)
            spine_items.append(cover_item)

        if options.get("include_outline", False) and outline_text:
            outline_html = self._build_section_html("大纲", outline_text, css_item)
            book.add_item(outline_html)
            spine_items.append(outline_html)

        if options.get("include_characters", False) and characters_text:
            char_html = self._build_section_html("角色设定", characters_text, css_item)
            book.add_item(char_html)
            spine_items.append(char_html)

        current_volume = 0
        ch_index = 0
        for ch in chapters:
            ch_index += 1
            parts: list[str] = []
            if ch.volume_no != current_volume:
                current_volume = ch.volume_no
                parts.append(f"<h1>第{current_volume}卷</h1>")

            parts.append(f"<h2>第{ch.chapter_no}章 {ch.title}</h2>")
            content = ch.content or ""
            for para in content.split("\n"):
                parts.append(f"<p>{para}</p>")
            total_chars += len(content)

            chapter_html = (
                f"<html><head><link rel='stylesheet' href='style/default.css'/></head>"
                f"<body>{''.join(parts)}</body></html>"
            )
            ch_item = epub.EpubHtml(
                title=f"第{ch.chapter_no}章 {ch.title}",
                file_name=f"chapter_{ch_index}.xhtml",
                content=chapter_html,
            )
            ch_item.add_item(css_item)
            book.add_item(ch_item)
            spine_items.append(ch_item)

        book.toc = tuple(spine_items)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav"] + spine_items

        epub.write_epub(str(file_path), book, {})
        self.logger.info(f"EPUB 导出成功: {file_path}, 共 {total_chars} 字")
        return total_chars

    @staticmethod
    def _build_section_html(title: str, text: str, css_item) -> epub.EpubHtml:
        paras = "".join(f"<p>{p}</p>" for p in text.split("\n"))
        html = (
            f"<html><head><link rel='stylesheet' href='style/default.css'/></head>"
            f"<body><h1>{title}</h1>{paras}</body></html>"
        )
        item = epub.EpubHtml(title=title, file_name=f"{title}.xhtml", content=html)
        item.add_item(css_item)
        return item