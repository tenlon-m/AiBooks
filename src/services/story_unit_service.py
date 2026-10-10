"""故事单元服务 - 雪花式5级分层大纲逐层生成/级联标记/树查询/更新."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.story_unit_schema import (
    StoryUnitDto,
    StoryUnitTreeDto,
    StoryUnitUpdateRequest,
)
from src.config.settings import get_config
from src.db.models import (
    ChapterOutline,
    Character,
    Project,
    StoryUnit,
    Synopsis,
    Worldview,
)
from src.db.session import release_write_lock
from src.utils.logger import get_logger

_LEVEL_ORDER = {"volume": 0, "major": 1, "middle": 2, "minor": 3}

_CHILD_LEVEL = {"volume": "major", "major": "middle", "middle": "minor"}

_CHAPTER_RANGE = {
    "major": (21, 100),
    "middle": (5, 20),
    "minor": (2, 4),
}

_LEVEL_LABEL = {
    "volume": "分卷",
    "major": "大篇",
    "middle": "中篇",
    "minor": "小篇",
}


class StoryUnitService:
    """故事单元服务 - 雪花式分层大纲."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def generate_volume_layer(self, project_id: str) -> list[StoryUnitDto]:
        """生成分卷层（最高层）."""
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")

        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        if not synopsis or not synopsis.content.strip():
            raise ValueError("请先输入故事梗概")
        if not worldview or not worldview.content.strip():
            raise ValueError("请先输入世界观")

        chars_result = await self.session.execute(
            select(Character).where(
                Character.project_id == project_id,
                Character.confirmed == True,
            )
        )
        characters = list(chars_result.scalars().all())
        if not characters:
            raise ValueError("请先确认人物清单")

        existing_result = await self.session.execute(
            select(StoryUnit).where(
                StoryUnit.project_id == project_id,
                StoryUnit.level_type == "volume",
            )
        )
        if existing_result.scalars().first():
            raise ValueError("分卷层已生成，如需重新生成请先清空")

        await release_write_lock(self.session)

        params = {
            "synopsis": synopsis.content,
            "worldview": worldview.content,
            "characters": [
                {"name": c.name, "identity": c.identity, "intro": c.intro or ""}
                for c in characters
            ],
            "parent_unit": None,
            "level_type": "volume",
            "narrative_duty": "",
            "chapter_range": "",
        }

        result = await self.gateway.call_and_parse(
            module="outline",
            scene="generate-story-unit",
            params=params,
            project_id=project_id,
            max_tokens=4096,
        )
        parsed = result.get("parsed", {})
        units_data = parsed.get("units", [])
        if not units_data:
            raise ValueError("AI未返回有效的分卷数据")

        dtos: list[StoryUnitDto] = []
        for idx, u in enumerate(units_data, start=1):
            unit = StoryUnit(
                story_unit_id=str(uuid.uuid4()),
                project_id=project_id,
                parent_unit_id=None,
                level_type="volume",
                unit_no=idx,
                unit_name=u.get("unit_name", f"第{idx}卷"),
                synopsis=u.get("synopsis", ""),
                chapter_count=int(u.get("chapter_count", 0) or 0),
                gen_status="已生成",
                narrative_duty=u.get("narrative_duty", ""),
                cascade_dirty=False,
            )
            self.session.add(unit)
            dtos.append(self._to_dto(unit))

        await self.session.commit()
        return dtos

    async def generate_layer(
        self, project_id: str, parent_unit_id: str, level_type: str
    ) -> list[StoryUnitDto]:
        """逐层细化生成."""
        if level_type not in _CHILD_LEVEL.values():
            raise ValueError(f"不支持的层级类型: {level_type}")

        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")

        parent = await self.session.get(StoryUnit, parent_unit_id)
        if not parent or parent.project_id != project_id:
            raise ValueError("父单元不存在")
        if parent.gen_status != "已生成":
            raise ValueError("上层尚未生成，请先生成上层单元")

        expected_child = _CHILD_LEVEL.get(parent.level_type)
        if expected_child != level_type:
            raise ValueError(
                f"层级不匹配：父单元为{_LEVEL_LABEL.get(parent.level_type, parent.level_type)}，"
                f"应生成{_LEVEL_LABEL.get(expected_child or '', expected_child or '')}层"
            )

        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        if not synopsis or not worldview.content.strip():
            raise ValueError("故事梗概或世界观未设定")

        chars_result = await self.session.execute(
            select(Character).where(
                Character.project_id == project_id,
                Character.confirmed == True,
            )
        )
        characters = list(chars_result.scalars().all())

        existing_result = await self.session.execute(
            select(StoryUnit).where(
                StoryUnit.parent_unit_id == parent_unit_id,
                StoryUnit.level_type == level_type,
            )
        )
        if existing_result.scalars().first():
            raise ValueError(
                f"{_LEVEL_LABEL.get(level_type, level_type)}层已生成，如需重新生成请先清空"
            )

        await release_write_lock(self.session)

        lo, hi = _CHAPTER_RANGE[level_type]
        chapter_range = f"{lo}-{hi}"

        params = {
            "synopsis": synopsis.content,
            "worldview": worldview.content,
            "characters": [
                {"name": c.name, "identity": c.identity, "intro": c.intro or ""}
                for c in characters
            ],
            "parent_unit": {
                "unit_name": parent.unit_name,
                "synopsis": parent.synopsis,
                "narrative_duty": parent.narrative_duty,
                "chapter_count": parent.chapter_count,
            },
            "level_type": level_type,
            "narrative_duty": parent.narrative_duty,
            "chapter_range": chapter_range,
        }

        parsed = await self._call_ai_with_retry(params, project_id, level_type)
        units_data = parsed.get("units", [])
        if not units_data:
            raise ValueError("AI未返回有效的分层数据")

        dtos: list[StoryUnitDto] = []
        for idx, u in enumerate(units_data, start=1):
            unit = StoryUnit(
                story_unit_id=str(uuid.uuid4()),
                project_id=project_id,
                parent_unit_id=parent_unit_id,
                level_type=level_type,
                unit_no=idx,
                unit_name=u.get("unit_name", f"{_LEVEL_LABEL.get(level_type, '')}{idx}"),
                synopsis=u.get("synopsis", ""),
                chapter_count=int(u.get("chapter_count", 0) or 0),
                gen_status="已生成",
                narrative_duty=u.get("narrative_duty", ""),
                cascade_dirty=False,
            )
            self.session.add(unit)
            dtos.append(self._to_dto(unit))

        await self.session.commit()
        return dtos

    async def _call_ai_with_retry(
        self,
        params: dict,
        project_id: str,
        level_type: str,
    ) -> dict:
        """调用AI生成分层，章数超区间时提示词约束重试一次."""
        lo, hi = _CHAPTER_RANGE[level_type]
        result = await self.gateway.call_and_parse(
            module="outline",
            scene="generate-story-unit",
            params=params,
            project_id=project_id,
            max_tokens=4096,
        )
        parsed = result.get("parsed", {})
        units_data = parsed.get("units", [])

        out_of_range = any(
            not (lo <= int(u.get("chapter_count", 0) or 0) <= hi)
            for u in units_data
        )
        if out_of_range:
            self.logger.warning(
                f"{_LEVEL_LABEL.get(level_type, level_type)}层章数超出区间[{lo},{hi}]，"
                "提示词约束重试一次"
            )
            retry_params = dict(params)
            retry_params["chapter_range"] = f"{lo}-{hi}（严格约束，每单元章数必须在此区间内）"
            retry_result = await self.gateway.call_and_parse(
                module="outline",
                scene="generate-story-unit",
                params=retry_params,
                project_id=project_id,
                max_tokens=4096,
            )
            retry_parsed = retry_result.get("parsed", {})
            retry_units = retry_parsed.get("units", [])
            if retry_units:
                still_out = any(
                    not (lo <= int(u.get("chapter_count", 0) or 0) <= hi)
                    for u in retry_units
                )
                if not still_out:
                    return retry_parsed
                self.logger.warning(
                    f"{_LEVEL_LABEL.get(level_type, level_type)}层重试后章数仍超区间，使用重试结果"
                )
                return retry_parsed
            return parsed
        return parsed

    async def cascade_mark(self, unit_id: str) -> int:
        """级联标记该单元所有下层 gen_status='待重新生成'，递归向下."""
        unit = await self.session.get(StoryUnit, unit_id)
        if not unit:
            raise ValueError("单元不存在")

        count = 0
        count += await self._cascade_mark_recursive(unit_id)
        unit.cascade_dirty = True
        await self.session.commit()
        return count

    async def _cascade_mark_recursive(self, parent_unit_id: str) -> int:
        """递归标记子单元与关联章纲."""
        count = 0
        child_result = await self.session.execute(
            select(StoryUnit).where(StoryUnit.parent_unit_id == parent_unit_id)
        )
        for child in child_result.scalars().all():
            child.gen_status = "待重新生成"
            child.cascade_dirty = True
            count += 1
            count += await self._cascade_mark_recursive(child.story_unit_id)

        ch_result = await self.session.execute(
            select(ChapterOutline).where(ChapterOutline.story_unit_id == parent_unit_id)
        )
        for ch_outline in ch_result.scalars().all():
            ch_outline.gen_source = "待重新生成"
            count += 1

        return count

    async def list_tree(self, project_id: str) -> StoryUnitTreeDto:
        """返回完整树，无数据时返回空树（退化两级模式）."""
        result = await self.session.execute(
            select(StoryUnit)
            .where(StoryUnit.project_id == project_id)
            .order_by(StoryUnit.level_type, StoryUnit.unit_no)
        )
        units = list(result.scalars().all())
        dtos = [self._to_dto(u) for u in units]
        return StoryUnitTreeDto(project_id=project_id, units=dtos)

    async def get_unit(self, unit_id: str) -> StoryUnitDto | None:
        """获取单个单元."""
        unit = await self.session.get(StoryUnit, unit_id)
        if not unit:
            return None
        return self._to_dto(unit)

    async def update_unit(
        self, unit_id: str, req: StoryUnitUpdateRequest
    ) -> StoryUnitDto:
        """更新单元，若 synopsis/narrative_duty 变更则触发级联标记."""
        unit = await self.session.get(StoryUnit, unit_id)
        if not unit:
            raise ValueError("单元不存在")

        synopsis_changed = False
        duty_changed = False

        if req.unit_name is not None:
            unit.unit_name = req.unit_name
        if req.synopsis is not None and req.synopsis != unit.synopsis:
            unit.synopsis = req.synopsis
            synopsis_changed = True
        if req.narrative_duty is not None and req.narrative_duty != unit.narrative_duty:
            unit.narrative_duty = req.narrative_duty
            duty_changed = True

        cascade_count = 0
        if synopsis_changed or duty_changed:
            cascade_count = await self._cascade_mark_recursive(unit_id)
            unit.cascade_dirty = True

        await self.session.commit()

        dto = self._to_dto(unit)
        if cascade_count > 0:
            self.logger.info(
                f"单元{unit_id}概要/职责变更，已级联标记{cascade_count}个下层单元待重新生成"
            )
        return dto

    @staticmethod
    def _to_dto(unit: StoryUnit) -> StoryUnitDto:
        return StoryUnitDto(
            story_unit_id=unit.story_unit_id,
            project_id=unit.project_id,
            parent_unit_id=unit.parent_unit_id,
            level_type=unit.level_type,
            unit_no=unit.unit_no,
            unit_name=unit.unit_name,
            synopsis=unit.synopsis,
            chapter_count=unit.chapter_count,
            gen_status=unit.gen_status,
            narrative_duty=unit.narrative_duty,
            cascade_dirty=unit.cascade_dirty,
            created_at=unit.created_at,
        )