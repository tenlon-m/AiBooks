"""场景级大纲细化服务."""
from __future__ import annotations

import uuid
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.scene_outline_schema import (
    SceneDto,
    SceneSplitResponse,
    SceneStreamChunk,
    SceneUpdateRequest,
)
from src.config.settings import get_config
from src.db.models import (
    Chapter,
    ChapterScene,
    Character,
    CoolPoint,
    Hook,
    Project,
    Synopsis,
    Worldview,
)
from src.db.session import release_write_lock
from src.utils.logger import get_logger


class SceneOutlineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def _load_chapter_context(self, project_id: str, chapter_id: str) -> dict:
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
        cool_result = await self.session.execute(
            select(CoolPoint).where(
                CoolPoint.project_id == project_id,
                CoolPoint.volume_no == chapter.volume_no,
                CoolPoint.chapter_no == chapter.chapter_no,
            )
        )
        cool_points = [
            {"cool_type": cp.cool_type, "content_desc": cp.content_desc}
            for cp in cool_result.scalars().all()
        ]
        hook_result = await self.session.execute(
            select(Hook).where(
                Hook.project_id == project_id,
                Hook.volume_no == chapter.volume_no,
                Hook.chapter_no == chapter.chapter_no,
            )
        )
        hooks = [
            {"hook_content": h.hook_content}
            for h in hook_result.scalars().all()
        ]
        return {
            "chapter": chapter,
            "synopsis": synopsis.content if synopsis else "",
            "worldview": worldview.content if worldview else "",
            "characters": characters,
            "cool_points": cool_points,
            "hooks": hooks,
        }

    async def split(
        self,
        project_id: str,
        chapter_id: str,
        target_words: int = 3000,
        user_ideas: str = "",
    ) -> SceneSplitResponse:
        ctx = await self._load_chapter_context(project_id, chapter_id)
        chapter = ctx["chapter"]
        await release_write_lock(self.session)

        result = await self.gateway.call_and_parse(
            module="outline",
            scene="scene-split",
            params={
                "chapter_synopsis": chapter.title or "",
                "synopsis": ctx["synopsis"],
                "worldview": ctx["worldview"],
                "characters": ctx["characters"],
                "cool_points": ctx["cool_points"],
                "hooks": ctx["hooks"],
                "target_words": target_words,
                "user_ideas": user_ideas,
                "min_length": get_config().min_ai_content_length,
            },
            project_id=project_id,
            timeout_seconds=get_config().scene_split_timeout_seconds,
        )
        parsed = result.get("parsed", {})
        min_len = get_config().min_ai_content_length
        scenes: list[SceneDto] = []
        for sc in parsed.get("scenes", []):
            key_event = sc.get("key_event", "")
            if len(key_event) < min_len:
                raise ValueError(f"场景{sc.get('scene_order', 0)}关键事件不足{min_len}字")
            scenes.append(SceneDto(
                scene_order=sc.get("scene_order", len(scenes) + 1),
                goal=sc.get("goal", ""),
                characters=sc.get("characters", ""),
                key_event=key_event,
                mood=sc.get("mood", ""),
                est_words=sc.get("est_words", 0),
            ))

        await self._save_scenes(chapter_id, scenes)
        return SceneSplitResponse(scenes=scenes)

    async def _save_scenes(self, chapter_id: str, scenes: list[SceneDto]) -> None:
        existing = await self.session.execute(
            select(ChapterScene).where(ChapterScene.chapter_id == chapter_id)
        )
        for sc in existing.scalars().all():
            await self.session.delete(sc)
        await self.session.flush()

        for sc in scenes:
            entity = ChapterScene(
                scene_id=str(uuid.uuid4()),
                chapter_id=chapter_id,
                scene_order=sc.scene_order,
                goal=sc.goal,
                characters=sc.characters,
                key_event=sc.key_event,
                mood=sc.mood,
                est_words=sc.est_words,
            )
            self.session.add(entity)
            sc.scene_id = entity.scene_id
            sc.chapter_id = chapter_id
        await self.session.commit()

    async def list_scenes(self, chapter_id: str) -> list[SceneDto]:
        result = await self.session.execute(
            select(ChapterScene)
            .where(ChapterScene.chapter_id == chapter_id)
            .order_by(ChapterScene.scene_order)
        )
        return [
            SceneDto(
                scene_id=sc.scene_id,
                chapter_id=sc.chapter_id,
                scene_order=sc.scene_order,
                goal=sc.goal,
                characters=sc.characters or "",
                key_event=sc.key_event,
                mood=sc.mood or "",
                est_words=sc.est_words or 0,
            )
            for sc in result.scalars().all()
        ]

    async def update_scene(self, scene_id: str, req: SceneUpdateRequest) -> SceneDto:
        """更新单个场景（仅覆盖请求中给出的字段）."""
        scene = await self.session.get(ChapterScene, scene_id)
        if not scene:
            raise ValueError("场景不存在")
        if req.scene_order is not None:
            scene.scene_order = req.scene_order
        if req.goal is not None:
            scene.goal = req.goal
        if req.characters is not None:
            scene.characters = req.characters
        if req.key_event is not None:
            scene.key_event = req.key_event
        if req.mood is not None:
            scene.mood = req.mood
        if req.est_words is not None:
            scene.est_words = req.est_words
        await self.session.commit()
        return SceneDto(
            scene_id=scene.scene_id,
            chapter_id=scene.chapter_id,
            scene_order=scene.scene_order,
            goal=scene.goal or "",
            characters=scene.characters or "",
            key_event=scene.key_event or "",
            mood=scene.mood or "",
            est_words=scene.est_words or 0,
        )

    async def delete_scene(self, scene_id: str) -> int:
        """删除单个场景."""
        scene = await self.session.get(ChapterScene, scene_id)
        if not scene:
            raise ValueError("场景不存在")
        await self.session.delete(scene)
        await self.session.commit()
        return 1

    async def stream_split(
        self,
        project_id: str,
        chapter_id: str,
        target_words: int = 3000,
        user_ideas: str = "",
    ) -> AsyncGenerator[SceneStreamChunk, None]:
        yield SceneStreamChunk(type="progress", message="正在细化场景大纲...")
        try:
            response = await self.split(project_id, chapter_id, target_words, user_ideas)
        except ValueError as e:
            yield SceneStreamChunk(type="done", message=f"失败: {e}")
            return
        except Exception as e:
            yield SceneStreamChunk(type="done", message=f"AI调用异常: {e}")
            return

        for sc in response.scenes:
            yield SceneStreamChunk(
                type="chunk",
                content=f"场景{sc.scene_order}: {sc.goal}",
                scene=sc,
                chapter_id=chapter_id,
            )

        yield SceneStreamChunk(
            type="done",
            message=f"共生成{len(response.scenes)}个场景",
        )
    async def _find_unrefined_chapters(self, project_id: str) -> list[Chapter]:
        """查询项目中场景表无记录的章节，按 (volume_no, chapter_no) 升序返回."""
        result = await self.session.execute(
            select(Chapter)
            .outerjoin(ChapterScene, Chapter.chapter_id == ChapterScene.chapter_id)
            .where(Chapter.project_id == project_id, ChapterScene.scene_id.is_(None))
            .order_by(Chapter.volume_no.asc(), Chapter.chapter_no.asc())
        )
        return list(result.scalars().all())

    async def batch_stream_split(
        self,
        project_id: str,
        target_words: int = 3000,
        user_ideas: str = "",
    ) -> AsyncGenerator[SceneStreamChunk, None]:
        """批量逐章生成场景大纲，单章失败隔离不中断全书."""
        project = await self.session.get(Project, project_id)
        if not project:
            yield SceneStreamChunk(type="done", message="项目不存在")
            return

        unrefined = await self._find_unrefined_chapters(project_id)
        total = len(unrefined)
        if total == 0:
            yield SceneStreamChunk(type="done", message="所有章节已细化场景，无需批量处理")
            return

        success_count = 0
        failed_count = 0
        failed_chapters: list[dict] = []

        for idx, chapter in enumerate(unrefined, 1):
            yield SceneStreamChunk(
                type="progress",
                message=f"正在细化第 {idx}/{total} 章：{chapter.title}",
                chapter_id=chapter.chapter_id,
                chapter_title=chapter.title,
                current=idx,
                total=total,
            )
            self.logger.info(f"批量细化第 {idx}/{total} 章：{chapter.title}")
            await release_write_lock(self.session)
            try:
                response = await self.split(
                    project_id, chapter.chapter_id, target_words, user_ideas
                )
                for sc in response.scenes:
                    yield SceneStreamChunk(
                        type="chunk",
                        content=f"场景{sc.scene_order}: {sc.goal}",
                        scene=sc,
                        chapter_id=chapter.chapter_id,
                        chapter_title=chapter.title,
                        current=idx,
                        total=total,
                    )
                success_count += 1
                self.logger.info(
                    f"章 {chapter.title} 完成，{len(response.scenes)} 个场景"
                )
            except ValueError as e:
                failed_count += 1
                failed_chapters.append(
                    {"chapter_id": chapter.chapter_id, "title": chapter.title, "reason": str(e)}
                )
                yield SceneStreamChunk(
                    type="failed",
                    chapter_id=chapter.chapter_id,
                    chapter_title=chapter.title,
                    message=str(e),
                    current=idx,
                    total=total,
                )
                self.logger.warning(f"章 {chapter.title} 失败：{e}")
            except TimeoutError as e:
                failed_count += 1
                failed_chapters.append(
                    {"chapter_id": chapter.chapter_id, "title": chapter.title, "reason": f"AI超时: {e}"}
                )
                yield SceneStreamChunk(
                    type="failed",
                    chapter_id=chapter.chapter_id,
                    chapter_title=chapter.title,
                    message="AI超时",
                    current=idx,
                    total=total,
                )
                self.logger.warning(f"章 {chapter.title} AI超时：{e}")
            except Exception as e:
                failed_count += 1
                failed_chapters.append(
                    {"chapter_id": chapter.chapter_id, "title": chapter.title, "reason": f"异常: {e}"}
                )
                yield SceneStreamChunk(
                    type="failed",
                    chapter_id=chapter.chapter_id,
                    chapter_title=chapter.title,
                    message=str(e),
                    current=idx,
                    total=total,
                )
                self.logger.warning(f"章 {chapter.title} 异常：{e}")

        yield SceneStreamChunk(
            type="done",
            message=f"批量细化完成：成功 {success_count} 章，失败 {failed_count} 章",
            success_count=success_count,
            failed_count=failed_count,
            failed_chapters=failed_chapters,
        )
        self.logger.info(f"批量细化完成：成功 {success_count}，失败 {failed_count}")