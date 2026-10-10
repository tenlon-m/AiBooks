"""PDF 导出器 - 使用 reportlab 生成 PDF 文档."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from src.utils.logger import get_logger


class PdfExporter:
    """按排版模板与导出选项生成 PDF 文件."""

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
        font_name = template.get("font") or "SimHei"
        font_size = template.get("font_size") or 14
        line_spacing = template.get("line_spacing") or 1.5
        title_style = template.get("title_style") or "bold_center"
        first_indent = template.get("first_indent", True)
        header_tpl = template.get("header") or ""
        footer_tpl = template.get("footer") or ""

        registered_font = self._register_font(font_name)
        title_align = TA_CENTER if "center" in title_style else TA_LEFT

        heading_style = ParagraphStyle(
            name="Heading", fontName=registered_font, fontSize=28,
            leading=36, alignment=TA_CENTER, spaceAfter=12,
        )
        volume_style = ParagraphStyle(
            name="Volume", fontName=registered_font, fontSize=font_size + 2,
            leading=(font_size + 2) * line_spacing, alignment=title_align, spaceAfter=8,
        )
        chapter_style = ParagraphStyle(
            name="Chapter", fontName=registered_font, fontSize=font_size + 1,
            leading=(font_size + 1) * line_spacing, alignment=title_align, spaceAfter=6,
        )
        body_style = ParagraphStyle(
            name="Body", fontName=registered_font, fontSize=font_size,
            leading=font_size * line_spacing, alignment=TA_LEFT,
            firstLineIndent=font_size * 2 if first_indent else 0, spaceAfter=2,
        )

        doc = SimpleDocTemplate(
            str(file_path), pagesize=A4,
            leftMargin=2 * cm, rightMargin=2 * cm,
            topMargin=2 * cm, bottomMargin=2 * cm,
        )

        story = []
        total_chars = 0

        if options.get("cover_page", True):
            story.append(Paragraph(self._escape(book_title), heading_style))
            story.append(PageBreak())

        if options.get("include_outline", False) and outline_text:
            story.append(Paragraph("大纲", volume_style))
            story.append(Spacer(1, 6))
            for para in outline_text.split("\n"):
                if para.strip():
                    story.append(Paragraph(self._escape(para), body_style))
            story.append(PageBreak())

        if options.get("include_characters", False) and characters_text:
            story.append(Paragraph("角色设定", volume_style))
            story.append(Spacer(1, 6))
            for para in characters_text.split("\n"):
                if para.strip():
                    story.append(Paragraph(self._escape(para), body_style))
            story.append(PageBreak())

        current_volume = 0
        first_chapter = True
        for ch in chapters:
            if options.get("chapter_pagination", True) and not first_chapter:
                story.append(PageBreak())
            first_chapter = False

            if ch.volume_no != current_volume:
                current_volume = ch.volume_no
                story.append(Paragraph(f"第{current_volume}卷", volume_style))
                story.append(Spacer(1, 4))

            story.append(Paragraph(self._escape(f"第{ch.chapter_no}章 {ch.title}"), chapter_style))
            story.append(Spacer(1, 4))

            content = ch.content or ""
            for para in content.split("\n"):
                if para.strip():
                    story.append(Paragraph(self._escape(para), body_style))
                else:
                    story.append(Spacer(1, 2))
            total_chars += len(content)

        doc.build(
            story,
            onFirstPage=lambda c, d: self._draw_header_footer(
                c, d, header_tpl, footer_tpl, book_title, registered_font
            ),
            onLaterPages=lambda c, d: self._draw_header_footer(
                c, d, header_tpl, footer_tpl, book_title, registered_font
            ),
        )
        self.logger.info(f"PDF 导出成功: {file_path}, 共 {total_chars} 字")
        return total_chars

    @staticmethod
    def _register_font(font_name: str) -> str:
        """注册中文字体，返回可用的字体名."""
        candidates = {
            "SimSun": [
                ("simsun", "C:/Windows/Fonts/simsun.ttc", 0),
                ("simsun", "C:/Windows/Fonts/simsun.ttf", None),
            ],
            "SimHei": [("simhei", "C:/Windows/Fonts/simhei.ttf", None)],
            "Microsoft YaHei": [
                ("msyh", "C:/Windows/Fonts/msyh.ttc", 0),
                ("msyh", "C:/Windows/Fonts/msyh.ttf", None),
            ],
        }
        for registered_name, font_path, subfont_index in candidates.get(font_name, []):
            try:
                if subfont_index is not None:
                    pdfmetrics.registerFont(
                        TTFont(registered_name, font_path, subfontIndex=subfont_index)
                    )
                else:
                    pdfmetrics.registerFont(TTFont(registered_name, font_path))
                return registered_name
            except Exception:
                continue
        return "Helvetica"

    @staticmethod
    def _draw_header_footer(canvas, doc, header_tpl: str, footer_tpl: str, book_title: str, font: str) -> None:
        canvas.saveState()
        if header_tpl:
            header_text = header_tpl.replace("{book_title}", book_title)
            canvas.setFont(font, 9)
            canvas.drawString(doc.leftMargin, A4[1] - 1.2 * cm, header_text)
        if footer_tpl:
            footer_text = footer_tpl.replace("{book_title}", book_title)
            footer_text = footer_text.replace("{page_number}", str(canvas.getPageNumber()))
            canvas.setFont(font, 9)
            canvas.drawCentredString(A4[0] / 2, 1 * cm, footer_text)
        canvas.restoreState()

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")