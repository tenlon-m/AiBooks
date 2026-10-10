"""章节锁定与版本快照共享辅助.

为 batch_replace / chapter_merge / chapter_version / writing 等 service 提供
统一的锁定校验和自动版本快照写入，避免重复实现。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_config
from src.db.models import Chapter, ChapterVersion
from src.utils.logger import get_logger


class ChapterLockedError(Exception):
    """章节已锁定，拒绝写入."""

    def __init__(self, chapter_id: str) -> None:
        super().__init__(f"章节已锁定，请先解锁: {chapter_id}")
        self.chapter_id = chapter_id


async def assert_not_locked(session: AsyncSession, chapter_id: str) -> None:
    """校验章节未锁定，锁定时抛出 ChapterLockedError."""
    chapter = await session.get(Chapter, chapter_id)
    if chapter and chapter.is_locked:
        raise ChapterLockedError(chapter_id)


async def assert_chapters_not_locked(
    session: AsyncSession, chapter_ids: list[str]
) -> None:
    """批量校验多个章节未锁定."""
    for cid in chapter_ids:
        await assert_not_locked(session, cid)


async def create_auto_version_snapshot(
    session: AsyncSession,
    chapter: Chapter,
) -> ChapterVersion | None:
    """当章节内容有变更时写入自动版本快照，并清理超出保留数量的旧 auto 版本.

    返回新建的 ChapterVersion；若章节无内容或无变更则返回 None。
    """
    logger = get_logger()
    if not chapter.content:
        return None

    from sqlalchemy import select

    latest_result = await session.execute(
        select(ChapterVersion)
        .where(ChapterVersion.chapter_id == chapter.chapter_id)
        .order_by(ChapterVersion.created_at.desc())
    )
    latest = latest_result.scalars().first()
    if latest and latest.content == chapter.content:
        return None

    version = ChapterVersion(
        version_id=str(uuid.uuid4()),
        chapter_id=chapter.chapter_id,
        version_type="auto",
        name=None,
        content=chapter.content,
        word_count=chapter.word_count,
        created_at=datetime.now(timezone.utc),
    )
    session.add(version)
    await session.flush()

    max_keep = get_config().chapter_version_max_keep
    auto_result = await session.execute(
        select(ChapterVersion)
        .where(
            ChapterVersion.chapter_id == chapter.chapter_id,
            ChapterVersion.version_type == "auto",
        )
        .order_by(ChapterVersion.created_at.desc())
    )
    auto_versions = list(auto_result.scalars().all())
    if len(auto_versions) > max_keep:
        for old in auto_versions[max_keep:]:
            await session.delete(old)
        await session.flush()

    logger.debug(
        f"章节 {chapter.chapter_id} 自动版本快照已写入，当前 auto 版本数 "
        f"{min(len(auto_versions), max_keep)}"
    )
    return version