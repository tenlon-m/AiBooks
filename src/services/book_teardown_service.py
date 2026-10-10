"""一键拆书服务 - 本地文件解析、AI多级大纲拆解、要素提取、二创工程."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import AiGateway, get_gateway
from src.api.schemas.book_teardown_schema import (
    ParsedContentDto,
    TeardownElementsDto,
    TeardownOutlineDto,
)
from src.config.settings import get_config
from src.db.models import BookTeardown, Project, Synopsis, Worldview
from src.db.session import release_write_lock
from src.utils.logger import get_logger

BATCH_CHAR_LIMIT = 100000
SUPPORTED_FORMATS = ("txt", "pdf", "epub", "docx")


class BookTeardownService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway: AiGateway = get_gateway()
        self._last_teardown_id: str | None = None
        self._batch_count: int = 1

    async def upload_and_parse(self, file_path: str) -> ParsedContentDto:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        fmt = path.suffix.lower().lstrip(".")
        if fmt not in SUPPORTED_FORMATS:
            raise ValueError(f"不支持的文件格式: .{fmt}，仅支持 txt/pdf/epub/docx")
        content = await self._parse_file(path, fmt)

        teardown_id = str(uuid.uuid4())
        record = BookTeardown(
            teardown_id=teardown_id,
            source_file_path=str(path),
            file_format=fmt,
            multi_level_outline=content,
            teardown_status="已解析",
        )
        self.session.add(record)
        await self.session.flush()
        self._last_teardown_id = teardown_id
        self.logger.info(f"文件解析完成: {fmt}, {len(content)}字, teardown_id={teardown_id}")
        return ParsedContentDto(file_format=fmt, content=content, char_count=len(content))

    async def _parse_file(self, path: Path, fmt: str) -> str:
        if fmt == "txt":
            return await self._parse_txt(path)
        if fmt == "pdf":
            return await self._parse_pdf(path)
        if fmt == "epub":
            return await self._parse_epub(path)
        if fmt == "docx":
            return await self._parse_docx(path)
        raise ValueError(f"不支持的文件格式: .{fmt}")

    async def _parse_txt(self, path: Path) -> str:
        encoding = self._detect_encoding(path)
        with open(path, "r", encoding=encoding) as f:
            return f.read()

    async def _parse_pdf(self, path: Path) -> str:
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError("解析 PDF 需要安装 pdfplumber，请执行: pip install pdfplumber")
        parts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n".join(parts)

    async def _parse_epub(self, path: Path) -> str:
        try:
            import ebooklib
            from bs4 import BeautifulSoup
            from ebooklib import epub
        except ImportError:
            raise RuntimeError(
                "解析 EPUB 需要安装 ebooklib 和 beautifulsoup4，请执行: pip install ebooklib beautifulsoup4"
            )
        book = epub.read_epub(str(path))
        parts: list[str] = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            parts.append(soup.get_text())
        return "\n".join(parts)

    async def _parse_docx(self, path: Path) -> str:
        try:
            import docx
        except ImportError:
            raise RuntimeError("解析 DOCX 需要安装 python-docx，请执行: pip install python-docx")
        doc = docx.Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)

    def _detect_encoding(self, path: Path) -> str:
        for enc in ("utf-8", "gbk", "gb2312", "big5"):
            try:
                with open(path, "r", encoding=enc) as f:
                    f.read(1024)
                return enc
            except (UnicodeDecodeError, LookupError):
                continue
        return "utf-8"


    async def teardown_outline(self, teardown_id: str) -> TeardownOutlineDto:
        record = await self.session.get(BookTeardown, teardown_id)
        if record is None:
            raise ValueError(f"拆书记录不存在: {teardown_id}")
        content = record.multi_level_outline
        timeout = get_config().book_teardown_timeout_seconds
        await release_write_lock(self.session)
        if len(content) > BATCH_CHAR_LIMIT:
            outline = await self._batched_teardown_outline(content, timeout)
        else:
            result = await self.gateway.call_and_parse(
                module="analysis",
                scene="book-teardown",
                params={"parsed_content": content, "teardown_phase": "outline"},
                timeout_seconds=timeout,
            )
            parsed = result.get("parsed", {})
            outline = parsed.get("multi_level_outline", "")
        if not outline:
            raise ValueError("AI 未返回有效大纲，请重试")
        record.multi_level_outline = outline
        record.teardown_status = "已拆大纲"
        await self.session.flush()
        return TeardownOutlineDto(teardown_id=teardown_id, multi_level_outline=outline)

    async def _batched_teardown_outline(self, content: str, timeout: int) -> str:
        partials: list[str] = []
        for i in range(0, len(content), BATCH_CHAR_LIMIT):
            chunk = content[i : i + BATCH_CHAR_LIMIT]
            result = await self.gateway.call_and_parse(
                module="analysis",
                scene="book-teardown",
                params={"parsed_content": chunk, "teardown_phase": "outline"},
                timeout_seconds=timeout,
            )
            parsed = result.get("parsed", {})
            partials.append(parsed.get("multi_level_outline", ""))
        merge_result = await self.gateway.call_and_parse(
            module="analysis",
            scene="book-teardown",
            params={"parsed_content": "\n\n".join(partials), "teardown_phase": "outline"},
            timeout_seconds=timeout,
        )
        return merge_result.get("parsed", {}).get("multi_level_outline", "")

    async def extract_elements(self, teardown_id: str) -> TeardownElementsDto:
        record = await self.session.get(BookTeardown, teardown_id)
        if record is None:
            raise ValueError(f"拆书记录不存在: {teardown_id}")
        outline = record.multi_level_outline
        timeout = get_config().book_teardown_timeout_seconds
        await release_write_lock(self.session)
        result = await self.gateway.call_and_parse(
            module="analysis",
            scene="book-teardown",
            params={"parsed_content": outline, "teardown_phase": "elements"},
            timeout_seconds=timeout,
        )
        parsed = result.get("parsed", {})
        characters = parsed.get("characters")
        time_places = parsed.get("time_places")
        worldview = parsed.get("worldview")
        special_items = parsed.get("special_items")
        events = parsed.get("events")
        record.characters_extract = characters
        record.time_places = time_places
        record.worldview_setting = worldview
        record.special_items = special_items
        record.event_points = events
        record.teardown_status = "已提取要素"
        await self.session.flush()
        return TeardownElementsDto(
            teardown_id=teardown_id,
            characters=characters,
            time_places=time_places,
            worldview=worldview,
            special_items=special_items,
            events=events,
        )

    def _infer_project_params(self, outline: str) -> tuple[int, int]:
        volume_count = 0
        chapter_count = 0
        for line in outline.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if "卷" in stripped and "章" not in stripped:
                volume_count += 1
            elif "章" in stripped and "卷" not in stripped:
                chapter_count += 1
        if volume_count > 0 and chapter_count > 0:
            return volume_count, max(1, chapter_count // volume_count)
        if chapter_count > 0:
            return 1, chapter_count
        if volume_count > 0:
            return volume_count, 10
        return 1, 10

    async def create_project_from_teardown(self, teardown_id: str, book_title: str) -> dict[str, Any]:
        record = await self.session.get(BookTeardown, teardown_id)
        if record is None:
            raise ValueError(f"拆书记录不存在: {teardown_id}")
        project_id = str(uuid.uuid4())
        outline_content = record.multi_level_outline or ""
        volume_count, chapters_per_volume = self._infer_project_params(outline_content)
        project = Project(
            project_id=project_id,
            book_title=book_title,
            volume_count=volume_count,
            chapters_per_volume=chapters_per_volume,
            words_per_chapter=3000,
            status="draft",
        )
        self.session.add(project)
        await self.session.flush()
        synopsis_content = record.multi_level_outline or ""
        if synopsis_content:
            self.session.add(
                Synopsis(project_id=project_id, content=synopsis_content, source="book_teardown")
            )
        worldview_content = record.worldview_setting or ""
        if worldview_content:
            self.session.add(
                Worldview(project_id=project_id, content=worldview_content, source="book_teardown")
            )
        record.teardown_status = "已创建工程"
        await self.session.flush()
        self.logger.info(f"基于拆书结果创建工程: project_id={project_id}, book_title={book_title}")
        return {
            "project_id": project_id,
            "book_title": book_title,
            "teardown_id": teardown_id,
            "message": "已基于拆书结果创建新工程",
        }