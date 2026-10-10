"""乱码修复配置服务 - 三层优先级解析与持久化读写.

方案 C：内置默认 < 全局配置 < 项目级配置。
对应 spec 5.6.1 规则 4、6.6.4，design 2.7.2。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import GarbledConfigModel
from src.services.garbled_normalizer import GarbledConfig
from src.utils.logger import get_logger


# 内置默认配置（spec 6.5）
_BUILTIN_DEFAULT = GarbledConfig()

# 可覆盖的阈值字段列表
_CONFIG_FIELDS = [
    "enabled",
    "max_blank_lines",
    "max_punct_repeat",
    "max_consecutive_spaces",
    "enable_fullwidth_indent",
    "enable_punct_repeat_fix",
    "enable_whitespace_cleanup",
    "enable_irreversible_clear",
]


class GarbledConfigService:
    """乱码修复配置服务."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    async def resolve_effective_config(
        self, project_id: str | None = None
    ) -> GarbledConfig:
        """解析生效配置：内置默认 < 全局 < 项目级.

        逐字段覆盖非整条替换（spec 5.6.1 规则 9）。
        """
        try:
            kwargs: dict[str, object] = {}

            # 全局配置覆盖
            global_model = await self._get_model("global", None)
            if global_model:
                self._overlay(kwargs, global_model)

            # 项目级配置覆盖
            if project_id:
                project_model = await self._get_model("project", project_id)
                if project_model:
                    self._overlay(kwargs, project_model)

            config = GarbledConfig(**kwargs)
            return self._validate(config)
        except Exception as e:
            self.logger.warning(f"解析乱码配置失败，回退默认: {e}")
            return GarbledConfig()

    async def get_config(
        self, scope: str, project_id: str | None
    ) -> GarbledConfigModel | None:
        """读取指定作用域配置."""
        return await self._get_model(scope, project_id)

    async def save_config(
        self, scope: str, project_id: str | None, config: GarbledConfig
    ) -> None:
        """保存配置（upsert 语义）."""
        existing = await self._get_model(scope, project_id)
        now = datetime.now(timezone.utc)

        if existing:
            for field in _CONFIG_FIELDS:
                setattr(existing, field, getattr(config, field))
            existing.updated_at = now
        else:
            model = GarbledConfigModel(
                config_id=str(uuid.uuid4()),
                scope=scope,
                project_id=project_id if scope == "project" else None,
                **{f: getattr(config, f) for f in _CONFIG_FIELDS},
                updated_at=now,
            )
            self.session.add(model)
        await self.session.flush()

    async def delete_config(
        self, scope: str, project_id: str | None
    ) -> None:
        """删除配置."""
        model = await self._get_model(scope, project_id)
        if model:
            await self.session.delete(model)
            await self.session.flush()

    # ── 内部方法 ──────────────────────────────────────────────

    async def _get_model(
        self, scope: str, project_id: str | None
    ) -> GarbledConfigModel | None:
        """查询配置模型."""
        stmt = select(GarbledConfigModel).where(
            GarbledConfigModel.scope == scope,
        )
        if project_id:
            stmt = stmt.where(GarbledConfigModel.project_id == project_id)
        else:
            stmt = stmt.where(GarbledConfigModel.project_id.is_(None))
        result = await self.session.execute(stmt)
        return result.scalars().first()

    def _overlay(
        self, kwargs: dict[str, object], model: GarbledConfigModel
    ) -> None:
        """用模型非 NULL 字段覆盖 kwargs（逐字段覆盖）."""
        for field in _CONFIG_FIELDS:
            val = getattr(model, field, None)
            if val is not None:
                kwargs[field] = val

    def _validate(self, config: GarbledConfig) -> GarbledConfig:
        """校验阈值合法性，非法值回退默认."""
        try:
            if config.max_blank_lines < 0:
                config.max_blank_lines = _BUILTIN_DEFAULT.max_blank_lines
            if config.max_punct_repeat < 0:
                config.max_punct_repeat = _BUILTIN_DEFAULT.max_punct_repeat
            if config.max_consecutive_spaces < 0:
                config.max_consecutive_spaces = _BUILTIN_DEFAULT.max_consecutive_spaces
        except Exception as e:
            self.logger.warning(f"乱码配置阈值非法，回退默认: {e}")
            return GarbledConfig()
        return config