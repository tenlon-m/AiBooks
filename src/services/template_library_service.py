"""写作模板/套路库服务 - 从JSON文件加载模板，不建表."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.template_library_schema import (
    TemplateLibraryApplyRequest,
    TemplateLibraryDetailResponse,
    TemplateLibraryListResponse,
    WorldviewTemplateApplyRequestDto,
    WorldviewTemplateDetailResponse,
    WorldviewTemplateDto,
    WorldviewTemplateListResponse,
    WritingTemplateDto,
    WritingTemplateStage,
    WritingTemplateCoolRhythm,
)
from src.db.models import Worldview
from src.config.settings import get_config
from src.utils.logger import get_logger


def _templates_dir() -> Path:
    return get_config().templates_dir / "writing_templates"


def _worldview_templates_dir() -> Path:
    return get_config().templates_dir / "worldview_templates"


class TemplateLibraryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    def _load_all_raw(self) -> list[dict]:
        if not _templates_dir().exists():
            return []
        result: list[dict] = []
        for fp in sorted(_templates_dir().glob("*.json")):
            try:
                with fp.open("r", encoding="utf-8") as f:
                    result.append(json.load(f))
            except Exception as e:
                self.logger.warning(f"加载写作模板失败 {fp}: {e}")
        return result

    def _to_dto(self, raw: dict) -> WritingTemplateDto:
        return WritingTemplateDto(
            name=raw.get("name", ""),
            novel_type=raw.get("novel_type", ""),
            stages=[
                WritingTemplateStage(
                    name=s.get("name", ""),
                    volume=s.get("volume", 0),
                    chapters=s.get("chapters", ""),
                    desc=s.get("desc", ""),
                )
                for s in raw.get("stages", [])
            ],
            cool_rhythm=[
                WritingTemplateCoolRhythm(
                    interval=c.get("interval", 0),
                    type=c.get("type", ""),
                    desc=c.get("desc", ""),
                )
                for c in raw.get("cool_rhythm", [])
            ],
            character_config=raw.get("character_config", {}),
            outline_skeleton=raw.get("outline_skeleton", {}),
            is_builtin=raw.get("is_builtin", True),
        )

    async def list_templates(self) -> TemplateLibraryListResponse:
        raws = self._load_all_raw()
        templates = [self._to_dto(r) for r in raws]
        return TemplateLibraryListResponse(templates=templates)

    async def get_template(self, novel_type: str) -> TemplateLibraryDetailResponse:
        raws = self._load_all_raw()
        for r in raws:
            if r.get("novel_type") == novel_type:
                return TemplateLibraryDetailResponse(template=self._to_dto(r))
        raise ValueError(f"未找到类型为 {novel_type} 的写作模板")

    async def apply_template(self, req: TemplateLibraryApplyRequest) -> dict:
        detail = await self.get_template(req.novel_type)
        template = detail.template
        skeleton = template.outline_skeleton
        return {
            "project_id": req.project_id,
            "novel_type": req.novel_type,
            "name": template.name,
            "stages": [s.model_dump() for s in template.stages],
            "cool_rhythm": [c.model_dump() for c in template.cool_rhythm],
            "character_config": template.character_config,
            "outline_skeleton": skeleton,
            "applied": True,
        }
    def _load_all_worldview_raw(self) -> list[dict]:
        if not _worldview_templates_dir().exists():
            return []
        result: list[dict] = []
        for fp in sorted(_worldview_templates_dir().glob("*.json")):
            try:
                with fp.open("r", encoding="utf-8") as f:
                    result.append(json.load(f))
            except Exception as e:
                self.logger.warning(f"加载世界观模板失败 {fp}: {e}")
        return result

    @staticmethod
    def _to_worldview_dto(raw: dict) -> WorldviewTemplateDto:
        return WorldviewTemplateDto(
            name=raw.get("name", ""),
            world_type=raw.get("world_type", ""),
            power_system=raw.get("power_system", ""),
            social_structure=raw.get("social_structure", ""),
            geography=raw.get("geography", ""),
            races=raw.get("races", []),
            core_rules=raw.get("core_rules", []),
            is_builtin=raw.get("is_builtin", True),
        )

    async def list_worldview_templates(self) -> WorldviewTemplateListResponse:
        raws = self._load_all_worldview_raw()
        templates = [self._to_worldview_dto(r) for r in raws]
        return WorldviewTemplateListResponse(templates=templates)

    async def get_worldview_template(self, world_type: str) -> WorldviewTemplateDetailResponse:
        raws = self._load_all_worldview_raw()
        for r in raws:
            if r.get("world_type") == world_type:
                return WorldviewTemplateDetailResponse(template=self._to_worldview_dto(r))
        raise ValueError(f"未找到类型为 {world_type} 的世界观模板")

    async def apply_worldview_template(self, req: WorldviewTemplateApplyRequestDto) -> dict:
        detail = await self.get_worldview_template(req.world_type)
        template = detail.template
        content_parts = [
            f"# {template.name}",
            f"\n## 力量体系\n{template.power_system}",
            f"\n## 社会结构\n{template.social_structure}",
            f"\n## 地理设定\n{template.geography}",
            f"\n## 种族\n{', '.join(template.races)}",
            "\n## 核心规则",
        ]
        for rule in template.core_rules:
            content_parts.append(f"- {rule}")
        content = "\n".join(content_parts)

        existing = await self.session.get(Worldview, req.project_id)
        if existing:
            existing.content = content
            existing.source = "worldview_template"
        else:
            entity = Worldview(
                project_id=req.project_id,
                content=content,
                source="worldview_template",
            )
            self.session.add(entity)
        await self.session.commit()
        return {
            "project_id": req.project_id,
            "world_type": req.world_type,
            "name": template.name,
            "applied": True,
        }