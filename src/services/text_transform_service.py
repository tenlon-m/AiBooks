"""续写/扩写/缩写服务."""
from __future__ import annotations

from typing import AsyncGenerator, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.text_transform_schema import (
    TextTransformResponse,
    TextTransformStreamChunk,
)
from src.config.settings import get_config
from src.db.models import Chapter, Character, NameFavorite, Synopsis, Worldview
from src.db.session import release_write_lock
from src.services.naming_service import NAME_TYPE_LABELS
from src.utils.logger import get_logger
from sqlalchemy import select


class TextTransformService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def _load_chapter_context(self, project_id: str, chapter_id: str) -> dict:
        if not chapter_id:
            return {
                "chapter_synopsis": "",
                "characters": [],
                "synopsis": "",
                "worldview": "",
                "naming_favorites": {},
            }
        chapter = await self.session.get(Chapter, chapter_id)
        if not chapter:
            return {
                "chapter_synopsis": "",
                "characters": [],
                "synopsis": "",
                "worldview": "",
                "naming_favorites": {},
            }
        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        chars_result = await self.session.execute(
            select(Character).where(Character.project_id == project_id)
        )
        characters = [
            {"name": c.name, "identity": c.identity, "intro": c.intro or ""}
            for c in chars_result.scalars().all()
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
            "chapter_synopsis": chapter.title or "",
            "characters": characters,
            "synopsis": synopsis.content if synopsis else "",
            "worldview": worldview.content if worldview else "",
            "naming_favorites": naming_favorites,
        }

    async def transform(
        self,
        project_id: str,
        scene: Literal["continue", "expand", "shrink"],
        content: str,
        chapter_id: str = "",
        direction: str = "",
        target_words: int = 0,
        user_ideas: str = "",
    ) -> TextTransformResponse:
        ctx = await self._load_chapter_context(project_id, chapter_id)
        await release_write_lock(self.session)

        result = await self.gateway.call_and_parse(
            module="writing",
            scene=scene,
            params={
                "content": content,
                "direction": direction,
                "target_words": target_words,
                "chapter_synopsis": ctx["chapter_synopsis"],
                "synopsis": ctx["synopsis"],
                "worldview": ctx["worldview"],
                "characters": ctx["characters"],
                "naming_favorites": ctx["naming_favorites"],
                "user_ideas": user_ideas,
                "min_length": get_config().min_ai_content_length,
            },
            project_id=project_id,
            timeout_seconds=get_config().text_transform_timeout_seconds,
        )
        parsed = result.get("parsed", {})
        out_content = parsed.get("content", "")
        min_len = get_config().min_ai_content_length
        if len(out_content) < min_len:
            raise ValueError(f"处理结果内容不足{min_len}字")

        return TextTransformResponse(
            content=out_content,
            word_count=parsed.get("word_count", len(out_content)),
        )

    async def stream_transform(
        self,
        project_id: str,
        scene: Literal["continue", "expand", "shrink"],
        content: str,
        chapter_id: str = "",
        direction: str = "",
        target_words: int = 0,
        user_ideas: str = "",
    ) -> AsyncGenerator[TextTransformStreamChunk, None]:
        yield TextTransformStreamChunk(type="progress", message="正在处理文本...")
        try:
            response = await self.transform(
                project_id, scene, content, chapter_id, direction, target_words, user_ideas
            )
        except ValueError as e:
            yield TextTransformStreamChunk(type="done", message=f"失败: {e}")
            return
        except Exception as e:
            yield TextTransformStreamChunk(type="done", message=f"AI调用异常: {e}")
            return

        text = response.content
        step = max(20, len(text) // 20)
        for i in range(0, len(text), step):
            yield TextTransformStreamChunk(type="chunk", content=text[i:i + step])

        yield TextTransformStreamChunk(type="done", content=text)