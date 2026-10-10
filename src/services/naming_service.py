"""命名生成器服务."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.naming_schema import (
    NamingCandidate,
    NamingFavoriteDto,
    NamingGenerateResponse,
    NamingStreamChunk,
)
from src.config.settings import get_config
from src.db.models import Character, Item, NameFavorite, Synopsis, Worldview
from src.db.session import release_write_lock
from src.utils.logger import get_logger


# 命名类型 → 提示词展示标签（人物类不进创作链路，人物必须来自已确认清单）
NAME_TYPE_LABELS = {
    "character": "人物",
    "location": "地点",
    "place": "地点",
    "item": "物品/法宝",
    "faction": "势力/门派",
    "sect": "门派",
    "skill": "功法/技能",
}


class NamingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def _load_existing_names(self, project_id: str, name_type: str) -> list[str]:
        result = await self.session.execute(
            select(NameFavorite).where(
                NameFavorite.project_id == project_id,
                NameFavorite.name_type == name_type,
            )
        )
        return [f.value for f in result.scalars().all()]

    async def generate(
        self,
        project_id: str,
        name_type: str,
        count: int = 10,
        context: str = "",
        user_ideas: str = "",
    ) -> NamingGenerateResponse:
        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        existing = await self._load_existing_names(project_id, name_type)
        await release_write_lock(self.session)

        result = await self.gateway.call_and_parse(
            module="naming",
            scene="generate",
            params={
                "name_type": name_type,
                "count": count,
                "worldview": worldview.content if worldview else "",
                "synopsis": synopsis.content if synopsis else "",
                "context": context,
                "existing_names": existing,
                "user_ideas": user_ideas,
            },
            project_id=project_id,
            timeout_seconds=get_config().naming_generate_timeout_seconds,
        )
        parsed = result.get("parsed", {})
        names = [
            NamingCandidate(
                value=n.get("value", ""),
                reason=n.get("reason", ""),
            )
            for n in parsed.get("names", [])
            if n.get("value", "")
        ]
        if not names:
            raise ValueError("AI未生成有效命名")

        return NamingGenerateResponse(names=names)

    async def stream_generate(
        self,
        project_id: str,
        name_type: str,
        count: int = 10,
        context: str = "",
        user_ideas: str = "",
    ) -> AsyncGenerator[NamingStreamChunk, None]:
        yield NamingStreamChunk(type="progress", message="正在生成命名候选...")
        try:
            response = await self.generate(project_id, name_type, count, context, user_ideas)
        except ValueError as e:
            yield NamingStreamChunk(type="done", message=f"失败: {e}")
            return
        except Exception as e:
            yield NamingStreamChunk(type="done", message=f"AI调用异常: {e}")
            return

        total = len(response.names)
        for i, cand in enumerate(response.names, start=1):
            yield NamingStreamChunk(
                type="chunk",
                content=cand.value,
                name=cand.value,
                naming_type=name_type,
                meaning=cand.reason,
                progress=int(i * 100 / total) if total else 100,
                count=i,
                total=total,
            )

        yield NamingStreamChunk(
            type="done",
            message=f"共生成{len(response.names)}个候选",
        )

    async def add_favorite(
        self, project_id: str, name_type: str, value: str, meaning: str | None = None
    ) -> NamingFavoriteDto:
        existing = await self.session.execute(
            select(NameFavorite).where(
                NameFavorite.project_id == project_id,
                NameFavorite.name_type == name_type,
                NameFavorite.value == value,
            )
        )
        if existing.scalars().first():
            raise ValueError("该命名已收藏")
        entity = NameFavorite(
            favorite_id=str(uuid.uuid4()),
            project_id=project_id,
            name_type=name_type,
            value=value,
            meaning=meaning,
        )
        self.session.add(entity)
        await self.session.commit()
        return NamingFavoriteDto(
            favorite_id=entity.favorite_id,
            project_id=project_id,
            name_type=name_type,
            value=value,
            meaning=meaning,
            created_at=entity.created_at.isoformat() if entity.created_at else "",
        )

    async def add_favorites_batch(
        self, project_id: str, favorites: list[dict]
    ) -> int:
        """批量收藏命名，重复项跳过，返回实际新增数量."""
        saved = 0
        seen: set[tuple[str, str]] = set()
        for fav in favorites:
            name_type = (fav.get("name_type") or "").strip()
            value = (fav.get("value") or "").strip()
            if not name_type or not value:
                continue
            key = (name_type, value)
            if key in seen:
                continue
            existing = await self.session.execute(
                select(NameFavorite).where(
                    NameFavorite.project_id == project_id,
                    NameFavorite.name_type == name_type,
                    NameFavorite.value == value,
                )
            )
            if existing.scalars().first():
                seen.add(key)
                continue
            self.session.add(
                NameFavorite(
                    favorite_id=str(uuid.uuid4()),
                    project_id=project_id,
                    name_type=name_type,
                    value=value,
                    meaning=fav.get("meaning"),
                )
            )
            seen.add(key)
            saved += 1
        if saved:
            await self.session.commit()
        return saved

    async def list_favorites(
        self, project_id: str, name_type: str | None = None
    ) -> list[NamingFavoriteDto]:
        stmt = select(NameFavorite).where(NameFavorite.project_id == project_id)
        if name_type:
            stmt = stmt.where(NameFavorite.name_type == name_type)
        result = await self.session.execute(stmt)
        return [
            NamingFavoriteDto(
                favorite_id=f.favorite_id,
                project_id=f.project_id,
                name_type=f.name_type,
                value=f.value,
                meaning=f.meaning,
                created_at=f.created_at.isoformat() if f.created_at else "",
            )
            for f in result.scalars().all()
        ]

    async def list_favorites_grouped(
        self, project_id: str, skip_types: tuple[str, ...] = ("character",)
    ) -> dict[str, list[str]]:
        """按类别分组返回收藏命名（默认排除人物类），供大纲/撰写提示词注入."""
        result = await self.session.execute(
            select(NameFavorite).where(NameFavorite.project_id == project_id)
        )
        grouped: dict[str, list[str]] = {}
        for f in result.scalars().all():
            if f.name_type in skip_types:
                continue
            label = NAME_TYPE_LABELS.get(f.name_type, f.name_type)
            grouped.setdefault(label, []).append(f.value)
        return grouped

    async def remove_favorite(self, project_id: str, favorite_id: str) -> int:
        result = await self.session.execute(
            select(NameFavorite).where(
                NameFavorite.favorite_id == favorite_id,
                NameFavorite.project_id == project_id,
            )
        )
        entity = result.scalars().first()
        if not entity:
            raise ValueError("收藏记录不存在")
        await self.session.delete(entity)
        await self.session.commit()
        return 1
    async def import_to_items(self, project_id: str, name_types: list[str] | None = None) -> int:
        """将命名收藏中的物品/功法类名称导入到 Item 表.

        name_types 指定要导入的命名类型，默认为 item 和 skill。
        已存在于 Item 表中的同名物品会跳过。
        """
        if name_types is None:
            name_types = ["item", "skill"]
        fav_result = await self.session.execute(
            select(NameFavorite).where(
                NameFavorite.project_id == project_id,
                NameFavorite.name_type.in_(name_types),
            )
        )
        favorites = fav_result.scalars().all()
        if not favorites:
            return 0

        existing_items_result = await self.session.execute(
            select(Item).where(Item.project_id == project_id)
        )
        existing_names = {i.name for i in existing_items_result.scalars().all()}

        imported = 0
        for fav in favorites:
            if fav.value in existing_names:
                continue
            entity = Item(
                item_id=str(uuid.uuid4()),
                project_id=project_id,
                name=fav.value,
                item_type=NAME_TYPE_LABELS.get(fav.name_type, fav.name_type),
                key_attrs=None,
                owner_character=None,
                first_appear_volume=1,
                first_appear_chapter=1,
            )
            self.session.add(entity)
            existing_names.add(fav.value)
            imported += 1
        if imported:
            await self.session.commit()
        return imported

    async def import_to_characters(self, project_id: str) -> int:
        """将命名收藏中的角色类名称导入到 Character 表.

        已存在于 Character 表中的同名角色会跳过。
        导入的角色默认 confirmed=False，source='naming_import'。
        """
        fav_result = await self.session.execute(
            select(NameFavorite).where(
                NameFavorite.project_id == project_id,
                NameFavorite.name_type == "character",
            )
        )
        favorites = fav_result.scalars().all()
        if not favorites:
            return 0

        existing_chars_result = await self.session.execute(
            select(Character).where(Character.project_id == project_id)
        )
        existing_names = {c.name for c in existing_chars_result.scalars().all()}

        imported = 0
        for fav in favorites:
            if fav.value in existing_names:
                continue
            entity = Character(
                character_id=str(uuid.uuid4()),
                project_id=project_id,
                name=fav.value,
                identity=NAME_TYPE_LABELS.get(fav.name_type, fav.name_type),
                intro=fav.meaning,
                relation=None,
                source="naming_import",
                confirmed=False,
            )
            self.session.add(entity)
            existing_names.add(fav.value)
            imported += 1
        if imported:
            await self.session.commit()
        return imported

    async def append_to_worldview(self, project_id: str, name_types: list[str] | None = None) -> str:
        """将命名收藏中的地点/势力类名称追加到世界观内容中.

        name_types 指定要追加的命名类型，默认为 location 和 faction。
        返回更新后的世界观内容。
        """
        if name_types is None:
            name_types = ["location", "place", "faction", "sect"]
        fav_result = await self.session.execute(
            select(NameFavorite).where(
                NameFavorite.project_id == project_id,
                NameFavorite.name_type.in_(name_types),
            )
        )
        favorites = fav_result.scalars().all()
        if not favorites:
            raise ValueError("没有可追加的命名收藏")

        grouped: dict[str, list[str]] = {}
        for fav in favorites:
            label = NAME_TYPE_LABELS.get(fav.name_type, fav.name_type)
            grouped.setdefault(label, []).append(fav.value)

        appendix_lines = ["\n\n--- 作者命名库（从命名生成器导入） ---"]
        for label, names in grouped.items():
            appendix_lines.append(f"{label}：{'、'.join(names)}")

        appendix = "\n".join(appendix_lines)

        worldview = await self.session.get(Worldview, project_id)
        if worldview is None:
            raise ValueError("世界观尚未创建，请先在创作参数页设定世界观")
        worldview.content = worldview.content + appendix
        await self.session.commit()
        return worldview.content