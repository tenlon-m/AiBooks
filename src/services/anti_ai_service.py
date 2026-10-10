"""降AI率改写服务."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.anti_ai_schema import AntiAiRewriteDto
from src.api.schemas.writing_schema import ChapterDto
from src.config.settings import get_config
from src.db.models import AntiAiRewriteRecord, Chapter, ChapterVersion
from src.db.session import release_write_lock
from src.utils.logger import get_logger

_DETECTOR_FEATURES = (
    "朱雀等AI检测器主要识别特征："
    "句式过于工整对仗、成语排比堆砌、转折词套路化（然而/但是/不仅而且）、"
    "情感说教直白、句式结构雷同、典型AI用语（综上所述/值得注意的是）、"
    "段落长度均匀、缺乏口语化表达、描写缺乏画面感与细节。"
)

_VALID_STRATEGIES = {"句式变换", "同义替换", "口语化", "全部"}


class AntiAiService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def rewrite_chapter(
        self, chapter_id: str, strategy: str = "全部"
    ) -> AntiAiRewriteDto:
        if strategy not in _VALID_STRATEGIES:
            raise ValueError(f"不支持的策略：{strategy}，可选：{', '.join(sorted(_VALID_STRATEGIES))}")

        chapter = await self.session.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError("章节不存在")
        if not chapter.content or not chapter.content.strip():
            raise ValueError("章节内容为空，无法改写")

        original_content = chapter.content

        original_version = ChapterVersion(
            version_id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            version_type="auto",
            name=f"anti-ai-original@{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
            content=original_content,
            word_count=chapter.word_count,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(original_version)
        await self.session.flush()
        original_version_id = original_version.version_id

        await release_write_lock(self.session)

        min_length = get_config().min_ai_content_length
        timeout_seconds = get_config().anti_ai_rewrite_timeout_seconds

        rewritten_content = await self._call_rewrite(
            original_content, strategy, chapter.project_id, timeout_seconds
        )

        if len(rewritten_content.strip()) < min_length:
            self.logger.warning(
                f"降AI率改写首次输出仅 {len(rewritten_content.strip())} 字，"
                f"不足 {min_length} 字，重试一次"
            )
            rewritten_content = await self._call_rewrite(
                original_content, strategy, chapter.project_id, timeout_seconds
            )
            if len(rewritten_content.strip()) < min_length:
                raise ValueError(
                    f"改写结果过短（{len(rewritten_content.strip())} 字），"
                    f"未达到最低要求 {min_length} 字"
                )

        record = AntiAiRewriteRecord(
            rewrite_id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            original_version_id=original_version_id,
            rewritten_content=rewritten_content,
            strategy=strategy,
            adopt_status="待采纳",
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(record)
        await self.session.commit()

        self.logger.info(
            f"降AI率改写完成 chapter_id={chapter_id} rewrite_id={record.rewrite_id} "
            f"strategy={strategy}"
        )

        return self._to_dto(record)

    async def _call_rewrite(
        self,
        original_content: str,
        strategy: str,
        project_id: str,
        timeout_seconds: int,
    ) -> str:
        result = await self.gateway.call(
            module="rewrite",
            scene="anti-ai",
            params={
                "original_content": original_content,
                "strategy": strategy,
                "detector_features": _DETECTOR_FEATURES,
            },
            project_id=project_id,
            temperature=0.8,
            max_tokens=4096,
            timeout_seconds=timeout_seconds,
        )
        return result.get("content", "").strip()

    async def list_rewrites(self, chapter_id: str) -> list[AntiAiRewriteDto]:
        result = await self.session.execute(
            select(AntiAiRewriteRecord)
            .where(AntiAiRewriteRecord.chapter_id == chapter_id)
            .order_by(AntiAiRewriteRecord.created_at.desc())
        )
        return [self._to_dto(r) for r in result.scalars().all()]

    async def adopt_rewrite(self, rewrite_id: str) -> ChapterDto:
        record = await self.session.get(AntiAiRewriteRecord, rewrite_id)
        if not record:
            raise ValueError("改写记录不存在")
        if record.adopt_status == "已采纳":
            raise ValueError("该改写已采纳，请勿重复操作")

        chapter = await self.session.get(Chapter, record.chapter_id)
        if not chapter:
            raise ValueError("章节不存在")

        snapshot = ChapterVersion(
            version_id=str(uuid.uuid4()),
            chapter_id=chapter.chapter_id,
            version_type="auto",
            name=f"anti-ai-before-adopt@{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
            content=chapter.content or "",
            word_count=chapter.word_count,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(snapshot)

        now = datetime.now(timezone.utc)
        chapter.content = record.rewritten_content
        chapter.word_count = len(record.rewritten_content)
        chapter.modify_status = "modified"
        chapter.last_modified_at = now

        record.adopt_status = "已采纳"
        await self.session.commit()

        self.logger.info(
            f"采纳降AI率改写 rewrite_id={rewrite_id} chapter_id={chapter.chapter_id}"
        )

        return ChapterDto(
            chapter_id=chapter.chapter_id,
            project_id=chapter.project_id,
            volume_no=chapter.volume_no,
            chapter_no=chapter.chapter_no,
            title=chapter.title,
            content=chapter.content,
            word_count=chapter.word_count,
            gen_status=chapter.gen_status,
            modify_status=chapter.modify_status,
        )

    async def rollback_rewrite(self, rewrite_id: str) -> None:
        record = await self.session.get(AntiAiRewriteRecord, rewrite_id)
        if not record:
            raise ValueError("改写记录不存在")
        if record.adopt_status != "已采纳":
            raise ValueError("仅已采纳的改写可回退")

        original_version = await self.session.get(
            ChapterVersion, record.original_version_id
        )
        if not original_version:
            raise ValueError("原始版本快照不存在，无法回退")

        chapter = await self.session.get(Chapter, record.chapter_id)
        if not chapter:
            raise ValueError("章节不存在")

        rollback_snapshot = ChapterVersion(
            version_id=str(uuid.uuid4()),
            chapter_id=chapter.chapter_id,
            version_type="auto",
            name=f"anti-ai-rollback@{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
            content=chapter.content or "",
            word_count=chapter.word_count,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(rollback_snapshot)

        now = datetime.now(timezone.utc)
        chapter.content = original_version.content
        chapter.word_count = original_version.word_count
        chapter.modify_status = "rolled_back"
        chapter.last_modified_at = now

        record.adopt_status = "已回退"
        await self.session.commit()

        self.logger.info(
            f"回退降AI率改写 rewrite_id={rewrite_id} chapter_id={chapter.chapter_id}"
        )

    @staticmethod
    def _to_dto(record: AntiAiRewriteRecord) -> AntiAiRewriteDto:
        return AntiAiRewriteDto(
            rewrite_id=record.rewrite_id,
            chapter_id=record.chapter_id,
            rewritten_content=record.rewritten_content,
            strategy=record.strategy,
            adopt_status=record.adopt_status,
            created_at=record.created_at.isoformat() if record.created_at else "",
        )