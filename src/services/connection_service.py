"""章节间衔接优化服务."""
from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.connection_schema import (
    ConnectionAnalyzeResponse,
    ConnectionIssue,
    ConnectionStreamChunk,
)
from src.config.settings import get_config
from src.db.models import Chapter, Character
from src.db.session import release_write_lock
from src.utils.logger import get_logger


class ConnectionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    def _extract_ending(self, content: str, length: int = 500) -> str:
        if not content:
            return ""
        return content[-length:] if len(content) > length else content

    def _extract_start(self, content: str, length: int = 500) -> str:
        if not content:
            return ""
        return content[:length] if len(content) > length else content

    async def _load_characters(self, project_id: str) -> list[dict]:
        result = await self.session.execute(
            select(Character).where(Character.project_id == project_id)
        )
        return [
            {"name": c.name, "identity": c.identity, "intro": c.intro or ""}
            for c in result.scalars().all()
        ]

    async def analyze(
        self,
        project_id: str,
        prev_chapter_id: str,
        next_chapter_id: str,
        user_ideas: str = "",
    ) -> ConnectionAnalyzeResponse:
        prev_chapter = await self.session.get(Chapter, prev_chapter_id)
        next_chapter = await self.session.get(Chapter, next_chapter_id)
        if not prev_chapter:
            raise ValueError("前一章节不存在")
        if not next_chapter:
            raise ValueError("后一章节不存在")

        characters = await self._load_characters(project_id)
        await release_write_lock(self.session)

        result = await self.gateway.call_and_parse(
            module="writing",
            scene="connection",
            params={
                "prev_ending": self._extract_ending(prev_chapter.content or ""),
                "next_start": self._extract_start(next_chapter.content or ""),
                "prev_synopsis": prev_chapter.title or "",
                "next_synopsis": next_chapter.title or "",
                "characters": characters,
                "user_ideas": user_ideas,
                "min_length": get_config().min_ai_content_length,
            },
            project_id=project_id,
            timeout_seconds=get_config().connection_analyze_timeout_seconds,
        )
        parsed = result.get("parsed", {})
        issues = [
            ConnectionIssue(
                type=it.get("type", ""),
                detail=it.get("detail", ""),
                suggestion=it.get("suggestion", ""),
            )
            for it in parsed.get("issues", [])
        ]
        transition = parsed.get("transition", "")
        min_len = get_config().min_ai_content_length
        if transition and len(transition) < min_len:
            raise ValueError(f"衔接段落内容不足{min_len}字")

        return ConnectionAnalyzeResponse(
            score=parsed.get("score", 0),
            issues=issues,
            transition=transition,
            summary=parsed.get("summary", ""),
        )

    async def stream_analyze(
        self,
        project_id: str,
        prev_chapter_id: str,
        next_chapter_id: str,
        user_ideas: str = "",
    ) -> AsyncGenerator[ConnectionStreamChunk, None]:
        yield ConnectionStreamChunk(type="progress", message="正在分析章节衔接...")
        try:
            response = await self.analyze(project_id, prev_chapter_id, next_chapter_id, user_ideas)
        except ValueError as e:
            yield ConnectionStreamChunk(type="done", message=f"失败: {e}")
            return
        except Exception as e:
            yield ConnectionStreamChunk(type="done", message=f"AI调用异常: {e}")
            return

        yield ConnectionStreamChunk(
            type="done",
            content=response.transition,
            message=f"衔接分数: {response.score}",
        )