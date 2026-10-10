"""Repository 基类 - 封装通用 CRUD 与查询."""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """通用 Repository 基类，子类设置 model_class 即可获得 CRUD 能力."""

    model_class: type[T]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, pk: Any) -> T | None:
        return await self.session.get(self.model_class, pk)

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        stmt = select(self.model_class).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by(self, **filters: Any) -> list[T]:
        stmt = select(self.model_class).filter_by(**filters)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_one_by(self, **filters: Any) -> T | None:
        stmt = select(self.model_class).filter_by(**filters)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: T) -> T:
        await self.session.flush()
        return entity

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def delete_by_id(self, pk: Any) -> bool:
        entity = await self.get_by_id(pk)
        if entity is None:
            return False
        await self.delete(entity)
        return True

    async def count(self, **filters: Any) -> int:
        from sqlalchemy import func
        stmt = select(func.count()).select_from(self.model_class)
        if filters:
            stmt = stmt.filter_by(**filters)
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0)