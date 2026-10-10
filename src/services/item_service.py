"""物品清单维护服务 - 每章生成后AI提取新物品增量入库."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from typing import TYPE_CHECKING

from src.ai.gateway import get_gateway
from src.api.schemas.item_schema import ItemDto

if TYPE_CHECKING:  # 仅在类型检查时导入，避免运行期循环依赖
    from src.api.schemas.item_schema import ItemCreateRequest, ItemUpdateRequest
from src.config.settings import get_config
from src.db.models import Item
from src.db.session import release_write_lock
from src.utils.logger import get_logger


class ItemService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    def _to_dto(self, item: Item) -> ItemDto:
        return ItemDto(
            item_id=item.item_id,
            project_id=item.project_id,
            name=item.name,
            item_type=item.item_type,
            key_attrs=item.key_attrs,
            owner_character=item.owner_character,
            first_appear_volume=item.first_appear_volume,
            first_appear_chapter=item.first_appear_chapter,
        )

    async def list_by_project(self, project_id: str) -> list[ItemDto]:
        result = await self.session.execute(select(Item).where(Item.project_id == project_id))
        return [self._to_dto(i) for i in result.scalars().all()]

    async def extract_and_save(self, project_id: str, chapter_content: str, volume_no: int, chapter_no: int) -> list[ItemDto]:
        """AI 提取本章新出现物品并增量入库."""
        existing = await self.list_by_project(project_id)
        # 防御性提交：本方法无法预知调用方的事务状态。会话配置了 autoflush=False，
        # 属性赋值不会立刻写库；但只要调用方在这之前 exec 过 DML 或调用过 flush()
        # （例如大纲侧 _reset_outline、任何先落库再调 AI 的流程），写锁就会被一直
        # 持有到 commit。带着它跨过下面的 AI 调用，期间并发的自动保存与网关计数器
        # 写回都会撞 database is locked。
        # 这里无事可做时就是空操作；有事时会顺带把本章内容立即落盘，
        # 符合"每章完成立即持久化"的要求。
        await release_write_lock(self.session)
        try:
            result = await self.gateway.call_and_parse(
                module="writing",
                scene="extract-items",
                params={
                    "chapter_content": chapter_content,
                    "existing_items": [i.model_dump() for i in existing],
                },
                project_id=project_id,
            )
            items_data = result.get("parsed", {}).get("items", [])
        except Exception as e:
            self.logger.warning(f"物品提取失败: {e}")
            return []

        existing_names = {i.name for i in existing}
        new_items = []
        for it in items_data:
            name = it.get("name", "")
            if not name or name in existing_names:
                continue
            entity = Item(
                item_id=str(uuid.uuid4()),
                project_id=project_id,
                name=name,
                item_type=it.get("item_type", "未知"),
                key_attrs=it.get("key_attrs"),
                owner_character=it.get("owner_character"),
                first_appear_volume=volume_no,
                first_appear_chapter=chapter_no,
            )
            self.session.add(entity)
            await self.session.flush()
            new_items.append(self._to_dto(entity))
            existing_names.add(name)
        return new_items

    async def create(self, req: "ItemCreateRequest") -> ItemDto:
        """手动新增一个物品（物品管理页入口）."""
        entity = Item(
            item_id=str(uuid.uuid4()),
            project_id=req.project_id,
            name=req.name,
            item_type=req.item_type,
            key_attrs=req.key_attrs,
            owner_character=req.owner_character,
            first_appear_volume=req.first_appear_volume,
            first_appear_chapter=req.first_appear_chapter,
        )
        self.session.add(entity)
        await self.session.flush()
        return self._to_dto(entity)

    async def update(self, item_id: str, req: "ItemUpdateRequest") -> ItemDto:
        """更新物品字段（只更新显式传入的字段）."""
        item = await self.session.get(Item, item_id)
        if not item:
            raise ValueError("物品不存在")
        for field in (
            "name",
            "item_type",
            "key_attrs",
            "owner_character",
            "first_appear_volume",
            "first_appear_chapter",
        ):
            value = getattr(req, field, None)
            if value is not None:
                setattr(item, field, value)
        await self.session.flush()
        return self._to_dto(item)

    async def delete(self, item_id: str) -> int:
        """删除物品，返回删除数量."""
        item = await self.session.get(Item, item_id)
        if not item:
            raise ValueError("物品不存在")
        await self.session.delete(item)
        await self.session.flush()
        return 1

    async def check_consistency(self, project_id: str) -> list[str]:
        """检查物品全书一致性."""
        items = await self.list_by_project(project_id)
        problems = []
        name_type_map: dict[str, str] = {}
        for it in items:
            if it.name in name_type_map:
                if name_type_map[it.name] != it.item_type:
                    problems.append(f"物品 '{it.name}' 类型不一致: {name_type_map[it.name]} vs {it.item_type}")
            else:
                name_type_map[it.name] = it.item_type
        return problems