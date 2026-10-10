"""排版模板服务 - 内置模板加载/自定义模板CRUD."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.layout_template_schema import (
    LayoutTemplateCreateRequest,
    LayoutTemplateDto,
    LayoutTemplateListResponse,
)
from src.db.models import LayoutTemplate
from src.config.settings import get_config
from src.utils.logger import get_logger


def _builtin_template_dir() -> Path:
    return get_config().templates_dir / "layout"


class LayoutTemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    async def list_templates(self, format: str | None = None) -> LayoutTemplateListResponse:
        """列出排版模板（含内置），可按格式过滤."""
        await self._ensure_builtin_loaded()
        stmt = select(LayoutTemplate)
        if format:
            stmt = stmt.where(LayoutTemplate.format == format)
        stmt = stmt.order_by(LayoutTemplate.is_builtin.desc(), LayoutTemplate.name)
        result = await self.session.execute(stmt)
        templates = [self._to_dto(t) for t in result.scalars().all()]
        return LayoutTemplateListResponse(templates=templates)

    async def get_template(self, template_id: str) -> LayoutTemplateDto:
        """获取单个排版模板."""
        await self._ensure_builtin_loaded()
        tpl = await self.session.get(LayoutTemplate, template_id)
        if not tpl:
            raise ValueError(f"排版模板不存在: {template_id}")
        return self._to_dto(tpl)

    async def create_template(self, req: LayoutTemplateCreateRequest) -> LayoutTemplateDto:
        """创建自定义排版模板."""
        entity = LayoutTemplate(
            template_id=str(uuid.uuid4()),
            name=req.name,
            format=req.format,
            font=req.font,
            font_size=req.font_size,
            line_spacing=req.line_spacing,
            title_style=req.title_style,
            first_indent=req.first_indent,
            header=req.header,
            footer=req.footer,
            is_builtin=False,
        )
        self.session.add(entity)
        await self.session.commit()
        return self._to_dto(entity)

    async def delete_template(self, template_id: str) -> None:
        """删除排版模板（内置不可删）."""
        tpl = await self.session.get(LayoutTemplate, template_id)
        if not tpl:
            raise ValueError(f"排版模板不存在: {template_id}")
        if tpl.is_builtin:
            raise ValueError("内置模板不可删除")
        await self.session.delete(tpl)
        await self.session.commit()

    async def get_template_dict(self, template_id: str | None) -> dict:
        """获取模板参数字典（供导出器使用）."""
        if not template_id:
            return {}
        await self._ensure_builtin_loaded()
        tpl = await self.session.get(LayoutTemplate, template_id)
        if not tpl:
            return {}
        return {
            "name": tpl.name,
            "font": tpl.font,
            "font_size": tpl.font_size,
            "line_spacing": tpl.line_spacing,
            "title_style": tpl.title_style,
            "first_indent": tpl.first_indent,
            "header": tpl.header,
            "footer": tpl.footer,
        }

    async def _ensure_builtin_loaded(self) -> None:
        """首次调用时从 JSON 文件加载内置模板."""
        result = await self.session.execute(
            select(LayoutTemplate).where(LayoutTemplate.is_builtin.is_(True)).limit(1)
        )
        if result.scalars().first():
            return

        if not _builtin_template_dir().exists():
            return

        for json_file in sorted(_builtin_template_dir().glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                formats = data.get("format", [])
                if isinstance(formats, str):
                    formats = [formats]
                for fmt in formats:
                    entity = LayoutTemplate(
                        template_id=f"builtin-{json_file.stem}-{fmt}",
                        name=data["name"],
                        format=fmt,
                        font=data.get("font"),
                        font_size=data.get("font_size"),
                        line_spacing=data.get("line_spacing"),
                        title_style=data.get("title_style"),
                        first_indent=data.get("first_indent"),
                        header=data.get("header"),
                        footer=data.get("footer"),
                        is_builtin=True,
                    )
                    self.session.add(entity)
            except Exception as e:
                self.logger.warning(f"加载内置排版模板失败 {json_file}: {e}")
        await self.session.commit()

    @staticmethod
    def _to_dto(tpl: LayoutTemplate) -> LayoutTemplateDto:
        return LayoutTemplateDto(
            template_id=tpl.template_id,
            name=tpl.name,
            format=tpl.format,
            font=tpl.font,
            font_size=tpl.font_size,
            line_spacing=tpl.line_spacing,
            title_style=tpl.title_style,
            first_indent=tpl.first_indent,
            header=tpl.header,
            footer=tpl.footer,
            is_builtin=tpl.is_builtin,
        )