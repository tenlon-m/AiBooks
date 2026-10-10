"""小说导出服务 - TXT/DOCX/EPUB/Markdown/PDF 多格式导出."""
from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.export_schema import ExportOptions, ExportResponse
from src.config.settings import get_config
from src.db.models import (
    Chapter,
    Character,
    ChapterOutline,
    Outline,
    Project,
    VolumeOutline,
)
from src.services.exporters import (
    DocxExporter,
    EpubExporter,
    MarkdownExporter,
    PdfExporter,
)
from src.services.layout_template_service import LayoutTemplateService
from src.utils.logger import get_logger

_MAX_PATH_DEPTH = 12

_EXT_MAP = {
    "docx": ".docx",
    "epub": ".epub",
    "markdown": ".md",
    "pdf": ".pdf",
}

_EXPORTER_MAP = {
    "docx": DocxExporter,
    "epub": EpubExporter,
    "markdown": MarkdownExporter,
    "pdf": PdfExporter,
}


class ExportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    async def export_to_txt(self, project_id: str, target_dir: str) -> ExportResponse:
        """导出全书为 书名.txt（UTF-8）."""
        project = await self._get_completed_project(project_id)
        chapters = await self._get_chapters(project_id)

        lines: list[str] = []
        lines.append(project.book_title)
        lines.append("")
        lines.append("=" * 50)
        lines.append("")

        current_volume = 0
        total_chars = 0
        for ch in chapters:
            if ch.volume_no != current_volume:
                current_volume = ch.volume_no
                lines.append("")
                lines.append(f"第{current_volume}卷")
                lines.append("-" * 30)
                lines.append("")
            lines.append(f"第{ch.chapter_no}章 {ch.title}")
            lines.append("")
            lines.append(ch.content or "")
            lines.append("")
            total_chars += len(ch.content or "")

        content = "\n".join(lines)
        target_path = self._validate_target_dir(target_dir)
        file_path = target_path / f"{project.book_title}.txt"

        def _write() -> int:
            file_path.write_text(content, encoding="utf-8")
            return total_chars

        chars = await self._run_with_timeout(_write)
        self.logger.info(f"导出成功: {file_path}, 共 {chars} 字")
        return ExportResponse(file_path=str(file_path), char_count=chars)

    async def export_to_docx(
        self,
        project_id: str,
        target_dir: str,
        template_id: str | None = None,
        options: ExportOptions | None = None,
    ) -> ExportResponse:
        """导出为 DOCX."""
        return await self._export_multi_format(
            "docx", project_id, target_dir, template_id, options or ExportOptions()
        )

    async def export_to_epub(
        self,
        project_id: str,
        target_dir: str,
        template_id: str | None = None,
        options: ExportOptions | None = None,
    ) -> ExportResponse:
        """导出为 EPUB."""
        return await self._export_multi_format(
            "epub", project_id, target_dir, template_id, options or ExportOptions()
        )

    async def export_to_markdown(
        self,
        project_id: str,
        target_dir: str,
        template_id: str | None = None,
        options: ExportOptions | None = None,
    ) -> ExportResponse:
        """导出为 Markdown."""
        return await self._export_multi_format(
            "markdown", project_id, target_dir, template_id, options or ExportOptions()
        )

    async def export_to_pdf(
        self,
        project_id: str,
        target_dir: str,
        template_id: str | None = None,
        options: ExportOptions | None = None,
    ) -> ExportResponse:
        """导出为 PDF."""
        return await self._export_multi_format(
            "pdf", project_id, target_dir, template_id, options or ExportOptions()
        )

    async def _export_multi_format(
        self,
        fmt: str,
        project_id: str,
        target_dir: str,
        template_id: str | None,
        options: ExportOptions,
    ) -> ExportResponse:
        project = await self._get_completed_project(project_id)
        chapters = await self._get_chapters(project_id)
        template = await self._get_template_dict(template_id)

        outline_text = ""
        if options.include_outline:
            outline_text = await self._get_outline_text(project_id)
        characters_text = ""
        if options.include_characters:
            characters_text = await self._get_characters_text(project_id)

        target_path = self._validate_target_dir(target_dir)
        file_path = target_path / f"{project.book_title}{_EXT_MAP[fmt]}"

        exporter = _EXPORTER_MAP[fmt]()
        opts_dict = options.model_dump()

        def _do_export() -> int:
            return exporter.export(
                book_title=project.book_title,
                chapters=chapters,
                template=template,
                options=opts_dict,
                file_path=file_path,
                outline_text=outline_text,
                characters_text=characters_text,
            )

        total_chars = await self._run_with_timeout(_do_export)
        self.logger.info(f"导出成功: {file_path}, 共 {total_chars} 字")
        return ExportResponse(file_path=str(file_path), char_count=total_chars)

    async def _get_completed_project(self, project_id: str) -> Project:
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        if project.status != "completed":
            raise ValueError("项目撰写未完成，暂不能导出")
        return project

    async def _get_chapters(self, project_id: str) -> list[Chapter]:
        result = await self.session.execute(
            select(Chapter).where(Chapter.project_id == project_id).order_by(
                Chapter.volume_no, Chapter.chapter_no
            )
        )
        chapters = list(result.scalars().all())
        if not chapters:
            raise ValueError("项目尚未开始撰写")
        incomplete = [c for c in chapters if c.gen_status != "completed" or not c.content]
        if incomplete:
            raise ValueError(f"存在未完成章节: {len(incomplete)} 章")
        return chapters

    async def _get_template_dict(self, template_id: str | None) -> dict:
        if not template_id:
            return {}
        service = LayoutTemplateService(self.session)
        return await service.get_template_dict(template_id)

    async def _get_outline_text(self, project_id: str) -> str:
        result = await self.session.execute(
            select(Outline).where(Outline.project_id == project_id)
        )
        outline = result.scalars().first()
        if not outline:
            return ""
        lines: list[str] = []
        vol_result = await self.session.execute(
            select(VolumeOutline)
            .where(VolumeOutline.outline_id == outline.outline_id)
            .order_by(VolumeOutline.volume_no)
        )
        for vol in vol_result.scalars().all():
            lines.append(f"第{vol.volume_no}卷 {vol.volume_name}")
            ch_result = await self.session.execute(
                select(ChapterOutline)
                .where(ChapterOutline.volume_outline_id == vol.volume_outline_id)
                .order_by(ChapterOutline.chapter_no)
            )
            for ch in ch_result.scalars().all():
                lines.append(f"  第{ch.chapter_no}章 {ch.chapter_name}")
                lines.append(f"    {ch.synopsis_points}")
        return "\n".join(lines)

    async def _get_characters_text(self, project_id: str) -> str:
        result = await self.session.execute(
            select(Character)
            .where(
                Character.project_id == project_id,
                Character.confirmed.is_(True),
            )
            .order_by(Character.created_at)
        )
        lines: list[str] = []
        for c in result.scalars().all():
            lines.append(f"【{c.name}】{c.identity}")
            if c.intro:
                lines.append(c.intro)
            if c.relation:
                lines.append(f"关系：{c.relation}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _validate_target_dir(target_dir: str) -> Path:
        """校验目标路径合法性（防目录穿越攻击）."""
        raw = Path(target_dir)
        if ".." in raw.parts:
            raise ValueError("目标路径包含非法的目录穿越符")
        if len(raw.parts) > _MAX_PATH_DEPTH:
            raise ValueError("目标路径层级过深")
        raw.mkdir(parents=True, exist_ok=True)
        return raw

    @staticmethod
    async def _run_with_timeout(func) -> int:
        """在线程中执行同步导出，带超时控制."""
        timeout = get_config().export_timeout_seconds
        return await asyncio.wait_for(asyncio.to_thread(func), timeout=timeout)
