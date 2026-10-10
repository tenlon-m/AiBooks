"""AI对话式写作辅助服务."""
from __future__ import annotations

import uuid
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.writing_chat_schema import (
    WritingChatResponse,
    WritingChatStreamChunk,
)
from src.config.settings import get_config
from src.db.models import Chapter, Character, Item, NameFavorite, Synopsis, Worldview, WritingChatHistory
from src.db.session import release_write_lock
from src.services.naming_service import NAME_TYPE_LABELS
from src.utils.logger import get_logger


class WritingChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def _load_context(self, project_id: str, chapter_id: str) -> dict:
        chapter = await self.session.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError("章节不存在")
        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        chars_result = await self.session.execute(
            select(Character).where(Character.project_id == project_id)
        )
        characters = [
            {"name": c.name, "identity": c.identity, "intro": c.intro or ""}
            for c in chars_result.scalars().all()
        ]
        items_result = await self.session.execute(
            select(Item).where(Item.project_id == project_id)
        )
        items = [
            {
                "name": i.name,
                "item_type": i.item_type,
                "key_attrs": i.key_attrs or "",
                "owner_character": i.owner_character or "",
            }
            for i in items_result.scalars().all()
        ]
        fav_result = await self.session.execute(
            select(NameFavorite).where(
                NameFavorite.project_id == project_id,
                NameFavorite.name_type != "character",
            )
        )
        naming_favorites: dict[str, list[str]] = {}
        for fav in fav_result.scalars().all():
            label = NAME_TYPE_LABELS.get(fav.name_type, fav.name_type)
            naming_favorites.setdefault(label, []).append(fav.value)
        return {
            "chapter": chapter,
            "synopsis": synopsis.content if synopsis else "",
            "worldview": worldview.content if worldview else "",
            "characters": characters,
            "items": items,
            "naming_favorites": naming_favorites,
        }

    async def _load_history(self, chapter_id: str, limit: int = 20) -> list[dict]:
        result = await self.session.execute(
            select(WritingChatHistory)
            .where(WritingChatHistory.chapter_id == chapter_id)
            .order_by(WritingChatHistory.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {"role": r.role, "content": r.content}
            for r in reversed(rows)
        ]

    async def list_history(self, chapter_id: str, limit: int = 100) -> list[dict]:
        """列出章节对话历史（按时间正序），供历史查询接口使用."""
        return await self._load_history(chapter_id, limit=limit)

    async def _save_message(
        self, chapter_id: str, role: str, content: str, context_mode: str
    ) -> None:
        entity = WritingChatHistory(
            chat_id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            role=role,
            content=content,
            context_mode=context_mode,
        )
        self.session.add(entity)
        await self.session.commit()

    async def chat(
        self,
        project_id: str,
        chapter_id: str,
        message: str,
        context_mode: str = "selected",
        user_ideas: str = "",
    ) -> WritingChatResponse:
        ctx = await self._load_context(project_id, chapter_id)
        chapter = ctx["chapter"]
        history = await self._load_history(chapter_id)

        await self._save_message(chapter_id, "user", message, context_mode)
        await release_write_lock(self.session)

        result = await self.gateway.call_and_parse(
            module="writing",
            scene="chat",
            params={
                "volume_no": chapter.volume_no,
                "chapter_no": chapter.chapter_no,
                "current_content": chapter.content or "",
                "chapter_synopsis": chapter.title or "",
                "synopsis": ctx["synopsis"],
                "worldview": ctx["worldview"],
                "characters": ctx["characters"],
                "items": ctx["items"],
                "naming_favorites": ctx["naming_favorites"],
                "history": history,
                "message": message,
                "user_ideas": user_ideas,
                "context_mode": context_mode,
                "min_length": get_config().min_ai_content_length,
            },
            project_id=project_id,
            timeout_seconds=get_config().writing_chat_timeout_seconds,
            max_tokens=8192,
        )
        parsed = result.get("parsed", {})
        content = parsed.get("content", "")
        min_len = get_config().min_ai_content_length
        if len(content) < min_len:
            raise ValueError(f"AI回复内容不足{min_len}字")

        await self._save_message(chapter_id, "assistant", content, context_mode)

        return WritingChatResponse(
            content=content,
            suggestion=parsed.get("suggestion", ""),
        )

    async def stream_chat(
        self,
        project_id: str,
        chapter_id: str,
        message: str,
        context_mode: str = "selected",
        user_ideas: str = "",
    ) -> AsyncGenerator[WritingChatStreamChunk, None]:
        yield WritingChatStreamChunk(type="progress", message="正在加载上下文...")
        try:
            response = await self.chat(project_id, chapter_id, message, context_mode, user_ideas)
        except ValueError as e:
            yield WritingChatStreamChunk(type="done", message=f"失败: {e}")
            return
        except Exception as e:
            yield WritingChatStreamChunk(type="done", message=f"AI调用异常: {e}")
            return

        yield WritingChatStreamChunk(type="progress", message="正在生成回复...")
        text = response.content
        step = max(20, len(text) // 20)
        for i in range(0, len(text), step):
            yield WritingChatStreamChunk(type="chunk", content=text[i:i + step])

        yield WritingChatStreamChunk(
            type="done",
            content=text,
            suggestion=response.suggestion,
        )