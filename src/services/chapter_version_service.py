"""章节多版本管理服务 - 列表、标记、diff、回滚、清理."""
from __future__ import annotations

import difflib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.chapter_version_schema import (
    ChapterVersionDto,
    VersionCleanupResponse,
    VersionDiffResponse,
    VersionRollbackResponse,
)
from src.config.settings import get_config
from src.db.models import Chapter, ChapterVersion
from src.services._chapter_guard import (
    ChapterLockedError,
    assert_not_locked,
    create_auto_version_snapshot,
)
from src.utils.logger import get_logger


class ChapterVersionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    async def list_versions(
        self, chapter_id: str, version_type: str | None = None
    ) -> list[ChapterVersionDto]:
        stmt = select(ChapterVersion).where(
            ChapterVersion.chapter_id == chapter_id
        ).order_by(ChapterVersion.created_at.desc())
        if version_type:
            stmt = stmt.where(ChapterVersion.version_type == version_type)
        result = await self.session.execute(stmt)
        return [
            ChapterVersionDto(
                version_id=v.version_id,
                chapter_id=v.chapter_id,
                version_type=v.version_type,
                name=v.name,
                word_count=v.word_count,
                created_at=v.created_at,
            )
            for v in result.scalars().all()
        ]

    async def mark_manual(
        self, chapter_id: str, name: str
    ) -> ChapterVersionDto:
        chapter = await self.session.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError("章节不存在")
        if not chapter.content:
            raise ValueError("章节内容为空，无法标记版本")

        version = ChapterVersion(
            version_id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            version_type="manual",
            name=name,
            content=chapter.content,
            word_count=chapter.word_count,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(version)
        await self.session.commit()
        return ChapterVersionDto(
            version_id=version.version_id,
            chapter_id=version.chapter_id,
            version_type=version.version_type,
            name=version.name,
            word_count=version.word_count,
            created_at=version.created_at,
        )

    async def diff(self, version_id_a: str, version_id_b: str) -> VersionDiffResponse:
        va = await self.session.get(ChapterVersion, version_id_a)
        vb = await self.session.get(ChapterVersion, version_id_b)
        if not va:
            raise ValueError(f"版本不存在: {version_id_a}")
        if not vb:
            raise ValueError(f"版本不存在: {version_id_b}")

        lines_a = (va.content or "").splitlines(keepends=True)
        lines_b = (vb.content or "").splitlines(keepends=True)
        differ = difflib.HtmlDiff(wrapcolumn=80)
        html = differ.make_table(
            lines_a, lines_b,
            fromdesc=f"版本 {version_id_a[:8]}",
            todesc=f"版本 {version_id_b[:8]}",
            context=True,
        )
        return VersionDiffResponse(
            version_id_a=version_id_a,
            version_id_b=version_id_b,
            html_diff=html,
        )

    async def rollback(self, version_id: str) -> VersionRollbackResponse:
        version = await self.session.get(ChapterVersion, version_id)
        if not version:
            raise ValueError(f"版本不存在: {version_id}")

        chapter = await self.session.get(Chapter, version.chapter_id)
        if not chapter:
            raise ValueError("章节不存在")

        await assert_not_locked(self.session, chapter.chapter_id)

        await create_auto_version_snapshot(self.session, chapter)

        now = datetime.now(timezone.utc)
        chapter.content = version.content
        chapter.word_count = version.word_count
        chapter.modify_status = "rolled_back"
        chapter.last_modified_at = now

        new_snapshot = ChapterVersion(
            version_id=str(uuid.uuid4()),
            chapter_id=chapter.chapter_id,
            version_type="auto",
            name=f"rollback@{now.isoformat(timespec='seconds')}",
            content=version.content,
            word_count=version.word_count,
            created_at=now,
        )
        self.session.add(new_snapshot)
        await self.session.commit()

        return VersionRollbackResponse(
            chapter_id=chapter.chapter_id,
            new_version_id=new_snapshot.version_id,
            success=True,
            message="回滚成功",
        )

    async def cleanup(self, chapter_id: str) -> VersionCleanupResponse:
        max_keep = get_config().chapter_version_max_keep
        result = await self.session.execute(
            select(ChapterVersion)
            .where(
                ChapterVersion.chapter_id == chapter_id,
                ChapterVersion.version_type == "auto",
            )
            .order_by(ChapterVersion.created_at.desc())
        )
        auto_versions = list(result.scalars().all())
        deleted_count = 0
        if len(auto_versions) > max_keep:
            for old in auto_versions[max_keep:]:
                await self.session.delete(old)
                deleted_count += 1
            await self.session.commit()
        return VersionCleanupResponse(
            chapter_id=chapter_id,
            deleted_count=deleted_count,
        )