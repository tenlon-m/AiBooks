"""快捷键服务 - 列表/更新/重置/冲突检测，持久化至 shortcut_configs 表.

预设快捷键：保存 Ctrl+S / 查找 Ctrl+F / 替换 Ctrl+H / 新建章节 Ctrl+N
           AI对话 Ctrl+Shift+D / 续写 Ctrl+Shift+R
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.shortcut_schema import ShortcutDto, ShortcutUpdateRequest
from src.db.models import ShortcutConfig
from src.utils.logger import get_logger


# 预设快捷键：action_name -> (action_label, key_sequence)
BUILTIN_SHORTCUTS: list[dict] = [
    {"action_name": "save", "action_label": "保存", "key_sequence": "Ctrl+S"},
    {"action_name": "find", "action_label": "查找", "key_sequence": "Ctrl+F"},
    {"action_name": "replace", "action_label": "替换", "key_sequence": "Ctrl+H"},
    {"action_name": "new_chapter", "action_label": "新建章节", "key_sequence": "Ctrl+N"},
    {"action_name": "ai_chat", "action_label": "AI对话", "key_sequence": "Ctrl+Shift+D"},
    {"action_name": "continue_writing", "action_label": "续写", "key_sequence": "Ctrl+Shift+R"},
]


class ShortcutConflictError(Exception):
    """快捷键冲突异常."""

    def __init__(self, key_sequence: str, conflict_action: str) -> None:
        self.key_sequence = key_sequence
        self.conflict_action = conflict_action
        super().__init__(
            f"快捷键 '{key_sequence}' 已被操作 '{conflict_action}' 占用"
        )


class ShortcutService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    async def list_shortcuts(self) -> list[ShortcutDto]:
        """列出全部快捷键配置；若表为空则先初始化预设."""
        result = await self.session.execute(select(ShortcutConfig))
        entities = result.scalars().all()
        if not entities:
            entities = await self._init_builtin_shortcuts()
        return [self._to_dto(e) for e in entities]

    async def update_shortcut(
        self,
        shortcut_id: str,
        req: ShortcutUpdateRequest,
    ) -> ShortcutDto:
        """更新指定快捷键；冲突时抛 ShortcutConflictError."""
        entity = await self.session.get(ShortcutConfig, shortcut_id)
        if not entity:
            raise ValueError(f"快捷键不存在: {shortcut_id}")

        if req.key_sequence is not None:
            new_seq = req.key_sequence.strip()
            if not new_seq:
                raise ValueError("快捷键序列不能为空")
            conflict = await self._find_conflict(new_seq, exclude_id=shortcut_id)
            if conflict:
                raise ShortcutConflictError(new_seq, conflict.action_label)
            entity.key_sequence = new_seq

        if req.enabled is not None:
            entity.enabled = req.enabled

        entity.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return self._to_dto(entity)

    async def reset(self) -> list[ShortcutDto]:
        """重置全部快捷键为预设值."""
        result = await self.session.execute(select(ShortcutConfig))
        for e in result.scalars().all():
            await self.session.delete(e)
        await self.session.flush()
        entities = await self._init_builtin_shortcuts()
        return [self._to_dto(e) for e in entities]

    async def _find_conflict(
        self,
        key_sequence: str,
        exclude_id: str | None = None,
    ) -> ShortcutConfig | None:
        """查找启用状态下占用同一快捷键序列的其他配置."""
        stmt = select(ShortcutConfig).where(
            ShortcutConfig.key_sequence == key_sequence,
            ShortcutConfig.enabled.is_(True),
        )
        result = await self.session.execute(stmt)
        for e in result.scalars().all():
            if exclude_id and e.shortcut_id == exclude_id:
                continue
            return e
        return None

    async def _init_builtin_shortcuts(self) -> list[ShortcutConfig]:
        """初始化预设快捷键到数据库."""
        entities: list[ShortcutConfig] = []
        for item in BUILTIN_SHORTCUTS:
            entity = ShortcutConfig(
                shortcut_id=str(uuid.uuid4()),
                action_name=item["action_name"],
                action_label=item["action_label"],
                key_sequence=item["key_sequence"],
                enabled=True,
                is_builtin=True,
            )
            self.session.add(entity)
            entities.append(entity)
        await self.session.flush()
        return entities

    @staticmethod
    def _to_dto(e: ShortcutConfig) -> ShortcutDto:
        return ShortcutDto(
            shortcut_id=e.shortcut_id,
            action_name=e.action_name,
            action_label=e.action_label,
            key_sequence=e.key_sequence,
            enabled=e.enabled,
            is_builtin=e.is_builtin,
        )