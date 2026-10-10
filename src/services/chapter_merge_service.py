"""章节合并/拆分服务 - 相邻性校验、事务内版本快照、重新编号."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.chapter_merge_schema import (
    ChapterMergeResponse,
    ChapterSplitResponse,
)
from src.db.models import Chapter, ChapterVersion, Project
from src.db.session import release_write_lock
from src.services._chapter_guard import (
    ChapterLockedError,
    assert_chapters_not_locked,
    create_auto_version_snapshot,
)
from src.utils.logger import get_logger


class ChapterMergeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def merge(
        self, chapter_ids: list[str], new_title: str | None = None
    ) -> ChapterMergeResponse:
        if len(chapter_ids) < 2:
            raise ValueError("合并至少需要2个章节")

        await assert_chapters_not_locked(self.session, chapter_ids)

        ch_result = await self.session.execute(
            select(Chapter).where(Chapter.chapter_id.in_(chapter_ids))
        )
        chapters = list(ch_result.scalars().all())
        if len(chapters) != len(chapter_ids):
            raise ValueError("部分章节不存在")

        id_order = {cid: i for i, cid in enumerate(chapter_ids)}
        chapters.sort(key=lambda c: id_order[c.chapter_id])

        for i in range(1, len(chapters)):
            prev = chapters[i - 1]
            curr = chapters[i]
            prev_order = (prev.volume_no, prev.chapter_no)
            curr_order = (curr.volume_no, curr.chapter_no)
            if curr_order[0] == prev_order[0]:
                if curr_order[1] != prev_order[1] + 1:
                    raise ValueError("章节不相邻，无法合并")
            elif curr_order[0] == prev_order[0] + 1:
                if curr_order[1] != 1:
                    raise ValueError("跨卷合并仅支持卷末+卷首")
            else:
                raise ValueError("章节不相邻，无法合并")

        project_id = chapters[0].project_id
        merged_content = "\n\n".join(c.content or "" for c in chapters)
        merged_word_count = len(merged_content)

        if not new_title:
            new_title = await self._ai_generate_title(chapters, merged_content)

        now = datetime.now(timezone.utc)
        for ch in chapters:
            await create_auto_version_snapshot(self.session, ch)

        first = chapters[0]
        new_chapter = Chapter(
            chapter_id=str(uuid.uuid4()),
            project_id=project_id,
            volume_no=first.volume_no,
            chapter_no=first.chapter_no,
            title=new_title,
            content=merged_content,
            word_count=merged_word_count,
            gen_status="completed",
            modify_status="merged",
            last_modified_at=now,
        )
        self.session.add(new_chapter)

        for ch in chapters:
            await self.session.delete(ch)

        await self.session.flush()
        await self._renumber(project_id)

        await self.session.commit()
        return ChapterMergeResponse(
            new_chapter_id=new_chapter.chapter_id,
            new_title=new_title,
            volume_no=new_chapter.volume_no,
            chapter_no=new_chapter.chapter_no,
            word_count=merged_word_count,
        )

    async def split(
        self,
        chapter_id: str,
        split_positions: list[int],
        new_titles: list[str] | None = None,
    ) -> ChapterSplitResponse:
        from src.services._chapter_guard import assert_not_locked
        await assert_not_locked(self.session, chapter_id)

        chapter = await self.session.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError("章节不存在")
        if not chapter.content:
            raise ValueError("章节内容为空，无法拆分")

        content = chapter.content
        positions = sorted(set(split_positions))
        if not positions:
            raise ValueError("未指定拆分位置")
        if positions[0] <= 0 or positions[-1] >= len(content):
            raise ValueError("拆分位置越界，必须在 1 到 len(content)-1 之间")

        await create_auto_version_snapshot(self.session, chapter)

        boundaries = [0] + positions + [len(content)]
        segments = [content[boundaries[i]:boundaries[i + 1]] for i in range(len(boundaries) - 1)]

        if new_titles and len(new_titles) == len(segments):
            titles = list(new_titles)
        else:
            base_title = chapter.title
            titles = [f"{base_title}（{i + 1}）" for i in range(len(segments))]

        now = datetime.now(timezone.utc)
        project_id = chapter.project_id
        volume_no = chapter.volume_no
        base_chapter_no = chapter.chapter_no

        new_chapter_ids: list[str] = []
        ch_result = await self.session.execute(
            select(Chapter).where(
                Chapter.project_id == project_id,
                Chapter.volume_no == volume_no,
                Chapter.chapter_no >= base_chapter_no,
            ).order_by(Chapter.chapter_no)
        )
        following = list(ch_result.scalars().all())
        shift = len(segments) - 1
        for ch in following:
            if ch.chapter_id == chapter_id:
                continue
            ch.chapter_no = ch.chapter_no + shift

        await self.session.delete(chapter)
        await self.session.flush()

        for i, seg in enumerate(segments):
            new_ch = Chapter(
                chapter_id=str(uuid.uuid4()),
                project_id=project_id,
                volume_no=volume_no,
                chapter_no=base_chapter_no + i,
                title=titles[i],
                content=seg,
                word_count=len(seg),
                gen_status="completed",
                modify_status="split",
                last_modified_at=now,
            )
            self.session.add(new_ch)
            new_chapter_ids.append(new_ch.chapter_id)

        await self.session.flush()
        await self._renumber(project_id)
        await self.session.commit()

        return ChapterSplitResponse(
            new_chapter_ids=new_chapter_ids,
            titles=titles,
        )

    async def _ai_generate_title(self, chapters: list[Chapter], merged_content: str) -> str:
        try:
            await release_write_lock(self.session)
            result = await self.gateway.call_and_parse(
                module="chapter",
                scene="merge-title",
                params={
                    "original_titles": [c.title for c in chapters],
                    "content_preview": merged_content[:1000],
                },
                project_id=chapters[0].project_id,
            )
            title = result.get("parsed", {}).get("title", "")
            if title:
                return title[:200]
        except Exception as e:
            self.logger.warning(f"AI生成合并标题失败，使用默认标题: {e}")
        return "、".join(c.title for c in chapters)

    async def _renumber(self, project_id: str) -> None:
        ch_result = await self.session.execute(
            select(Chapter).where(Chapter.project_id == project_id)
            .order_by(Chapter.volume_no, Chapter.chapter_no)
        )
        all_chapters = list(ch_result.scalars().all())
        vol_groups: dict[int, list[Chapter]] = {}
        for ch in all_chapters:
            vol_groups.setdefault(ch.volume_no, []).append(ch)
        for vol_no, group in vol_groups.items():
            group.sort(key=lambda c: c.chapter_no)
            for idx, ch in enumerate(group, 1):
                ch.chapter_no = idx
        await self.session.flush()