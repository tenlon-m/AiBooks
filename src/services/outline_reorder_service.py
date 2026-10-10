"""大纲拖拽排序服务 - 事务内更新卷号/章号并检测时间线冲突."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.outline_reorder_schema import (
    OutlineOrderItem,
    OutlineReorderResponse,
)
from src.db.models import Chapter, Project
from src.services.timeline_service import TimelineService
from src.utils.logger import get_logger


class OutlineReorderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    async def reorder(
        self, project_id: str, new_order: list[OutlineOrderItem]
    ) -> OutlineReorderResponse:
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        if not new_order:
            raise ValueError("新顺序不能为空")

        order_ids = [item.chapter_id for item in new_order]
        ch_result = await self.session.execute(
            select(Chapter).where(
                Chapter.project_id == project_id,
                Chapter.chapter_id.in_(order_ids),
            )
        )
        chapter_map = {ch.chapter_id: ch for ch in ch_result.scalars().all()}
        if len(chapter_map) != len(order_ids):
            raise ValueError("部分章节不存在或不属于该项目")

        for item in new_order:
            ch = chapter_map.get(item.chapter_id)
            if ch:
                ch.volume_no = item.volume_no
                ch.chapter_no = item.chapter_no
        await self.session.flush()

        conflicts = await self._detect_timeline_conflicts(project_id)

        await self.session.commit()
        return OutlineReorderResponse(
            success=True,
            conflicts=conflicts,
        )

    async def _detect_timeline_conflicts(self, project_id: str) -> list[str]:
        try:
            timeline_service = TimelineService(self.session)
            nodes = await timeline_service.list_nodes(project_id)
            if not nodes:
                return []
            ordered = sorted(nodes, key=lambda n: n.node_order)
            return TimelineService._detect_temporal_conflicts(ordered)
        except Exception as e:
            self.logger.warning(f"时间线冲突检测失败（已忽略）: {e}")
            return []