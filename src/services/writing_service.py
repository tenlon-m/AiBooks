"""批量撰写服务 - 核心业务，状态机+断点续写+SSE进度."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.ai.gateway import get_gateway
from src.api.schemas.writing_schema import WritingProgressEvent
from src.config.settings import get_config
from src.db.models import (
    AiSource,
    Chapter,
    ChapterOutline,
    Character,
    CharacterRelationship,
    CoolPoint,
    EmotionCurvePoint,
    Hook,
    Item,
    NameFavorite,
    Outline,
    Project,
    SensitiveWord,
    StoryUnit,
    StyleFeature,
    StyleLibrary,
    Synopsis,
    TimelineNode,
    VolumeOutline,
    Worldview,
)
from src.db.session import get_session, release_write_lock
from src.services.item_service import ItemService
from src.services.naming_service import NAME_TYPE_LABELS
from src.utils.creation_logger import log_writing_step
from src.utils.logger import get_logger


class WritingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()
        self.config = get_config()
        self._paused = False
        self._running = False
        self._locked_style: str | None = None

    async def _validate_ai_source_available(self) -> None:
        """校验是否存在可用 AI 源，无则阻止撰写."""
        from sqlalchemy import func
        result = await self.session.execute(
            select(func.count()).select_from(AiSource).where(
                AiSource.enabled == True,
                AiSource.health_status.in_(["healthy", "degraded"]),
            )
        )
        count = result.scalar_one()
        if count > 0:
            return
        total_result = await self.session.execute(
            select(func.count()).select_from(AiSource)
        )
        total = total_result.scalar_one()
        if total == 0:
            raise ValueError("未配置AI源，请先在AI源配置页添加AI源")
        raise ValueError("未检测到可用AI源，请在AI源配置页测试连接后再开始撰写")

    async def _validate_prerequisites(self, project: Project) -> dict[str, Any]:
        """前置条件校验，返回所需上下文."""
        await self._validate_ai_source_available()

        from src.services.outline_service import OutlineService
        outline_service = OutlineService(self.session)
        outline = await outline_service.get_outline(project.project_id)
        if not outline:
            raise ValueError("请先在大纲管理中生成大纲")

        synopsis = await self.session.get(Synopsis, project.project_id)
        worldview = await self.session.get(Worldview, project.project_id)
        if not synopsis:
            raise ValueError("故事梗概未设定")
        if not worldview:
            raise ValueError("世界观未设定")

        chars_result = await self.session.execute(
            select(Character).where(Character.project_id == project.project_id, Character.confirmed == True)
        )
        characters = list(chars_result.scalars().all())
        if not characters:
            raise ValueError("无已确认人物")

        cool_result = await self.session.execute(
            select(CoolPoint).where(CoolPoint.project_id == project.project_id)
        )
        cool_points = list(cool_result.scalars().all())
        hooks_result = await self.session.execute(
            select(Hook).where(Hook.project_id == project.project_id)
        )
        hooks = list(hooks_result.scalars().all())
        if not cool_points or not hooks:
            raise ValueError("爽点/钩子未设定")

        style_features: list[StyleFeature] = []
        style_id = project.style_library_id
        if style_id:
            sl = await self.session.get(StyleLibrary, style_id)
            if not sl or not sl.confirmed:
                raise ValueError("指定的风格库未确认")
            feat_result = await self.session.execute(
                select(StyleFeature).where(StyleFeature.style_library_id == style_id)
            )
            style_features = list(feat_result.scalars().all())

        return {
            "synopsis": synopsis.content,
            "worldview": worldview.content,
            "characters": characters,
            "cool_points": cool_points,
            "hooks": hooks,
            "style_features": style_features,
        }

    async def _ensure_chapters(self, project: Project) -> list[Chapter]:
        """确保章节记录存在，返回按顺序排列的章节列表."""
        existing_result = await self.session.execute(
            select(Chapter).where(Chapter.project_id == project.project_id).order_by(Chapter.volume_no, Chapter.chapter_no)
        )
        chapters = list(existing_result.scalars().all())
        if len(chapters) == project.volume_count * project.chapters_per_volume:
            return chapters

        existing_keys = {(c.volume_no, c.chapter_no) for c in chapters}
        for v in range(1, project.volume_count + 1):
            for c in range(1, project.chapters_per_volume + 1):
                if (v, c) not in existing_keys:
                    ch = Chapter(
                        chapter_id=str(uuid.uuid4()),
                        project_id=project.project_id,
                        volume_no=v,
                        chapter_no=c,
                        title=f"第{v}卷第{c}章",
                        content=None,
                        word_count=0,
                        gen_status="pending",
                        modify_status="none",
                    )
                    self.session.add(ch)
                    chapters.append(ch)
        await self.session.flush()
        chapters.sort(key=lambda c: (c.volume_no, c.chapter_no))
        return chapters

    async def _generate_chapter(
        self,
        project: Project,
        chapter: Chapter,
        ctx: dict[str, Any],
        user_ideas: str = "",
    ) -> str:
        """生成单章内容，以大纲梗概要点为主约束."""
        from src.services.outline_service import OutlineService
        from src.services.auto_supporting_service import AutoSupportingService

        outline_service = OutlineService(self.session)
        chapter_synopsis = await outline_service.get_chapter_synopsis(
            project.project_id, chapter.volume_no, chapter.chapter_no
        )
        if not chapter_synopsis or not chapter_synopsis.strip():
            raise ValueError(
                f"第{chapter.volume_no}卷第{chapter.chapter_no}章大纲梗概要点缺失，请先补充大纲"
            )

        story_unit_context = await self._get_story_unit_context(
            project.project_id, chapter.volume_no, chapter.chapter_no
        )

        auto_supporting = AutoSupportingService(self.session)
        try:
            await auto_supporting.ensure_sufficient_for_writing(
                project.project_id, chapter.volume_no, chapter.chapter_no
            )
        except Exception as e:
            self.logger.warning(f"配角自动生成降级跳过: {e}")

        cool_point = next(
            (cp for cp in ctx["cool_points"] if cp.volume_no == chapter.volume_no and cp.chapter_no == chapter.chapter_no),
            ctx["cool_points"][0],
        )
        hook = next(
            (h for h in ctx["hooks"] if h.volume_no == chapter.volume_no and h.chapter_no == chapter.chapter_no),
            ctx["hooks"][0],
        )

        prev_chapters = await self.session.execute(
            select(Chapter).where(
                Chapter.project_id == project.project_id,
                Chapter.gen_status == "completed",
            ).order_by(Chapter.volume_no, Chapter.chapter_no)
        )
        prev_list = list(prev_chapters.scalars().all())
        prev_summary = ""
        if prev_list:
            recent = prev_list[-3:]
            prev_summary = "\n\n".join(f"第{c.volume_no}卷第{c.chapter_no}章 {c.title}:\n{c.content[:500]}..." for c in recent if c.content)

        items_result = await self.session.execute(
            select(Item).where(Item.project_id == project.project_id)
        )
        items = list(items_result.scalars().all())

        # 作者命名库（命名生成器收藏），注入提示词供正文命名时优先选用
        fav_result = await self.session.execute(
            select(NameFavorite).where(
                NameFavorite.project_id == project.project_id,
                NameFavorite.name_type != "character",
            )
        )
        naming_favorites: dict[str, list[str]] = {}
        for fav in fav_result.scalars().all():
            label = NAME_TYPE_LABELS.get(fav.name_type, fav.name_type)
            naming_favorites.setdefault(label, []).append(fav.value)

        params = {
            "synopsis": ctx["synopsis"],
            "worldview": ctx["worldview"],
            "chapter_synopsis_points": chapter_synopsis,
            "naming_favorites": naming_favorites,
            "characters": [
                {"name": c.name, "identity": c.identity, "intro": c.intro or "", "relation": c.relation or ""}
                for c in ctx["characters"]
            ],
            "cool_point": {"cool_type": cool_point.cool_type, "content_desc": cool_point.content_desc},
            "hook": {
                "hook_content": hook.hook_content,
                "recycle_volume_no": hook.recycle_volume_no,
                "recycle_chapter_no": hook.recycle_chapter_no,
            },
            "prev_summary": prev_summary,
            "style_features": [
                {"dimension": f.dimension, "description": f.description}
                for f in ctx["style_features"]
            ],
            "items": [
                {"name": i.name, "item_type": i.item_type, "key_attrs": i.key_attrs or "", "owner_character": i.owner_character or ""}
                for i in items
            ],
            "volume_no": chapter.volume_no,
            "chapter_no": chapter.chapter_no,
            "words_per_chapter": project.words_per_chapter,
            "user_ideas": user_ideas,
        }

        if story_unit_context:
            params["story_unit_context"] = story_unit_context

        result = await self.gateway.call_and_parse(
            module="writing",
            scene="write-chapter",
            params=params,
            project_id=project.project_id,
            max_tokens=8192,
        )
        parsed = result.get("parsed", {})
        content = parsed.get("content", "")
        title = parsed.get("title", f"第{chapter.volume_no}卷第{chapter.chapter_no}章")
        if not content:
            raise RuntimeError("AI返回内容为空")
        chapter.title = title
        return content

    async def _get_story_unit_context(
        self, project_id: str, volume_no: int, chapter_no: int
    ) -> dict:
        """查询该章节关联的 StoryUnit 链，构建分层上下文；无数据时返回空字典."""
        outline_result = await self.session.execute(
            select(Outline).where(Outline.project_id == project_id)
        )
        outline = outline_result.scalars().first()
        if not outline:
            return {}

        vol_result = await self.session.execute(
            select(VolumeOutline).where(
                VolumeOutline.outline_id == outline.outline_id,
                VolumeOutline.volume_no == volume_no,
            )
        )
        vol = vol_result.scalars().first()
        if not vol:
            return {}

        ch_result = await self.session.execute(
            select(ChapterOutline).where(
                ChapterOutline.volume_outline_id == vol.volume_outline_id,
                ChapterOutline.chapter_no == chapter_no,
            )
        )
        ch_outline = ch_result.scalars().first()
        if not ch_outline or not ch_outline.story_unit_id:
            return {}

        chain: list[dict] = []
        current_id: str | None = ch_outline.story_unit_id
        while current_id:
            unit = await self.session.get(StoryUnit, current_id)
            if not unit:
                break
            chain.append({
                "level_type": unit.level_type,
                "unit_name": unit.unit_name,
                "synopsis": unit.synopsis,
                "narrative_duty": unit.narrative_duty,
            })
            current_id = unit.parent_unit_id

        if not chain:
            return {}

        chain.reverse()
        return {"unit_chain": chain}

    async def start_writing(
        self,
        project_id: str,
        style_library_id: str | None = None,
        progress_callback: Any = None,
        user_ideas: str = "",
        proofread_mode: str = "off",
        proofread_sources: dict | None = None,
    ) -> AsyncGenerator[WritingProgressEvent, None]:
        """启动批量撰写，异步生成进度事件."""
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")

        if style_library_id:
            project.style_library_id = style_library_id
            self._locked_style = style_library_id
        elif not project.style_library_id:
            default_result = await self.session.execute(
                select(StyleLibrary).where(StyleLibrary.build_method == "builtin")
            )
            default_sl = default_result.scalars().first()
            if default_sl:
                project.style_library_id = default_sl.style_library_id

        ctx = await self._validate_prerequisites(project)
        chapters = await self._ensure_chapters(project)
        total = len(chapters)
        project.status = "writing"
        await self.session.flush()

        self._running = True
        self._paused = False

        for idx, chapter in enumerate(chapters):
            if self._paused:
                yield WritingProgressEvent(
                    current_volume=chapter.volume_no,
                    current_chapter=chapter.chapter_no,
                    total_chapters=total,
                    status="paused",
                    completed_ratio=idx / total,
                    message="撰写已暂停",
                )
                return

            if chapter.gen_status == "completed":
                continue

            chapter.gen_status = "writing"
            await self.session.flush()
            # 每章开工前先把上一章的事务提交掉，释放全局写锁，
            # 否则下面 await _generate_chapter 期间（30–60s）写锁持续被本 session 持有，
            # 会阻塞其它端点写入（如大纲批次落库 / save_project），撞 busy_timeout。
            await self.session.commit()

            try:
                content = await self._generate_chapter(project, chapter, ctx, user_ideas)
                word_count = len(content)
                expected = project.words_per_chapter
                tolerance = self.config.writing_words_tolerance
                if word_count < expected * (1 - tolerance):
                    self.logger.warning(
                        f"第{chapter.volume_no}卷第{chapter.chapter_no}章字数偏差过大: {word_count}/{expected}，尝试重新生成"
                    )
                    await release_write_lock(self.session)
                    retry_content = await self._generate_chapter(project, chapter, ctx, user_ideas)
                    retry_wc = len(retry_content)
                    if retry_wc > word_count:
                        content = retry_content
                        word_count = retry_wc
                    if word_count < expected * (1 - tolerance):
                        self.logger.warning(
                            f"第{chapter.volume_no}卷第{chapter.chapter_no}章重试后字数仍不足: {word_count}/{expected}"
                        )
                    else:
                        self.logger.info(
                            f"第{chapter.volume_no}卷第{chapter.chapter_no}章重试后字数达标: {word_count}/{expected}"
                        )

                chapter.content = content
                chapter.word_count = word_count
                chapter.gen_status = "completed"
                chapter.modify_status = "none"
                chapter.last_modified_at = datetime.now(timezone.utc)

                from src.services._chapter_guard import create_auto_version_snapshot
                await create_auto_version_snapshot(self.session, chapter)

                item_service = ItemService(self.session)
                await item_service.extract_and_save(project_id, content, chapter.volume_no, chapter.chapter_no)

                await self._update_character_appearance(
                    project_id, chapter.volume_no, chapter.chapter_no, content
                )

                await self.session.flush()
                # 章末 commit：把本章写盘释放全局写锁。
                # session 配置了 expire_on_commit=False，commit 后 chapter 实例属性仍可读。
                await self.session.commit()
                log_writing_step(project_id, chapter.volume_no, chapter.chapter_no, "completed", 0)

                if proofread_mode != "off" and proofread_sources:
                    await self._run_proofread(
                        project_id, chapter, proofread_mode, proofread_sources
                    )

            except Exception as e:
                self.logger.error(f"第{chapter.volume_no}卷第{chapter.chapter_no}章生成失败: {e}")
                chapter.gen_status = "failed"
                await self.session.flush()
                await self.session.commit()
                log_writing_step(project_id, chapter.volume_no, chapter.chapter_no, "failed", 0, str(e))
                yield WritingProgressEvent(
                    current_volume=chapter.volume_no,
                    current_chapter=chapter.chapter_no,
                    total_chapters=total,
                    status="failed",
                    completed_ratio=idx / total,
                    message=f"第{chapter.volume_no}卷第{chapter.chapter_no}章生成失败: {e}",
                )
                return

            yield WritingProgressEvent(
                current_volume=chapter.volume_no,
                current_chapter=chapter.chapter_no,
                total_chapters=total,
                status="writing",
                completed_ratio=(idx + 1) / total,
                message=f"第{chapter.volume_no}卷第{chapter.chapter_no}章已完成",
            )

        project.status = "completed"
        await self.session.flush()
        await self.session.commit()
        self._running = False
        yield WritingProgressEvent(
            current_volume=0,
            current_chapter=0,
            total_chapters=total,
            status="completed",
            completed_ratio=1.0,
            message="全书撰写完成",
        )

    async def _run_proofread(
        self,
        project_id: str,
        chapter: Chapter,
        proofread_mode: str,
        proofread_sources: dict,
    ) -> None:
        from src.services.proofread_service import ProofreadService

        proofread_service = ProofreadService(self.session)
        try:
            if proofread_mode == "ab":
                result = await proofread_service.proofread_ab(
                    chapter.chapter_id,
                    proofread_sources.get("source_a", ""),
                    proofread_sources.get("source_b", ""),
                )
            elif proofread_mode == "abc":
                result = await proofread_service.proofread_abc(
                    chapter.chapter_id,
                    proofread_sources.get("source_a", ""),
                    proofread_sources.get("source_b", ""),
                    proofread_sources.get("source_c", ""),
                    proofread_sources.get("source_eval", ""),
                )
            else:
                return
            if result.drafts:
                latest_draft = result.drafts[-1]
                await proofread_service.adopt_draft(latest_draft.draft_id)
                await self.session.commit()
        except Exception as e:
            self.logger.warning(
                f"第{chapter.volume_no}卷第{chapter.chapter_no}章接力纠错失败: {e}"
            )

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    async def pause_writing(self, project_id: str) -> bool:
        """标记项目撰写状态为已暂停."""
        project = await self.session.get(Project, project_id)
        if not project:
            return False
        project.status = "paused"
        await self.session.commit()
        self._paused = True
        return True

    async def resume_writing(self, project_id: str, user_ideas: str = "") -> bool:
        """标记项目撰写状态为撰写中，从下一章继续.

        user_ideas 透传至后续 start_writing 的逐章生成调用，作为思路约束注入提示词。
        """
        project = await self.session.get(Project, project_id)
        if not project:
            return False
        project.status = "writing"
        await self.session.commit()
        self._paused = False
        self._user_ideas = user_ideas
        return True

    async def get_progress(self, project_id: str) -> dict:
        """返回撰写进度."""
        project = await self.session.get(Project, project_id)
        if not project:
            return {"completed": 0, "total": 0, "status": "not_found"}
        chapters = await self.list_chapters(project_id)
        completed = sum(1 for c in chapters if c.gen_status == "completed")
        total = len(chapters)
        current = next(
            (c for c in chapters if c.gen_status == "writing"),
            None,
        )
        return {
            "completed": completed,
            "total": total,
            "status": project.status,
            "current_volume": current.volume_no if current else None,
            "current_chapter": current.chapter_no if current else None,
        }

    async def _update_character_appearance(
        self,
        project_id: str,
        volume_no: int,
        chapter_no: int,
        content: str,
    ) -> None:
        """解析章节正文中出场的配角，更新其 appearance_records."""
        import json

        from src.services.character_service import CharacterService
        char_service = CharacterService(self.session)
        all_chars = await char_service.list_by_project(project_id)
        supporting = [
            c for c in all_chars
            if "配角" in c.identity and c.supporting_type == "正式配角"
        ]
        for ch in supporting:
            if ch.name in content:
                records = []
                if ch.appearance_records:
                    try:
                        records = json.loads(ch.appearance_records)
                    except (json.JSONDecodeError, TypeError):
                        records = []
                order = len(records) + 1
                records.append(
                    {"volume_no": volume_no, "chapter_no": chapter_no, "order": order}
                )
                entity = await self.session.get(Character, ch.character_id)
                if entity:
                    entity.appearance_records = json.dumps(records, ensure_ascii=False)
        await self.session.flush()

    def is_word_underfilled(self, word_count: int, words_per_chapter: int) -> bool:
        """字数不足判定纯函数（单一确定性口径）.

        阈值 = words_per_chapter × (1 - writing_fill_tolerance)，严格小于才算不足。
        words_per_chapter <= 0 时不参与判定（返回 False）；负数字数按 0 处理。
        """
        if words_per_chapter <= 0:
            return False
        effective = max(0, word_count or 0)
        threshold = words_per_chapter * (1 - self.config.writing_fill_tolerance)
        return effective < threshold

    async def list_chapters(self, project_id: str) -> list[Chapter]:
        result = await self.session.execute(
            select(Chapter).options(selectinload(Chapter.summary)).where(Chapter.project_id == project_id).order_by(Chapter.volume_no, Chapter.chapter_no)
        )
        chapters = list(result.scalars().all())
        if chapters:
            return chapters
        await self._sync_chapters_from_outline(project_id)
        result = await self.session.execute(
            select(Chapter).options(selectinload(Chapter.summary)).where(Chapter.project_id == project_id).order_by(Chapter.volume_no, Chapter.chapter_no)
        )
        return list(result.scalars().all())

    async def _sync_chapters_from_outline(self, project_id: str) -> None:
        """兜底：chapters 表为空时从 chapter_outlines 同步创建占位记录."""
        import uuid

        outline_result = await self.session.execute(
            select(Outline).where(Outline.project_id == project_id)
        )
        outline = outline_result.scalars().first()
        if not outline:
            return
        vol_result = await self.session.execute(
            select(VolumeOutline).where(VolumeOutline.outline_id == outline.outline_id)
        )
        volumes = list(vol_result.scalars().all())
        if not volumes:
            return
        for vol in volumes:
            ch_result = await self.session.execute(
                select(ChapterOutline).where(ChapterOutline.volume_outline_id == vol.volume_outline_id)
            )
            for ch_outline in ch_result.scalars().all():
                self.session.add(
                    Chapter(
                        chapter_id=str(uuid.uuid4()),
                        project_id=project_id,
                        volume_no=ch_outline.volume_no,
                        chapter_no=ch_outline.chapter_no,
                        title=ch_outline.chapter_name or f"第{ch_outline.chapter_no}章",
                        content=None,
                        word_count=0,
                        gen_status="outlined",
                        modify_status="none",
                    )
                )
        await self.session.commit()

    async def get_chapter(self, chapter_id: str) -> Chapter | None:
        return await self.session.get(Chapter, chapter_id)
    async def save_chapters_batch(
        self,
        project_id: str,
        chapters: list,
    ) -> int:
        """单事务内批量更新已撰写章节内容，中途任一写入失败回滚事务，返回保存数量."""
        from src.api.schemas.writing_schema import ChapterSaveItem
        from datetime import datetime, timezone
        from src.services._chapter_guard import (
            ChapterLockedError,
            assert_chapters_not_locked,
            create_auto_version_snapshot,
        )

        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")

        if not chapters:
            return 0

        chapter_ids = [item.chapter_id for item in chapters]
        await assert_chapters_not_locked(self.session, chapter_ids)

        result = await self.session.execute(
            select(Chapter).where(
                Chapter.project_id == project_id,
                Chapter.chapter_id.in_(chapter_ids),
            )
        )
        existing_map = {ch.chapter_id: ch for ch in result.scalars().all()}

        now = datetime.now(timezone.utc)
        saved = 0
        for item in chapters:
            if not item.new_content or not item.new_content.strip():
                raise ValueError("章节内容不能为空")
            chapter = existing_map.get(item.chapter_id)
            if not chapter:
                raise ValueError("章节不存在")
            if chapter.content != item.new_content:
                await create_auto_version_snapshot(self.session, chapter)
            chapter.content = item.new_content
            chapter.word_count = len(item.new_content)
            chapter.modify_status = "modified"
            chapter.last_modified_at = now
            saved += 1

        await self.session.commit()
        return saved

    async def check_consistency(
        self,
        project_id: str,
        user_ideas: str = "",
        garbled_config: "GarbledConfig | None" = None,
    ):
        """校验已撰写章节与大纲/风格库的一致性，返回 WritingConsistencyResult."""
        from src.services.outline_service import OutlineService
        from src.services.style_library_service import StyleLibraryService
        from src.api.schemas.writing_schema import (
            WritingConsistencyIssue,
            WritingConsistencyResult,
        )
        from src.db.models import Character
        from src.db.session import release_write_lock
        from src.services.garbled_config_service import GarbledConfigService

        if garbled_config is None:
            cfg_svc = GarbledConfigService(self.session)
            garbled_config = await cfg_svc.resolve_effective_config(project_id)

        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")

        chapters_result = await self.session.execute(
            select(Chapter).where(
                Chapter.project_id == project_id,
                Chapter.gen_status == "completed",
            ).order_by(Chapter.volume_no, Chapter.chapter_no)
        )
        chapters = list(chapters_result.scalars().all())
        if not chapters:
            raise ValueError("无已撰写章节")

        outline_service = OutlineService(self.session)
        outline = await outline_service.get_outline(project_id)
        if outline is None:
            raise ValueError("大纲不存在")

        style_service = StyleLibraryService(self.session)
        style_libraries = await style_service.list_all()
        style_features = []
        for sl in style_libraries:
            if sl.confirmed:
                style_features.extend(sl.features)

        chars_result = await self.session.execute(
            select(Character).where(
                Character.project_id == project_id,
                Character.confirmed == True,
            )
        )
        confirmed_chars = list(chars_result.scalars().all())

        sw_result = await self.session.execute(
            select(SensitiveWord).where(SensitiveWord.project_id == project_id)
        )
        sensitive_words = list(sw_result.scalars().all())

        tl_result = await self.session.execute(
            select(TimelineNode).where(TimelineNode.project_id == project_id).order_by(TimelineNode.node_order)
        )
        timeline_nodes = list(tl_result.scalars().all())

        rel_result = await self.session.execute(
            select(CharacterRelationship).where(CharacterRelationship.project_id == project_id)
        )
        char_relationships = list(rel_result.scalars().all())

        ec_result = await self.session.execute(
            select(EmotionCurvePoint).where(EmotionCurvePoint.project_id == project_id).order_by(EmotionCurvePoint.chapter_no)
        )
        emotion_points = list(ec_result.scalars().all())

        outline_chapters = []
        for vol in outline.volumes:
            for ch in vol.chapters:
                outline_chapters.append({
                    "volume_no": vol.volume_no,
                    "chapter_no": ch.chapter_no,
                    "synopsis_points": ch.synopsis_points,
                })

        chapters_payload = [
            {
                "volume_no": c.volume_no,
                "chapter_no": c.chapter_no,
                "title": c.title,
                "content": c.content or "",
            }
            for c in chapters
        ]
        style_features_payload = [
            {"dimension": f.dimension, "description": f.description}
            for f in style_features
        ]

        # 下面是最长 writing_check_consistency_timeout_seconds 的 AI 调用。只要本会话
        # （或调用方）还有未提交的 DML，写锁就会一直被持有到 commit，期间并发的
        # 自动保存 / 网关计数器写回都会撞 database is locked。进入 AI 调用前先结束事务。
        await release_write_lock(self.session)

        try:
            ai_issues, score, summary = await self._batch_check_consistency(
                chapters_payload, outline_chapters, style_features_payload,
                user_ideas, garbled_config, project_id,
            )
        except TimeoutError:
            ai_issues = []
            score = 0
            summary = "AI校验超时，仅展示规则校验结果，建议重试"
        except Exception as e:
            self.logger.warning(f"AI校验异常降级: {e}")
            ai_issues = []
            score = 0
            summary = f"AI校验异常，仅展示规则校验结果：{e}"

        issues = ai_issues + self._rule_check_writing_consistency(
            chapters, outline_chapters, style_features, confirmed_chars,
            sensitive_words, timeline_nodes, char_relationships, emotion_points,
            garbled_config,
        )

        seen: dict[tuple, WritingConsistencyIssue] = {}
        level_order = {"严重": 0, "一般": 1, "轻微": 2}
        for issue in issues:
            key = (issue.volume_no, issue.chapter_no, issue.type)
            if key not in seen or level_order.get(issue.level, 9) < level_order.get(seen[key].level, 9):
                seen[key] = issue
        issues = sorted(
            seen.values(),
            key=lambda x: (level_order.get(x.level, 9), x.volume_no, x.chapter_no),
        )

        text = self._format_consistency_text(score, summary, issues)
        return WritingConsistencyResult(
            score=score,
            summary=summary,
            issues=issues,
            text=text,
        )

    async def _batch_check_consistency(
        self,
        chapters_payload: list[dict],
        outline_chapters: list[dict],
        style_features_payload: list[dict],
        user_ideas: str,
        garbled_config: "GarbledConfig | None",
        project_id: str,
    ) -> tuple[list, int, str]:
        """分批调用 AI 校验一致性，避免超过模型上下文窗口限制.

        按token估算将章节分批，每批独立调用AI校验，最后合并issues和score。
        部分批次失败时仍返回成功批次的结果。
        """
        from src.api.schemas.writing_schema import WritingConsistencyIssue

        SAFE_TOKEN_LIMIT = 25000
        batches: list[list[dict]] = []
        current_batch: list[dict] = []
        current_tokens = 0
        for ch in chapters_payload:
            ch_tokens = max(len(ch["content"]) // 3, 100)
            if current_batch and current_tokens + ch_tokens > SAFE_TOKEN_LIMIT:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0
            current_batch.append(ch)
            current_tokens += ch_tokens
        if current_batch:
            batches.append(current_batch)

        all_issues: list[WritingConsistencyIssue] = []
        all_scores: list[int] = []
        all_summaries: list[str] = []
        batch_errors: list[str] = []

        for idx, batch in enumerate(batches):
            try:
                result = await self.gateway.call_and_parse(
                    module="writing",
                    scene="check-consistency",
                    params={
                        "chapters": batch,
                        "outline_chapters": outline_chapters,
                        "style_features": style_features_payload,
                        "user_ideas": user_ideas,
                        "garbled_config_enabled": garbled_config.enabled if garbled_config else False,
                    },
                    project_id=project_id,
                    timeout_seconds=get_config().writing_check_consistency_timeout_seconds,
                    max_tokens=8192,
                )
                parsed = result.get("parsed", {})
                for iss in parsed.get("issues", []):
                    all_issues.append(WritingConsistencyIssue(
                        level=iss.get("level", "一般"),
                        volume_no=iss.get("volume_no", 0),
                        chapter_no=iss.get("chapter_no", 0),
                        type=iss.get("type", "其他"),
                        detail=iss.get("detail", ""),
                        suggestion=iss.get("suggestion", ""),
                    ))
                all_scores.append(parsed.get("score", 100))
                all_summaries.append(parsed.get("summary", ""))
            except Exception as e:
                self.logger.warning(f"AI校验第{idx+1}/{len(batches)}批异常: {e}")
                batch_errors.append(f"第{idx+1}批: {e}")

        if all_scores:
            score = sum(all_scores) // len(all_scores)
            summary = "；".join(s for s in all_summaries if s)
            if batch_errors:
                summary = f"（{len(batch_errors)}批失败）{summary}"
        else:
            score = 0
            summary = f"AI校验异常，仅展示规则校验结果：{batch_errors[-1] if batch_errors else '未知错误'}"

        return all_issues, score, summary

    @staticmethod
    def _rule_check_writing_consistency(
        chapters: list,
        outline_chapters: list[dict],
        style_features: list,
        confirmed_chars: list,
        sensitive_words: list | None = None,
        timeline_nodes: list | None = None,
        char_relationships: list | None = None,
        emotion_points: list | None = None,
        garbled_config: "GarbledConfig | None" = None,
    ) -> list:
        """确定性规则检查：(1)大纲梗概关键词匹配 (2)风格关键词缺失 (3)人物出场逻辑 (4)敏感词检测
        (5)时间线一致性 (6)角色关系一致性 (7)情感曲线完整性.

        人物出场逻辑采用保守策略：仅检查已确认人物是否在应有章节出场，不尝试
        从正文中提取未知人名（中文人名提取易误报，留给 AI 维度判断）。
        """
        from src.api.schemas.writing_schema import WritingConsistencyIssue

        issues: list[WritingConsistencyIssue] = []
        known_names = {c.name for c in confirmed_chars if c.name}

        outline_map: dict[tuple[int, int], str] = {
            (oc["volume_no"], oc["chapter_no"]): oc.get("synopsis_points", "") or ""
            for oc in outline_chapters
        }

        style_keywords: list[str] = []
        for f in style_features:
            desc = getattr(f, "description", "") or ""
            for w in desc.replace("，", " ").replace("、", " ").split():
                w = w.strip()
                if len(w) >= 2:
                    style_keywords.append(w)

        for ch in chapters:
            key = (ch.volume_no, ch.chapter_no)
            synopsis_points = outline_map.get(key, "")
            content = ch.content or ""

            if synopsis_points:
                keywords = [
                    w.strip()
                    for w in synopsis_points.replace("，", " ").replace("、", " ").split()
                    if len(w.strip()) >= 2
                ]
                missed = [kw for kw in keywords[:5] if kw and kw not in content]
                if missed and len(missed) >= 3:
                    issues.append(WritingConsistencyIssue(
                        level="一般",
                        volume_no=ch.volume_no,
                        chapter_no=ch.chapter_no,
                        type="偏离大纲",
                        detail=f"章节内容与大纲梗概要点关键词匹配度低，缺失关键词: {('、'.join(missed[:3]))}",
                        suggestion="对照大纲梗概要点补充对应情节",
                    ))

            if style_keywords and content:
                hit = sum(1 for kw in style_keywords if kw in content)
                ratio = hit / len(style_keywords) if style_keywords else 0
                if ratio < 0.05 and len(style_keywords) >= 6:
                    issues.append(WritingConsistencyIssue(
                        level="轻微",
                        volume_no=ch.volume_no,
                        chapter_no=ch.chapter_no,
                        type="风格偏差",
                        detail=f"风格关键词命中率过低（{ratio:.0%}），可能与风格库特征偏离",
                        suggestion="对照风格库特征调整用词与句式",
                    ))

            if known_names and content:
                appeared = [name for name in known_names if name and name in content]
                if not appeared and synopsis_points:
                    for name in known_names:
                        if name and name in synopsis_points:
                            issues.append(WritingConsistencyIssue(
                                level="一般",
                                volume_no=ch.volume_no,
                                chapter_no=ch.chapter_no,
                                type="人物出场",
                                detail=f"大纲梗概要点提及人物「{name}」但章节正文未出现",
                                suggestion="补充该人物在本章的出场或交代其去向",
                            ))
                            break

            if sensitive_words and content:
                for sw in sensitive_words:
                    if sw.word and sw.word in content:
                        issues.append(WritingConsistencyIssue(
                            level="严重",
                            volume_no=ch.volume_no,
                            chapter_no=ch.chapter_no,
                            type="敏感词",
                            detail=f"章节包含敏感词「{sw.word}」（分类：{sw.category}）",
                            suggestion=sw.suggestion or "请替换或删除该敏感词",
                        ))

            if garbled_config and garbled_config.enabled and content:
                from src.services.garbled_normalizer import GarbledNormalizer

                normalizer = GarbledNormalizer()
                garbled_issues = normalizer.detect_only(content, garbled_config)
                for gi in garbled_issues:
                    issues.append(WritingConsistencyIssue(
                        level=gi.level,
                        volume_no=ch.volume_no,
                        chapter_no=ch.chapter_no,
                        type=gi.category,
                        detail=f"位置{gi.position}：{gi.category}",
                        suggestion=gi.suggestion,
                    ))

        if timeline_nodes and known_names and chapters:
            ch_by_id = {ch.chapter_id: ch for ch in chapters if hasattr(ch, "chapter_id")}
            for tn in timeline_nodes:
                tn_chars = [n.strip() for n in (tn.characters or "").split(",") if n.strip()]
                tn_ch_ids = [cid.strip() for cid in (tn.chapter_ids or "").split(",") if cid.strip()]
                for cname in tn_chars:
                    if cname not in known_names:
                        issues.append(WritingConsistencyIssue(
                            level="一般",
                            volume_no=0,
                            chapter_no=0,
                            type="时间线人物",
                            detail=f"时间线节点「{tn.event_name}」引用人物「{cname}」不在已确认人物列表中",
                            suggestion="将该人物加入人物列表或修正时间线节点",
                        ))
                for cid in tn_ch_ids:
                    ch_obj = ch_by_id.get(cid)
                    if ch_obj and tn_chars:
                        ch_content = ch_obj.content or ""
                        missing_in_ch = [n for n in tn_chars if n and n not in ch_content]
                        if missing_in_ch:
                            issues.append(WritingConsistencyIssue(
                                level="轻微",
                                volume_no=ch_obj.volume_no,
                                chapter_no=ch_obj.chapter_no,
                                type="时间线人物",
                                detail=f"时间线节点「{tn.event_name}」人物未在本章出现：{('、'.join(missing_in_ch))}",
                                suggestion="补充人物出场或调整时间线节点关联章节",
                            ))

        if char_relationships and known_names and chapters:
            char_id_to_name = {c.character_id: c.name for c in confirmed_chars if hasattr(c, "character_id")}
            for rel in char_relationships:
                src_name = char_id_to_name.get(rel.source_character_id, "")
                tgt_name = char_id_to_name.get(rel.target_character_id, "")
                if not src_name or not tgt_name:
                    continue
                co_appeared = any(
                    src_name in (ch.content or "") and tgt_name in (ch.content or "")
                    for ch in chapters
                )
                if not co_appeared:
                    issues.append(WritingConsistencyIssue(
                        level="轻微",
                        volume_no=0,
                        chapter_no=0,
                        type="角色关系",
                        detail=f"角色关系「{src_name}→{tgt_name}（{rel.relation_type}）」未在任何章节中共同出场",
                        suggestion="安排两个角色在至少一章中共同出场，或调整关系设定",
                    ))

        if emotion_points and chapters:
            ec_chapter_ids = {ep.chapter_id for ep in emotion_points if hasattr(ep, "chapter_id")}
            for ch in chapters:
                if hasattr(ch, "chapter_id") and ch.chapter_id not in ec_chapter_ids and (ch.content or "").strip():
                    issues.append(WritingConsistencyIssue(
                        level="轻微",
                        volume_no=ch.volume_no,
                        chapter_no=ch.chapter_no,
                        type="情感曲线",
                        detail="已撰写章节缺少情感曲线数据点",
                        suggestion="在情感曲线页面为该章节添加情感数据点",
                    ))

        return issues

    @staticmethod
    def _format_consistency_text(score: int, summary: str, issues: list) -> str:
        """生成便于整段复制的纯文本报告."""
        lines = [
            f"撰写一致性评分：{score} / 100",
            f"总体评价：{summary}" if summary else "",
            "",
        ]
        if issues:
            level_order = {"严重": 0, "一般": 1, "轻微": 2}
            sorted_issues = sorted(
                issues,
                key=lambda x: (
                    level_order.get(x.level, 9),
                    x.volume_no,
                    x.chapter_no,
                ),
            )
            lines.append(f"发现问题：{len(sorted_issues)} 条")
            lines.append("=" * 44)
            for idx, issue in enumerate(sorted_issues, 1):
                lines.append(
                    f"[{idx}]【{issue.level}】"
                    f"第{issue.volume_no}卷第{issue.chapter_no}章"
                    f"（{issue.type}）"
                )
                lines.append(f"    问题：{issue.detail}")
                if issue.suggestion:
                    lines.append(f"    建议：{issue.suggestion}")
                lines.append("")
        else:
            lines.append("未发现问题：已撰写章节与大纲、风格库基本一致。")
            lines.append("")
        return "\n".join(lines)
    async def repair_writing_stream(
        self,
        project_id: str,
        issues: list,
        repair_scope: str = "all",
        garbled_config: "GarbledConfig | None" = None,
    ) -> AsyncGenerator:
        """SSE 流式逐章修复撰写内容."""
        from src.api.schemas.writing_schema import WritingRepairStreamChunk
        from src.db.session import release_write_lock
        from src.services.outline_service import OutlineService
        from src.services.style_library_service import StyleLibraryService
        from src.services.garbled_config_service import GarbledConfigService
        from src.services.garbled_normalizer import GarbledNormalizer
        from src.services._chapter_guard import create_auto_version_snapshot

        if garbled_config is None:
            cfg_svc = GarbledConfigService(self.session)
            garbled_config = await cfg_svc.resolve_effective_config(project_id)
        normalizer = GarbledNormalizer()

        project = await self.session.get(Project, project_id)
        if not project:
            yield WritingRepairStreamChunk(type="error", message="项目不存在")
            return
        if not issues:
            yield WritingRepairStreamChunk(type="error", message="问题清单为空")
            return

        try:
            await self._validate_prerequisites(project)
        except ValueError as e:
            yield WritingRepairStreamChunk(type="error", message=str(e))
            return

        scope_filter = {"all": None, "severe": "严重", "general": "一般"}
        target_level = scope_filter.get(repair_scope)

        issue_chapters: set[tuple[int, int]] = set()
        for issue in issues:
            if target_level and issue.level != target_level:
                if repair_scope == "general" and issue.level == "严重":
                    pass
                elif repair_scope == "severe":
                    continue
            if issue.volume_no and issue.chapter_no:
                issue_chapters.add((issue.volume_no, issue.chapter_no))

        target_chapters = sorted(issue_chapters)
        total = len(target_chapters)
        if total == 0:
            yield WritingRepairStreamChunk(type="error", message="未找到需修复的章节")
            return

        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        chars_result = await self.session.execute(
            select(Character).where(
                Character.project_id == project_id,
                Character.confirmed == True,
            )
        )
        confirmed_chars = list(chars_result.scalars().all())

        outline_service = OutlineService(self.session)
        outline = await outline_service.get_outline(project_id)
        outline_map: dict[tuple[int, int], str] = {}
        if outline:
            for vol in outline.volumes:
                for ch in vol.chapters:
                    outline_map[(vol.volume_no, ch.chapter_no)] = ch.synopsis_points or ""

        style_service = StyleLibraryService(self.session)
        style_libraries = await style_service.list_all()
        style_features = []
        for sl in style_libraries:
            if sl.confirmed:
                style_features.extend(sl.features)
        style_features_payload = [
            {"dimension": f.dimension, "description": f.description}
            for f in style_features
        ]

        success = 0
        failed = 0
        skipped = 0

        for idx, (v, c) in enumerate(target_chapters, 1):
            ch_issues = [
                {"level": i.level, "type": i.type, "detail": i.detail, "suggestion": i.suggestion}
                for i in issues if i.volume_no == v and i.chapter_no == c
            ]
            yield WritingRepairStreamChunk(
                type="progress", volume_no=v, chapter_no=c, done=idx, total=total
            )

            ch_result = await self.session.execute(
                select(Chapter).where(
                    Chapter.project_id == project_id,
                    Chapter.volume_no == v,
                    Chapter.chapter_no == c,
                )
            )
            chapter = ch_result.scalar_one_or_none()
            if not chapter or not chapter.content:
                skipped += 1
                yield WritingRepairStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    status="跳过", fail_reason="章节不存在或无内容",
                )
                continue
            if chapter.is_locked:
                skipped += 1
                yield WritingRepairStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    status="跳过", fail_reason="章节已锁定，请先解锁",
                )
                continue

            prev_tail = ""
            if c > 1:
                prev_result = await self.session.execute(
                    select(Chapter).where(
                        Chapter.project_id == project_id,
                        Chapter.volume_no == v,
                        Chapter.chapter_no == c - 1,
                    )
                )
                prev_ch = prev_result.scalar_one_or_none()
                if prev_ch and prev_ch.content:
                    prev_tail = prev_ch.content[-500:]

            chapter_synopsis = outline_map.get((v, c), "")

            await release_write_lock(self.session)

            try:
                result = await self.gateway.call_and_parse(
                    module="writing",
                    scene="repair-writing",
                    params={
                        "synopsis": synopsis.content if synopsis else "",
                        "worldview": worldview.content if worldview else "",
                        "characters": [
                            {"name": ch.name, "identity": ch.identity, "intro": ch.intro or ""}
                            for ch in confirmed_chars
                        ],
                        "outline_chapters": [
                            {"volume_no": k[0], "chapter_no": k[1], "synopsis_points": val}
                            for k, val in outline_map.items()
                        ],
                        "style_features": style_features_payload,
                        "volume_no": v,
                        "chapter_no": c,
                        "chapter_synopsis": chapter_synopsis,
                        "chapter_content": chapter.content,
                        "prev_chapter_tail": prev_tail,
                        "chapter_issues": ch_issues,
                        "garbled_config_enabled": garbled_config.enabled,
                    },
                    project_id=project_id,
                    timeout_seconds=get_config().writing_repair_timeout_seconds,
                )
                parsed = result.get("parsed", {})
            except TimeoutError:
                skipped += 1
                yield WritingRepairStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    status="跳过", fail_reason="AI 超时",
                )
                continue
            except Exception as e:
                skipped += 1
                yield WritingRepairStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    status="跳过", fail_reason=str(e),
                )
                continue

            content_new = parsed.get("content_new", "")
            if not content_new or len(content_new) < 50:
                skipped += 1
                yield WritingRepairStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    status="跳过", fail_reason="AI 返回内容过短",
                )
                continue

            original_len = len(chapter.content) if chapter.content else 0
            min_required_len = int(original_len * 0.8)
            if original_len > 0 and len(content_new) < min_required_len:
                skipped += 1
                yield WritingRepairStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    status="跳过",
                    fail_reason=(
                        f"修复后字数 {len(content_new)} 不足原文 {original_len} 的 80%"
                        f"（最低要求 {min_required_len} 字），保留原文不覆盖"
                    ),
                )
                continue

            char_repair_stat = None
            char_repair_details = None
            if garbled_config.enabled:
                content_new, stat = normalizer.detect_and_normalize(
                    content_new, garbled_config
                )
                if len(content_new) < 50:
                    skipped += 1
                    yield WritingRepairStreamChunk(
                        type="chapter_skip", volume_no=v, chapter_no=c,
                        status="跳过", fail_reason="规范化后内容过短",
                    )
                    continue
                char_repair_stat = stat.model_dump()
                char_repair_details = [d.model_dump() for d in stat.details]

            await create_auto_version_snapshot(self.session, chapter)
            chapter.content = content_new
            chapter.word_count = len(content_new)
            chapter.modify_status = "repaired"
            await self.session.commit()

            success += 1
            yield WritingRepairStreamChunk(
                type="chapter_done", volume_no=v, chapter_no=c,
                status="已修复",
                char_repair_stat=char_repair_stat,
                char_repair_details=char_repair_details,
            )

        yield WritingRepairStreamChunk(
            type="completed",
            success=success,
            failed=failed,
            skipped=skipped,
        )
    async def fill_writing_stream(
        self, project_id: str, garbled_config: "GarbledConfig | None" = None
    ) -> AsyncGenerator:
        """SSE 流式逐章补写字数不足的已撰写章节."""
        from src.api.schemas.writing_schema import WritingFillStreamChunk
        from src.db.session import release_write_lock
        from src.services._chapter_guard import create_auto_version_snapshot
        from src.services.outline_service import OutlineService
        from src.services.style_library_service import StyleLibraryService
        from src.services.garbled_config_service import GarbledConfigService
        from src.services.garbled_normalizer import GarbledNormalizer

        if garbled_config is None:
            cfg_svc = GarbledConfigService(self.session)
            garbled_config = await cfg_svc.resolve_effective_config(project_id)
        normalizer = GarbledNormalizer()

        project = await self.session.get(Project, project_id)
        if not project:
            yield WritingFillStreamChunk(type="error", message="项目不存在")
            return

        try:
            await self._validate_prerequisites(project)
        except ValueError as e:
            yield WritingFillStreamChunk(type="error", message=str(e))
            return

        words_per_chapter = project.words_per_chapter
        if words_per_chapter <= 0:
            yield WritingFillStreamChunk(
                type="completed", success=0, skipped=0, still_underfilled=0,
                message="项目未设置目标字数，无需补写",
            )
            return

        ch_result = await self.session.execute(
            select(Chapter)
            .where(
                Chapter.project_id == project_id,
                Chapter.gen_status == "completed",
            )
            .order_by(Chapter.volume_no, Chapter.chapter_no)
        )
        all_completed = list(ch_result.scalars().all())
        underfilled_chapters = [
            ch for ch in all_completed
            if ch.content and self.is_word_underfilled(ch.word_count, words_per_chapter)
        ]
        total = len(underfilled_chapters)
        if total == 0:
            yield WritingFillStreamChunk(
                type="completed", success=0, skipped=0, still_underfilled=0,
                message="当前无字数不足章节",
            )
            return

        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        chars_result = await self.session.execute(
            select(Character).where(
                Character.project_id == project_id,
                Character.confirmed == True,
            )
        )
        confirmed_chars = list(chars_result.scalars().all())

        outline_service = OutlineService(self.session)
        outline = await outline_service.get_outline(project_id)
        outline_map: dict[tuple[int, int], str] = {}
        if outline:
            for vol in outline.volumes:
                for ch in vol.chapters:
                    outline_map[(vol.volume_no, ch.chapter_no)] = ch.synopsis_points or ""

        style_service = StyleLibraryService(self.session)
        style_libraries = await style_service.list_all()
        style_features = []
        for sl in style_libraries:
            if sl.confirmed:
                style_features.extend(sl.features)
        style_features_payload = [
            {"dimension": f.dimension, "description": f.description}
            for f in style_features
        ]

        success = 0
        skipped = 0
        still_underfilled = 0
        max_retries = get_config().writing_fill_max_retries

        for idx, chapter in enumerate(underfilled_chapters, 1):
            v, c = chapter.volume_no, chapter.chapter_no
            yield WritingFillStreamChunk(
                type="progress", volume_no=v, chapter_no=c, done=idx, total=total,
            )

            if chapter.is_locked:
                skipped += 1
                yield WritingFillStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    fail_reason="章节已锁定，请先解锁",
                )
                continue
            if not chapter.content:
                skipped += 1
                yield WritingFillStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    fail_reason="无正文",
                )
                continue

            prev_tail = ""
            if c > 1:
                prev_result = await self.session.execute(
                    select(Chapter).where(
                        Chapter.project_id == project_id,
                        Chapter.volume_no == v,
                        Chapter.chapter_no == c - 1,
                    )
                )
                prev_ch = prev_result.scalar_one_or_none()
                if prev_ch and prev_ch.content:
                    prev_tail = prev_ch.content[-500:]

            chapter_synopsis = outline_map.get((v, c), "")
            word_count_before = chapter.word_count or len(chapter.content)

            best_content = chapter.content
            best_len = len(best_content)
            retries = 0
            skip_reason = ""

            while True:
                current_words = len(best_content)
                min_add_words = max(1, words_per_chapter - current_words)

                await release_write_lock(self.session)

                try:
                    result = await self.gateway.call_and_parse(
                        module="writing",
                        scene="supplement",
                        params={
                            "synopsis": synopsis.content if synopsis else "",
                            "worldview": worldview.content if worldview else "",
                            "characters": [
                                {"name": ch.name, "identity": ch.identity, "intro": ch.intro or ""}
                                for ch in confirmed_chars
                            ],
                            "outline_chapters": [
                                {"volume_no": k[0], "chapter_no": k[1], "synopsis_points": val}
                                for k, val in outline_map.items()
                            ],
                            "style_features": style_features_payload,
                            "volume_no": v,
                            "chapter_no": c,
                            "chapter_synopsis": chapter_synopsis,
                            "chapter_content": best_content,
                            "prev_chapter_tail": prev_tail,
                            "current_words": current_words,
                            "target_words": words_per_chapter,
                            "min_add_words": min_add_words,
                            "garbled_config_enabled": garbled_config.enabled,
                        },
                        project_id=project_id,
                        timeout_seconds=get_config().writing_fill_timeout_seconds,
                        max_tokens=8192,
                    )
                    parsed = result.get("parsed", {})
                except TimeoutError:
                    skip_reason = "AI 超时"
                    break
                except Exception as e:
                    skip_reason = str(e)
                    break

                new_content = parsed.get("content", "")
                if not new_content or len(new_content) < 50:
                    skip_reason = "AI 返回内容过短"
                    break

                max_accept = int(words_per_chapter * 1.3)
                if len(new_content) > max_accept:
                    retries += 1
                    if retries >= max_retries:
                        break
                    continue

                if len(new_content) > best_len:
                    best_content = new_content
                    best_len = len(new_content)

                fill_threshold = int(words_per_chapter * (1 - self.config.writing_fill_tolerance))
                if best_len >= fill_threshold:
                    break

                retries += 1
                if retries >= max_retries:
                    break

            if skip_reason and best_content == chapter.content:
                skipped += 1
                yield WritingFillStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    fail_reason=skip_reason,
                )
                continue

            char_repair_stat = None
            if garbled_config.enabled:
                best_content, stat = normalizer.detect_and_normalize(
                    best_content, garbled_config
                )
                if len(best_content) < 50:
                    skipped += 1
                    yield WritingFillStreamChunk(
                        type="chapter_skip", volume_no=v, chapter_no=c,
                        fail_reason="规范化后内容过短",
                    )
                    continue
                char_repair_stat = stat.model_dump()

            await create_auto_version_snapshot(self.session, chapter)
            chapter.content = best_content
            chapter.word_count = len(best_content)
            chapter.modify_status = "supplemented"
            await self.session.commit()

            success += 1
            if best_len >= words_per_chapter:
                yield WritingFillStreamChunk(
                    type="chapter_done", volume_no=v, chapter_no=c,
                    status="已补写",
                    word_count_before=word_count_before,
                    word_count_after=best_len,
                    retries=retries,
                    char_repair_stat=char_repair_stat,
                )
            else:
                still_underfilled += 1
                yield WritingFillStreamChunk(
                    type="chapter_done", volume_no=v, chapter_no=c,
                    status="仍字数不足",
                    word_count_before=word_count_before,
                    word_count_after=best_len,
                    retries=retries,
                    char_repair_stat=char_repair_stat,
                )

        yield WritingFillStreamChunk(
            type="completed",
            success=success,
            skipped=skipped,
            still_underfilled=still_underfilled,
        )