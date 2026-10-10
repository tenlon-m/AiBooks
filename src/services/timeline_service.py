"""时间线管理服务 - 事件节点 CRUD 与时序冲突检测."""
from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.timeline_schema import (
    TimelineCreateRequest,
    TimelineNodeDto,
    TimelineReorderResult,
    TimelineUpdateRequest,
)
from src.db.models import Chapter, Character, Project, TimelineNode
from src.utils.logger import get_logger

DEATH_KEYWORDS = ("死亡", "身亡", "陨落", "战死", "牺牲", "逝世", "离世", "身陨")


class TimelineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    @staticmethod
    def _to_dto(node: TimelineNode) -> TimelineNodeDto:
        return TimelineNodeDto(
            node_id=node.node_id,
            project_id=node.project_id,
            event_name=node.event_name,
            time_point=node.time_point,
            characters=json.loads(node.characters) if node.characters else [],
            chapter_ids=json.loads(node.chapter_ids) if node.chapter_ids else [],
            description=node.description,
            node_order=node.node_order,
        )

    async def create_node(self, project_id: str, req: TimelineCreateRequest) -> TimelineNodeDto:
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        node = TimelineNode(
            node_id=str(uuid.uuid4()),
            project_id=project_id,
            event_name=req.event_name,
            time_point=req.time_point,
            characters=json.dumps(req.characters, ensure_ascii=False),
            chapter_ids=json.dumps(req.chapter_ids, ensure_ascii=False),
            description=req.description,
            node_order=req.node_order,
        )
        self.session.add(node)
        await self.session.commit()
        return self._to_dto(node)

    async def list_nodes(self, project_id: str) -> list[TimelineNodeDto]:
        result = await self.session.execute(
            select(TimelineNode)
            .where(TimelineNode.project_id == project_id)
            .order_by(TimelineNode.node_order)
        )
        return [self._to_dto(n) for n in result.scalars().all()]

    async def update_node(
        self, project_id: str, node_id: str, req: TimelineUpdateRequest
    ) -> TimelineNodeDto:
        node = await self.session.get(TimelineNode, node_id)
        if not node or node.project_id != project_id:
            raise ValueError("时间线节点不存在")
        if req.event_name is not None:
            node.event_name = req.event_name
        if req.time_point is not None:
            node.time_point = req.time_point
        if req.characters is not None:
            node.characters = json.dumps(req.characters, ensure_ascii=False)
        if req.chapter_ids is not None:
            node.chapter_ids = json.dumps(req.chapter_ids, ensure_ascii=False)
        if req.description is not None:
            node.description = req.description
        if req.node_order is not None:
            node.node_order = req.node_order
        await self.session.commit()
        return self._to_dto(node)

    async def delete_node(self, project_id: str, node_id: str) -> int:
        node = await self.session.get(TimelineNode, node_id)
        if not node or node.project_id != project_id:
            raise ValueError("时间线节点不存在")
        await self.session.delete(node)
        await self.session.commit()
        return 1

    async def reorder(
        self, project_id: str, node_orders: list[dict]
    ) -> TimelineReorderResult:
        """按给定顺序重排节点，并检测时序冲突（角色在死亡事件后出现在后续事件）."""
        nodes = await self.list_nodes(project_id)
        node_map = {n.node_id: n for n in nodes}
        ordered: list[TimelineNodeDto] = []
        for item in node_orders:
            nid = item.get("node_id")
            order = item.get("node_order", 0)
            if nid in node_map:
                node_map[nid].node_order = order
                ordered.append(node_map[nid])
        ordered.sort(key=lambda n: n.node_order)
        await self.session.commit()

        conflicts = self._detect_temporal_conflicts(ordered)
        return TimelineReorderResult(success=True, conflicts=conflicts)

    @staticmethod
    def _detect_temporal_conflicts(ordered_nodes: list[TimelineNodeDto]) -> list[str]:
        """检测角色在死亡事件后出现在后续事件."""
        conflicts: list[str] = []
        dead_characters: dict[str, str] = {}
        for node in ordered_nodes:
            event_name = node.event_name or ""
            is_death = any(kw in event_name for kw in DEATH_KEYWORDS)
            if node.description:
                is_death = is_death or any(
                    kw in node.description for kw in DEATH_KEYWORDS
                )
            for char_id in node.characters:
                if char_id in dead_characters:
                    conflicts.append(
                        f"角色 {char_id} 在 '{dead_characters[char_id]}' 死亡后"
                        f"仍出现在后续事件 '{node.event_name}'"
                    )
            if is_death:
                for char_id in node.characters:
                    if char_id not in dead_characters:
                        dead_characters[char_id] = node.event_name
        return conflicts