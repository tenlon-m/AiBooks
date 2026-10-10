"""人物管理服务 - AI提取/生成配角、手动增删改、确认入库."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.config.settings import get_config
from src.api.schemas.character_schema import (
    CharacterDto,
    CharacterUpdateRequest,
)
from src.db.models import Character, StoryUnit
from src.utils.logger import get_logger


@dataclass
class MergeResult:
    """增量去重合并写入结果值对象."""
    added: list[CharacterDto] = field(default_factory=list)
    skipped: list[CharacterDto] = field(default_factory=list)

    @property
    def added_count(self) -> int:
        return len(self.added)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


import re

_NAME_SPLIT_RE = re.compile(r"[、，,；;／/]")

# AI 误把非人物（法宝、阵法、秘境、门派等）当人物时的兜底特征：
# identity 本身就是物品/地点/势力类描述（通常较短），且未注明器灵/化形。
# 只看 identity 不看 intro：真实人物的简介常提到"执掌法宝XX"，
# 看 intro 会把大量真人物误杀。
_NON_PERSON_RE = re.compile(r"(法宝|灵宝|至宝|神兵|兵器|武器|丹药|灵药|灵物|坐骑|阵法|杀阵|剑阵|大阵|秘境|洞府|遗迹|大陆|山峰|城池|宗门|门派|势力|王朝|古国|王朝古国)")
_PERSONIFIED_RE = re.compile(r"(器灵|化形|人格化|化身|转世)")


def _looks_like_object(c: dict) -> bool:
    """判断一条 AI 提取结果是否疑似非人物（法宝/地点/势力等）."""
    identity = (c.get("identity") or "").strip()
    if not identity or len(identity) > 12:
        # 身份描述过长时基本是人物介绍（如"截教大师兄，执掌法宝盘古幡"）
        return False
    return bool(_NON_PERSON_RE.search(identity)) and not _PERSONIFIED_RE.search(identity)


def _split_names(name: str) -> list[str]:
    return [p for p in _NAME_SPLIT_RE.split(name) if p]


def _split_ai_characters(chars_data: list[dict], source: str, log_tag: str = "") -> list[CharacterDto]:
    """解析 AI 返回的人物列表：过滤疑似非人物条目，并将 name 中并列的多人拆分.

    - AI 偶尔会把共用同一身份的多人合并成一条（如 name="有巢氏、燧人氏、缁衣氏"，
      identity="人族三祖"）。真实人名不含顿号/逗号等分隔符，据此在代码层兜底拆分。
    - AI 偶尔会把法宝/门派/地点等误提取为人物，按 identity/intro 中的物品类
      关键词兜底过滤（注明器灵/化形的除外）。
    """
    dtos: list[CharacterDto] = []
    for c in chars_data:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        if _looks_like_object(c):
            get_logger().info(
                f"过滤疑似非人物条目 [{log_tag or source}]: name={name!r} "
                f"identity={c.get('identity')!r}"
            )
            continue
        for part in _split_names(name):
            dtos.append(
                CharacterDto(
                    name=part,
                    identity=c.get("identity", ""),
                    intro=c.get("intro"),
                    relation=c.get("relation"),
                    source=source,
                    confirmed=False,
                )
            )
    return dtos


class CharacterService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    def _to_dto(self, ch: Character) -> CharacterDto:
        return CharacterDto(
            character_id=ch.character_id,
            project_id=ch.project_id,
            name=ch.name,
            identity=ch.identity,
            intro=ch.intro,
            relation=ch.relation,
            source=ch.source,
            confirmed=ch.confirmed,
            appearance_records=ch.appearance_records,
            supporting_type=ch.supporting_type,
            auto_gen_context=ch.auto_gen_context,
            future_reference=ch.future_reference,
            scope_type=ch.scope_type or "全书",
            scope_unit_id=ch.scope_unit_id,
        )

    async def ai_extract_main(self, project_id: str, synopsis: str, worldview: str) -> list[CharacterDto]:
        """AI 从梗概/世界观提取主角."""
        result = await self.gateway.call_and_parse(
            module="character",
            scene="extract-main",
            params={"synopsis": synopsis, "worldview": worldview},
            project_id=project_id,
            timeout_seconds=get_config().character_extract_timeout_seconds,
        )
        chars_data = result.get("parsed", {}).get("characters", [])
        return _split_ai_characters(chars_data, "ai_extract")


    async def ai_extract_supporting(self, project_id: str, synopsis: str, worldview: str, existing: list[CharacterDto]) -> list[CharacterDto]:
        """AI 从梗概/世界观提取配角."""
        result = await self.gateway.call_and_parse(
            module="character",
            scene="extract-supporting",
            params={
                "synopsis": synopsis,
                "worldview": worldview,
                "existing_characters": [c.model_dump() for c in existing],
            },
            project_id=project_id,
            timeout_seconds=get_config().character_extract_timeout_seconds,
        )
        chars_data = result.get("parsed", {}).get("characters", [])
        return _split_ai_characters(chars_data, "ai_extract")


    async def ai_generate_supporting(self, project_id: str, synopsis: str, worldview: str, existing: list[CharacterDto], count: int = 3) -> list[CharacterDto]:
        """AI 生成配角."""
        result = await self.gateway.call_and_parse(
            module="character",
            scene="generate-supporting",
            params={
                "synopsis": synopsis,
                "worldview": worldview,
                "existing_characters": [c.model_dump() for c in existing],
                "count": count,
            },
            project_id=project_id,
            timeout_seconds=get_config().character_extract_timeout_seconds,
        )
        chars_data = result.get("parsed", {}).get("characters", [])
        return _split_ai_characters(chars_data, "ai_generate")


    async def ai_import_from_file(self, project_id: str, file_path: str) -> list[CharacterDto]:
        """从设定文档识别人物及关系，返回解析结果（不写入数据库，写入由merge_characters统一处理）."""
        from src.services.import_service import ImportService

        import_service = ImportService()
        parsed = import_service.parse(file_path, "character")
        file_content = parsed.content

        existing = await self.list_by_project(project_id)

        result = await self.gateway.call_and_parse(
            module="character",
            scene="import-from-file",
            params={
                "file_content": file_content,
                "existing_characters": [c.model_dump() for c in existing],
            },
            project_id=project_id,
            timeout_seconds=get_config().character_extract_timeout_seconds,
        )
        chars_data = result.get("parsed", {}).get("characters", [])
        return _split_ai_characters(chars_data, "file_import")

    async def create(self, project_id: str, name: str, identity: str, intro: str | None, relation: str | None, source: str) -> CharacterDto:
        ch = Character(
            character_id=str(uuid.uuid4()),
            project_id=project_id,
            name=name,
            identity=identity,
            intro=intro,
            relation=relation,
            source=source,
            confirmed=False,
            scope_type="全书",
        )
        self.session.add(ch)
        await self.session.flush()
        return self._to_dto(ch)

    async def list_by_project(self, project_id: str) -> list[CharacterDto]:
        result = await self.session.execute(select(Character).where(Character.project_id == project_id))
        return [self._to_dto(c) for c in result.scalars().all()]

    async def list_confirmed(self, project_id: str) -> list[CharacterDto]:
        result = await self.session.execute(
            select(Character).where(Character.project_id == project_id, Character.confirmed == True)
        )
        return [self._to_dto(c) for c in result.scalars().all()]

    async def update(self, character_id: str, req: CharacterUpdateRequest) -> CharacterDto:
        ch = await self.session.get(Character, character_id)
        if not ch:
            raise ValueError(f"人物不存在: {character_id}")
        for field in ("name", "identity", "intro", "relation", "confirmed"):
            val = getattr(req, field)
            if val is not None:
                setattr(ch, field, val)
        await self.session.flush()
        return self._to_dto(ch)

    async def delete(self, character_id: str) -> bool:
        ch = await self.session.get(Character, character_id)
        if not ch:
            return False
        await self.session.delete(ch)
        await self.session.flush()
        return True

    async def confirm(self, character_id: str) -> CharacterDto:
        ch = await self.session.get(Character, character_id)
        if not ch:
            raise ValueError(f"人物不存在: {character_id}")
        ch.confirmed = True
        await self.session.flush()
        return self._to_dto(ch)

    async def batch_create(self, project_id: str, characters: list[CharacterDto]) -> list[CharacterDto]:
        """批量创建人物（AI提取后用户确认）."""
        result = []
        for c in characters:
            dto = await self.create(
                project_id=project_id,
                name=c.name,
                identity=c.identity,
                intro=c.intro,
                relation=c.relation,
                source=c.source,
            )
            result.append(dto)
        return result
    async def merge_characters(self, project_id: str, new_chars: list[CharacterDto]) -> MergeResult:
        """增量去重合并写入：按姓名比对已有人物，跳过同名，仅追加新人，UUID统一生成."""
        existing_result = await self.session.execute(
            select(Character).where(Character.project_id == project_id)
        )
        existing_names: dict[str, Character] = {
            ch.name: ch for ch in existing_result.scalars().all()
        }
        added: list[CharacterDto] = []
        skipped: list[CharacterDto] = []
        for char in new_chars:
            if not char.name or not char.name.strip():
                continue
            name = char.name.strip()
            if name in existing_names:
                skipped.append(char)
                continue
            dto = await self.create(
                project_id=project_id,
                name=name,
                identity=char.identity,
                intro=char.intro,
                relation=char.relation,
                source=char.source,
            )
            added.append(dto)
            existing_names[name] = Character(
                character_id=dto.character_id or "",
                project_id=project_id,
                name=name,
                identity=char.identity,
                intro=char.intro,
                relation=char.relation,
                source=char.source,
                confirmed=False,
            )
        await self.session.commit()
        return MergeResult(added=added, skipped=skipped)

    async def batch_delete(self, character_ids: list[str]) -> int:
        """批量删除人物，单事务原子性，返回实际删除数量."""
        deleted_count = 0
        for char_id in character_ids:
            ch = await self.session.get(Character, char_id)
            if ch:
                await self.session.delete(ch)
                deleted_count += 1
        await self.session.commit()
        return deleted_count

    async def batch_confirm(self, character_ids: list[str]) -> int:
        """批量确认人物，返回实际确认数量."""
        confirmed_count = 0
        for char_id in character_ids:
            ch = await self.session.get(Character, char_id)
            if ch and not ch.confirmed:
                ch.confirmed = True
                confirmed_count += 1
            elif ch and ch.confirmed:
                confirmed_count += 1
        await self.session.commit()
        return confirmed_count
    async def list_by_scope(
        self, project_id: str, scope_type: str, scope_unit_id: str | None
    ) -> list[CharacterDto]:
        """按作用域下钻查询可用角色：全书角色 + 父单元链上角色 + 本单元角色，合并去重."""
        if scope_type == "全书":
            return await self.list_confirmed(project_id)

        if not scope_unit_id:
            raise ValueError("非全书作用域必须指定作用域单元")

        unit = await self.session.get(StoryUnit, scope_unit_id)
        if not unit or unit.project_id != project_id:
            raise ValueError("作用域单元不存在")

        ancestor_ids: set[str] = {scope_unit_id}
        current = unit
        while current.parent_unit_id is not None:
            parent = await self.session.get(StoryUnit, current.parent_unit_id)
            if parent is None:
                break
            ancestor_ids.add(parent.story_unit_id)
            current = parent

        result = await self.session.execute(
            select(Character).where(
                Character.project_id == project_id,
                Character.confirmed == True,
            )
        )
        all_chars = list(result.scalars().all())

        seen: set[str] = set()
        available: list[CharacterDto] = []
        for ch in all_chars:
            if ch.character_id in seen:
                continue
            ch_scope = ch.scope_type or "全书"
            if ch_scope == "全书":
                seen.add(ch.character_id)
                available.append(self._to_dto(ch))
            elif ch.scope_unit_id is not None and ch.scope_unit_id in ancestor_ids:
                seen.add(ch.character_id)
                available.append(self._to_dto(ch))
        return available

    async def update_scope(
        self, character_id: str, scope_type: str, scope_unit_id: str | None
    ) -> CharacterDto:
        """更新作用域；主角不可设为单元级；非全书时 scope_unit_id 必须指向存在的 StoryUnit."""
        ch = await self.session.get(Character, character_id)
        if not ch:
            raise ValueError(f"人物不存在: {character_id}")

        if "主角" in (ch.identity or "") and scope_type != "全书":
            raise ValueError("主角必须全书可见，不可设为单元级作用域")

        if scope_type != "全书":
            if not scope_unit_id:
                raise ValueError("非全书作用域必须指定作用域单元")
            unit = await self.session.get(StoryUnit, scope_unit_id)
            if not unit or unit.project_id != ch.project_id:
                raise ValueError("作用域单元不存在")

        ch.scope_type = scope_type
        ch.scope_unit_id = scope_unit_id if scope_type != "全书" else None
        await self.session.flush()
        return self._to_dto(ch)

    async def check_name_unique(self, project_id: str, name: str) -> bool:
        """校验名字全书唯一性，返回 True 表示唯一可用."""
        result = await self.session.execute(
            select(Character).where(
                Character.project_id == project_id,
                Character.name == name,
            )
        )
        return result.scalars().first() is None