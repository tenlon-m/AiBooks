"""敏感词检测服务 - 合并内置JSON词库与数据库词表，分批扫描章节."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.sensitive_word_schema import (
    SensitiveHitDto,
    SensitiveScanResult,
    SensitiveWordAddRequest,
    SensitiveWordDto,
    SensitiveWordListResponse,
    SensitiveWordUpdateRequest,
)
from src.config.settings import get_config
from src.db.models import Chapter, SensitiveWord
from src.utils.logger import get_logger

def _builtin_dir() -> Path:
    return get_config().templates_dir / "sensitive_words"


class SensitiveWordService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    @staticmethod
    def _load_builtin() -> list[SensitiveWordDto]:
        if not _builtin_dir().exists():
            return []
        result: list[SensitiveWordDto] = []
        for fp in sorted(_builtin_dir().glob("*.json")):
            try:
                with fp.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                category = raw.get("category", "unknown")
                suggestion = raw.get("replacement_suggestions")
                for w in raw.get("words", []):
                    result.append(
                        SensitiveWordDto(
                            word=w,
                            category=category,
                            suggestion=suggestion,
                            is_builtin=True,
                        )
                    )
            except Exception as e:
                get_logger().warning(f"加载内置敏感词库失败 {fp}: {e}")
        return result

    async def list_words(
        self, project_id: str | None = None
    ) -> SensitiveWordListResponse:
        builtin = self._load_builtin()
        stmt = select(SensitiveWord)
        if project_id:
            stmt = stmt.where(
                (SensitiveWord.project_id == project_id)
                | (SensitiveWord.project_id.is_(None))
            )
        result = await self.session.execute(stmt)
        db_words = [
            SensitiveWordDto(
                word_id=w.word_id,
                project_id=w.project_id,
                word=w.word,
                category=w.category,
                suggestion=w.suggestion,
                is_builtin=w.is_builtin,
            )
            for w in result.scalars().all()
        ]
        all_words = builtin + db_words
        return SensitiveWordListResponse(words=all_words, total=len(all_words))

    async def add_word(self, req: SensitiveWordAddRequest) -> SensitiveWordDto:
        entity = SensitiveWord(
            word_id=str(uuid.uuid4()),
            project_id=req.project_id,
            word=req.word,
            category=req.category,
            suggestion=req.suggestion,
            is_builtin=False,
        )
        self.session.add(entity)
        await self.session.commit()
        return SensitiveWordDto(
            word_id=entity.word_id,
            project_id=entity.project_id,
            word=entity.word,
            category=entity.category,
            suggestion=entity.suggestion,
            is_builtin=False,
        )

    async def update_word(
        self, word_id: str, req: SensitiveWordUpdateRequest
    ) -> SensitiveWordDto:
        entity = await self.session.get(SensitiveWord, word_id)
        if not entity:
            raise ValueError("敏感词不存在")
        if entity.is_builtin:
            raise ValueError("内置敏感词不可修改")
        if req.word is not None:
            entity.word = req.word
        if req.category is not None:
            entity.category = req.category
        if req.suggestion is not None:
            entity.suggestion = req.suggestion
        await self.session.commit()
        return SensitiveWordDto(
            word_id=entity.word_id,
            project_id=entity.project_id,
            word=entity.word,
            category=entity.category,
            suggestion=entity.suggestion,
            is_builtin=False,
        )

    async def delete_word(self, word_id: str) -> int:
        entity = await self.session.get(SensitiveWord, word_id)
        if not entity:
            raise ValueError("敏感词不存在")
        if entity.is_builtin:
            raise ValueError("内置敏感词不可删除")
        await self.session.delete(entity)
        await self.session.commit()
        return 1

    async def save_words(self, words: list[dict]) -> tuple[int, int]:
        """批量保存词库（UI 的「保存」按钮）.

        - ``word_id`` 为空 → 新增词条（project_id 为 None，即全局词库）；
        - ``word_id`` 非空且存在 → 更新；内置词条与不存在的 id 静默跳过。
        - ``word`` 为空串的条目跳过（UI 表格可能出现空行）。

        Returns:
            (新增数, 更新数)
        """
        created = updated = 0
        for item in words:
            word = (item.get("word") or "").strip()
            if not word:
                continue
            category = (item.get("category") or "").strip() or "custom"
            suggestion = (item.get("replace_suggestion") or "").strip() or None
            word_id = item.get("word_id")
            if word_id:
                entity = await self.session.get(SensitiveWord, word_id)
                if entity is None or entity.is_builtin:
                    continue
                entity.word = word
                entity.category = category
                entity.suggestion = suggestion
                updated += 1
            else:
                self.session.add(
                    SensitiveWord(
                        word_id=str(uuid.uuid4()),
                        project_id=None,
                        word=word,
                        category=category,
                        suggestion=suggestion,
                        is_builtin=False,
                    )
                )
                created += 1
        await self.session.commit()
        return created, updated

    async def delete_words(self, word_ids: list[str]) -> int:
        """批量删除词条（UI 的「删除选中」按钮）.

        内置词条与不存在的 id 静默跳过。Returns: 实际删除数。
        """
        deleted = 0
        for word_id in word_ids:
            if not word_id:
                continue
            entity = await self.session.get(SensitiveWord, word_id)
            if entity is None or entity.is_builtin:
                continue
            await self.session.delete(entity)
            deleted += 1
        await self.session.commit()
        return deleted

    async def scan(
        self, project_id: str, chapter_ids: list[str] | None = None
    ) -> SensitiveScanResult:
        """合并内置词库与数据库词表，按 batch_size 分批扫描章节内容."""
        word_list = await self.list_words(project_id)
        words_by_category: dict[str, list[SensitiveWordDto]] = {}
        for w in word_list.words:
            words_by_category.setdefault(w.category, []).append(w)

        stmt = select(Chapter).where(Chapter.project_id == project_id)
        if chapter_ids:
            stmt = stmt.where(Chapter.chapter_id.in_(chapter_ids))
        result = await self.session.execute(stmt)
        chapters = result.scalars().all()

        batch_size = get_config().sensitive_word_scan_batch_size
        hits: list[SensitiveHitDto] = []
        all_words = [w for w in word_list.words if w.word]
        for i in range(0, len(chapters), batch_size):
            batch = chapters[i : i + batch_size]
            for chapter in batch:
                content = chapter.content or ""
                if not content:
                    continue
                for sw in all_words:
                    count = content.count(sw.word)
                    if count > 0:
                        hits.append(
                            SensitiveHitDto(
                                word=sw.word,
                                category=sw.category,
                                suggestion=sw.suggestion,
                                chapter_id=chapter.chapter_id,
                                chapter_no=chapter.chapter_no,
                                count=count,
                            )
                        )
        return SensitiveScanResult(
            project_id=project_id,
            total_hits=len(hits),
            hits=hits,
        )