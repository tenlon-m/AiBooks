"""大纲管理服务 - AI生成/读取/保存/删除 + 结构校验 + 字数校验."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.character_schema import CharacterDto
from src.api.schemas.outline_schema import (
    ChapterDraft,
    ChapterOutlineDto,
    FillAppearingRequest,
    FillAppearingResponse,
    FillAppearingResultItem,
    OutlineBatchGenerateRequest,
    OutlineCheckRequest,
    OutlineConsistencyIssue,
    OutlineConsistencyResult,
    OutlineDto,
    OutlineDraft,
    OutlineGenerateRequest,
    OutlineRepairRequest,
    OutlineSaveRequest,
    RepairStreamChunk,
    VolumeOutlineDto,
)
from src.config.settings import get_config
from src.db.models import Chapter, ChapterOutline, ChapterScene, Outline, Project, Synopsis, VolumeOutline, Worldview
from src.db.session import release_write_lock
from src.services.auto_supporting_service import AutoSupportingService
from src.services.character_service import CharacterService
from src.services.naming_service import NamingService
from src.services.outline_builder import OutlineBuilder
from src.services.scene_outline_service import SceneOutlineService
from src.utils.logger import get_logger


class OutlineService:
    """大纲管理服务."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.builder = OutlineBuilder()
        self.character_service = CharacterService(session)
        self.auto_supporting = AutoSupportingService(session)
        self.scene_service = SceneOutlineService(session)

    async def generate_outline(
        self, project_id: str, req: OutlineGenerateRequest
    ) -> OutlineDto:
        """AI 生成大纲."""
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")

        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        if not synopsis or not synopsis.content.strip():
            raise ValueError("请先输入故事梗概")
        if not worldview or not worldview.content.strip():
            raise ValueError("请先输入世界观")

        confirmed = await self.character_service.list_confirmed(project_id)
        if not confirmed:
            raise ValueError("请先确认人物清单")

        existing = await self.get_outline(project_id)
        if existing and not req.force_overwrite:
            raise ValueError("已存在大纲，需确认覆盖")

        # 进入 AI 调用前结束事务、释放 SQLite 锁。
        # 下面 ensure_sufficient_for_outline / build_and_call 会产生多次网关调用
        # （单次最长 outline_generate_timeout_seconds）。只要本会话（或调用方）
        # 存在未提交的 DML，写锁就会一直被持有到 commit，期间并发写入的自动保存
        # 与网关计数器写回都会撞 database is locked。
        await release_write_lock(self.session)

        await self.auto_supporting.ensure_sufficient_for_outline(
            project_id, synopsis.content, worldview.content, confirmed
        )
        confirmed = await self.character_service.list_confirmed(project_id)

        # 配角生成本身会写库，进入 300s 量级的大纲生成前再释放一次
        await release_write_lock(self.session)

        naming_favorites = await NamingService(self.session).list_favorites_grouped(project_id)

        draft = await self.builder.build_and_call(
            synopsis=synopsis.content,
            worldview=worldview.content,
            characters=confirmed,
            volume_count=project.volume_count,
            chapters_per_volume=project.chapters_per_volume,
            words_per_chapter=project.words_per_chapter,
            project_id=project_id,
            timeout_seconds=get_config().outline_generate_timeout_seconds,
            user_ideas=req.user_ideas,
            naming_favorites=naming_favorites,
        )

        if not self._validate_structure(draft, project):
            raise ValueError("大纲结构与创作参数不匹配")

        character_names = [c.name for c in confirmed if c.name]
        for vol in draft.volumes:
            self._auto_fill_appearing(vol.chapters, character_names)

        dto = await self._write_outline(project_id, draft, gen_status="已生成", source="AI生成")
        return dto

    async def generate_outline_batch(
        self, project_id: str, req: OutlineBatchGenerateRequest
    ) -> OutlineDto:
        """AI 分批生成大纲：每批仅生成若干章，增量落库并返回当前完整大纲.

        整本大纲一次性生成时输出过长、极易超时；分批后单次输出可控，
        前端可在每批返回后立即刷新展示，再继续下一批（支持暂停/续写）。
        对同一批次重复调用为幂等覆盖。
        """
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")

        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        if not synopsis or not synopsis.content.strip():
            raise ValueError("请先输入故事梗概")
        if not worldview or not worldview.content.strip():
            raise ValueError("请先输入世界观")

        confirmed = await self.character_service.list_confirmed(project_id)
        if not confirmed:
            raise ValueError("请先确认人物清单")

        if req.volume_no > project.volume_count:
            raise ValueError("卷号超出创作参数范围")
        if req.chapter_start > project.chapters_per_volume:
            raise ValueError("章号超出创作参数范围")
        # 本批不得越过当前卷末尾
        chapter_count = min(
            req.chapter_count, project.chapters_per_volume - req.chapter_start + 1
        )
        if chapter_count <= 0:
            raise ValueError("章号超出创作参数范围")

        if req.reset:
            outline = await self._reset_outline(project_id)
        else:
            outline = await self._get_outline_entity(project_id)
            if outline is None:
                outline = await self._reset_outline(project_id)

        volume_names, chapters = await self._collect_generated(outline)
        filled = {(v, c) for v, c, _, sp in chapters if sp and sp.strip()}

        # 关键：必须先结束事务再进 AI 调用。
        # _reset_outline 里的 flush() 已让本会话持有 SQLite 全局写锁，
        # _collect_generated 的读也处在同一事务里。若带着它进入下面数十秒
        # 乃至数分钟的 AI 调用，本连接会一直攥着写锁不放，导致其它写入
        # （自动保存 /api/creation/save、网关计数器写回、AI调用日志）全部
        # 在 busy_timeout 后报 database is locked。
        # `prev_chapters` 只用到已取出的纯数据，提交后无需重新查询。
        await release_write_lock(self.session)

        # 全书首次生成时补齐配角（与整本生成前置逻辑一致，仅触发一次）
        if not filled:
            await self.auto_supporting.ensure_sufficient_for_outline(
                project_id, synopsis.content, worldview.content, confirmed
            )
            confirmed = await self.character_service.list_confirmed(project_id)
            # 配角生成本身会写库，进入批次 AI 调用前再释放一次写锁
            await release_write_lock(self.session)

        prev_chapters = [
            {
                "volume_no": v,
                "chapter_no": c,
                "chapter_name": name,
                "synopsis_points": sp,
            }
            for v, c, name, sp in chapters
            if (v, c) < (req.volume_no, req.chapter_start) and sp and sp.strip()
        ][-get_config().outline_batch_prev_context:]

        draft = await self.builder.build_batch_and_call(
            synopsis=synopsis.content,
            worldview=worldview.content,
            characters=confirmed,
            volume_count=project.volume_count,
            chapters_per_volume=project.chapters_per_volume,
            words_per_chapter=project.words_per_chapter,
            batch_volume_no=req.volume_no,
            batch_volume_name=volume_names.get(req.volume_no, ""),
            batch_chapter_start=req.chapter_start,
            batch_chapter_count=chapter_count,
            prev_chapters=prev_chapters,
            generated_chapter_count=len(filled),
            project_id=project_id,
            timeout_seconds=get_config().outline_batch_timeout_seconds,
            user_ideas=req.user_ideas,
            naming_favorites=await NamingService(self.session).list_favorites_grouped(project_id),
            all_volume_names=volume_names,
        )

        character_names = [c.name for c in confirmed if c.name]
        self._auto_fill_appearing(draft.chapters, character_names)

        await self._upsert_batch(
            outline, req.volume_no, draft.volume_name, draft.chapters
        )

        _, chapters = await self._collect_generated(outline)
        filled = {(v, c) for v, c, _, sp in chapters if sp and sp.strip()}
        total = project.volume_count * project.chapters_per_volume
        outline.gen_status = "已生成" if len(filled) >= total else "生成中"
        await self.session.commit()
        return await self._to_dto(outline)

    async def _get_outline_entity(self, project_id: str) -> Outline | None:
        """读取大纲主记录."""
        result = await self.session.execute(
            select(Outline).where(Outline.project_id == project_id)
        )
        return result.scalars().first()

    async def _reset_outline(self, project_id: str) -> Outline:
        """清空并重建大纲主记录（分批重新生成的起点）."""
        existing = await self._get_outline_entity(project_id)
        if existing is not None:
            await self.session.delete(existing)
            await self.session.flush()

        outline = Outline(
            outline_id=str(uuid.uuid4()),
            project_id=project_id,
            gen_status="生成中",
            source="AI生成",
            generated_at=datetime.now(timezone.utc),
        )
        self.session.add(outline)
        await self.session.flush()
        return outline

    async def _collect_generated(
        self, outline: Outline
    ) -> tuple[dict[int, str], list[tuple[int, int, str, str]]]:
        """返回 (卷号->卷名, 章节明细[(卷号,章号,章节名,梗概要点)] 按卷章升序)."""
        vol_result = await self.session.execute(
            select(VolumeOutline).where(VolumeOutline.outline_id == outline.outline_id)
        )
        volume_names: dict[int, str] = {}
        chapters: list[tuple[int, int, str, str]] = []
        for vol in vol_result.scalars().all():
            volume_names[vol.volume_no] = vol.volume_name
            ch_result = await self.session.execute(
                select(ChapterOutline).where(
                    ChapterOutline.volume_outline_id == vol.volume_outline_id
                )
            )
            for ch in ch_result.scalars().all():
                chapters.append(
                    (vol.volume_no, ch.chapter_no, ch.chapter_name, ch.synopsis_points)
                )
        chapters.sort(key=lambda item: (item[0], item[1]))
        return volume_names, chapters

    async def _upsert_batch(
        self,
        outline: Outline,
        volume_no: int,
        volume_name: str,
        chapters: list[ChapterDraft],
    ) -> None:
        """把单批章节写入指定卷：已存在则更新，不存在则新增（幂等）."""
        if not chapters:
            return

        vol_result = await self.session.execute(
            select(VolumeOutline).where(
                VolumeOutline.outline_id == outline.outline_id,
                VolumeOutline.volume_no == volume_no,
            )
        )
        vol = vol_result.scalars().first()
        if vol is None:
            vol = VolumeOutline(
                volume_outline_id=str(uuid.uuid4()),
                outline_id=outline.outline_id,
                volume_no=volume_no,
                volume_name=volume_name or f"第{volume_no}卷",
                chapter_count=0,
            )
            self.session.add(vol)
            await self.session.flush()
        elif volume_name and volume_name != vol.volume_name:
            vol.volume_name = volume_name

        ch_result = await self.session.execute(
            select(ChapterOutline).where(
                ChapterOutline.volume_outline_id == vol.volume_outline_id
            )
        )
        existing_map = {c.chapter_no: c for c in ch_result.scalars().all()}
        for ch in chapters:
            entity = existing_map.get(ch.chapter_no)
            if entity is None:
                self.session.add(
                    ChapterOutline(
                        chapter_outline_id=str(uuid.uuid4()),
                        volume_outline_id=vol.volume_outline_id,
                        volume_no=volume_no,
                        chapter_no=ch.chapter_no,
                        chapter_name=ch.chapter_name or f"第{ch.chapter_no}章",
                        synopsis_points=ch.synopsis_points,
                        characters_appearing=ch.characters_appearing or None,
                        gen_source="AI生成",
                    )
                )
            else:
                if ch.chapter_name:
                    entity.chapter_name = ch.chapter_name
                if ch.synopsis_points:
                    entity.synopsis_points = ch.synopsis_points
                if ch.characters_appearing:
                    entity.characters_appearing = ch.characters_appearing
                entity.gen_source = "AI生成"

        ch_existing_result = await self.session.execute(
            select(Chapter).where(
                Chapter.project_id == outline.project_id,
                Chapter.volume_no == volume_no,
            )
        )
        ch_existing_map = {c.chapter_no: c for c in ch_existing_result.scalars().all()}
        for ch in chapters:
            ch_entity = ch_existing_map.get(ch.chapter_no)
            ch_title = ch.chapter_name or f"第{ch.chapter_no}章"
            if ch_entity is None:
                self.session.add(
                    Chapter(
                        chapter_id=str(uuid.uuid4()),
                        project_id=outline.project_id,
                        volume_no=volume_no,
                        chapter_no=ch.chapter_no,
                        title=ch_title,
                        content=None,
                        word_count=0,
                        gen_status="outlined",
                        modify_status="none",
                    )
                )
            else:
                ch_entity.title = ch_title
                if ch_entity.gen_status == "pending":
                    ch_entity.gen_status = "outlined"

        await self.session.flush()
        count_result = await self.session.execute(
            select(func.count())
            .select_from(ChapterOutline)
            .where(ChapterOutline.volume_outline_id == vol.volume_outline_id)
        )
        vol.chapter_count = int(count_result.scalar() or 0)

    async def check_consistency(
        self, project_id: str, req: OutlineCheckRequest,
        garbled_config: "GarbledConfig | None" = None,
    ) -> OutlineConsistencyResult:
        """校验某批大纲是否贴合梗概/世界观，以及人物出场逻辑是否合理.

        采用分批校验（与分批生成对称）：单次输入规模可控，避免整本大纲一次校验超时。
        AI 校验之外补充确定性规则检查（主角缺席、登记了未登记人物等）。
        """
        from src.services.garbled_config_service import GarbledConfigService

        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")

        if garbled_config is None:
            cfg_svc = GarbledConfigService(self.session)
            garbled_config = await cfg_svc.resolve_effective_config(project_id)

        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        if not synopsis or not synopsis.content.strip():
            raise ValueError("请先输入故事梗概")
        if not worldview or not worldview.content.strip():
            raise ValueError("请先输入世界观")

        confirmed = await self.character_service.list_confirmed(project_id)
        if not confirmed:
            raise ValueError("请先确认人物清单")

        outline = await self._get_outline_entity(project_id)
        if outline is None:
            raise ValueError("请先生成大纲")

        chapter_end = req.chapter_start + req.chapter_count - 1
        dto = await self._to_dto(outline)
        batch_chapters: list[dict] = []
        for vol in dto.volumes:
            if vol.volume_no != req.volume_no:
                continue
            for ch in vol.chapters:
                if req.chapter_start <= ch.chapter_no <= chapter_end:
                    batch_chapters.append(
                        {
                            "chapter_no": ch.chapter_no,
                            "chapter_name": ch.chapter_name,
                            "synopsis_points": ch.synopsis_points,
                            "characters_appearing": ch.characters_appearing,
                            "chapter_id": ch.chapter_id,
                        }
                    )
        batch_chapters.sort(key=lambda item: int(item["chapter_no"]))
        if not batch_chapters:
            raise ValueError("本批章节尚未生成，无法校验")

        for ch in batch_chapters:
            ch["scenes"] = []
            chapter_id = ch.get("chapter_id")
            if chapter_id:
                try:
                    scenes = await self.scene_service.list_scenes(chapter_id)
                    ch["scenes"] = [
                        {
                            "goal": sc.goal,
                            "characters": sc.characters,
                            "key_event": sc.key_event,
                            "mood": sc.mood,
                            "est_words": sc.est_words,
                        }
                        for sc in scenes
                    ]
                except Exception as e:
                    self.logger.warning(f"加载第{ch['chapter_no']}章场景失败，降级为空: {e}")

        for ch in batch_chapters:
            ch.pop("chapter_id", None)

        # 兜底：已有大纲数据中 characters_appearing 可能为空（早期生成遗漏），
        # 校验前自动补全，避免对历史数据重复报"未登记出场人物"。
        character_names = [c.name for c in confirmed if c.name]
        sorted_names = sorted(
            (n for n in character_names if n and n.strip()), key=len, reverse=True
        )
        for ch in batch_chapters:
            if (ch.get("characters_appearing") or "").strip():
                continue
            text = ch.get("synopsis_points") or ""
            if not text:
                continue
            found = [n for n in sorted_names if n in text]
            ch["characters_appearing"] = "、".join(found)

        # 与生成流程一致：进入 AI 调用前结束事务。
        # 调用方（或后续新增的调用点）若残留未提交的 DML，写锁会被一直持有到
        # commit，期间自动保存与网关计数器写回都会撞 database is locked。
        await release_write_lock(self.session)

        result = await self.builder.build_check_and_call(
            synopsis=synopsis.content,
            worldview=worldview.content,
            characters=confirmed,
            volume_no=req.volume_no,
            chapters=batch_chapters,
            project_id=project_id,
            timeout_seconds=get_config().outline_batch_timeout_seconds,
            garbled_config=garbled_config,
        )
        result.issues.extend(self._rule_check(confirmed, batch_chapters))
        if garbled_config and garbled_config.enabled:
            from src.services.garbled_normalizer import GarbledNormalizer
            normalizer = GarbledNormalizer()
            for ch in batch_chapters:
                for field_name in ("synopsis_points", "chapter_name"):
                    field_text = ch.get(field_name, "") or ""
                    if not field_text:
                        continue
                    gi_list = normalizer.detect_only(field_text, garbled_config)
                    for gi in gi_list:
                        result.issues.append(OutlineConsistencyIssue(
                            level=gi.level,
                            chapter_no=int(ch.get("chapter_no", 0)),
                            type=gi.category,
                            detail=f"{field_name}位置{gi.position}：{gi.category}",
                            suggestion=gi.suggestion,
                        ))
        return result

    @staticmethod
    def _rule_check(
        characters: list[CharacterDto], chapters: list[dict]
    ) -> list[OutlineConsistencyIssue]:
        """确定性规则检查：主角本批缺席、登记了清单外人物、未登记出场人物."""
        issues: list[OutlineConsistencyIssue] = []
        known_names = {c.name for c in characters}
        protagonists = [c.name for c in characters if "主角" in (c.identity or "")]

        appearing_text = " ".join(
            f"{ch.get('characters_appearing', '')} {ch.get('synopsis_points', '')}"
            for ch in chapters
        )
        first_chapter_no = int(chapters[0]["chapter_no"]) if chapters else 0
        for name in protagonists:
            if name and name not in appearing_text:
                issues.append(
                    OutlineConsistencyIssue(
                        level="严重",
                        chapter_no=first_chapter_no,
                        type="人物出场",
                        detail=f"本批章节均未出现或提及主角「{name}」",
                        suggestion=f"安排「{name}」在本批出场或推动情节，避免主角长时间缺席",
                    )
                )

        for ch in chapters:
            chapter_no = int(ch.get("chapter_no", 0))
            names = [
                name.strip()
                for name in str(ch.get("characters_appearing", "")).split("、")
                if name.strip()
            ]
            if not names:
                issues.append(
                    OutlineConsistencyIssue(
                        level="轻微",
                        chapter_no=chapter_no,
                        type="人物出场",
                        detail=f"第{chapter_no}章未登记出场人物",
                        suggestion="补充本章出场人物，便于校验人物出场逻辑",
                    )
                )
                continue
            unknown = [name for name in names if name not in known_names]
            if unknown:
                issues.append(
                    OutlineConsistencyIssue(
                        level="一般",
                        chapter_no=chapter_no,
                        type="人物出场",
                        detail=(
                            f"第{chapter_no}章登记了人物清单中不存在的人物："
                            f"{'、'.join(unknown)}"
                        ),
                        suggestion="在人物管理中补充该人物，或从本章出场人物中移除",
                    )
                )
            appearing_set = set(names)
            for sc in ch.get("scenes") or []:
                sc_chars = [
                    n.strip()
                    for n in str(sc.get("characters", "")).replace("，", "、").split("、")
                    if n.strip()
                ]
                for sc_name in sc_chars:
                    if sc_name not in appearing_set and sc_name not in known_names:
                        issues.append(
                            OutlineConsistencyIssue(
                                level="一般",
                                chapter_no=chapter_no,
                                type="场景一致性",
                                detail=f"第{chapter_no}章场景角色「{sc_name}」未登记于本章出场人物",
                                suggestion="补充登记该人物至本章出场人物，或调整场景角色",
                            )
                        )
        return issues

    async def get_outline(self, project_id: str) -> OutlineDto | None:
        """读取完整大纲结构."""
        result = await self.session.execute(
            select(Outline).where(Outline.project_id == project_id)
        )
        outline = result.scalars().first()
        if not outline:
            return None
        return await self._to_dto(outline)

    async def get_chapter_synopsis(
        self, project_id: str, volume_no: int, chapter_no: int
    ) -> str | None:
        """返回指定章节的梗概要点."""
        result = await self.session.execute(
            select(Outline).where(Outline.project_id == project_id)
        )
        outline = result.scalars().first()
        if not outline:
            return None

        vol_result = await self.session.execute(
            select(VolumeOutline).where(
                VolumeOutline.outline_id == outline.outline_id,
                VolumeOutline.volume_no == volume_no,
            )
        )
        vol = vol_result.scalars().first()
        if not vol:
            return None

        ch_result = await self.session.execute(
            select(ChapterOutline).where(
                ChapterOutline.volume_outline_id == vol.volume_outline_id,
                ChapterOutline.chapter_no == chapter_no,
            )
        )
        ch = ch_result.scalars().first()
        return ch.synopsis_points if ch else None

    async def generate_story_unit_layer(
        self, project_id: str, parent_unit_id: str | None, level_type: str
    ) -> list:
        """雪花式分层大纲逐层生成，委托 StoryUnitService."""
        from src.api.schemas.story_unit_schema import StoryUnitDto
        from src.services.story_unit_service import StoryUnitService

        service = StoryUnitService(self.session)
        if parent_unit_id is None and level_type == "volume":
            return await service.generate_volume_layer(project_id)
        if parent_unit_id is None:
            raise ValueError("非分卷层生成须指定父单元")
        return await service.generate_layer(project_id, parent_unit_id, level_type)

    async def save_outline(
        self, project_id: str, req: OutlineSaveRequest
    ) -> OutlineDto:
        """用户编辑后保存大纲."""
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")

        draft = OutlineDraft(
            volumes=[
                {
                    "volume_no": v.volume_no,
                    "volume_name": v.volume_name,
                    "chapters": [
                        {
                            "chapter_no": ch.chapter_no,
                            "chapter_name": ch.chapter_name,
                            "synopsis_points": ch.synopsis_points,
                        }
                        for ch in v.chapters
                    ],
                }
                for v in req.volumes
            ]
        )

        if not self._validate_structure(draft, project):
            raise ValueError("大纲结构与创作参数不匹配")

        for v in draft.volumes:
            for ch in v.chapters:
                if not ch.synopsis_points.strip():
                    raise ValueError(f"第{v.volume_no}卷第{ch.chapter_no}章梗概要点为空")

        dto = await self._write_outline(project_id, draft, gen_status="已保存", source="手动编辑")
        return dto

    async def delete_outline(self, project_id: str) -> bool:
        """级联删除大纲三张表数据."""
        result = await self.session.execute(
            select(Outline).where(Outline.project_id == project_id)
        )
        outline = result.scalars().first()
        if not outline:
            return False
        await self.session.delete(outline)
        await self.session.commit()
        return True

    def _validate_structure(self, draft: OutlineDraft, project: Project) -> bool:
        """校验卷数/章节数与创作参数一致."""
        if len(draft.volumes) != project.volume_count:
            return False
        for v in draft.volumes:
            if len(v.chapters) != project.chapters_per_volume:
                return False
        return True

    @staticmethod
    def _auto_fill_appearing(chapters: list[ChapterDraft], character_names: list[str]) -> None:
        """characters_appearing 为空时，从 synopsis_points 中提取已确认人物名字自动补全.

        AI 生成大纲时常遗漏 characters_appearing 字段（尤其分批生成时每批
        章节较多），导致一致性校验报大量"未登记出场人物"问题。此处兜底：
        从梗概要点文本中匹配已确认人物姓名，填入 characters_appearing，
        保证后续校验与撰写能正确追踪出场人物。

        通用逻辑，不针对特定小说硬编码：只要人物名字出现在梗概要点中即补全。
        """
        if not character_names:
            return
        sorted_names = sorted(
            (n for n in character_names if n and n.strip()),
            key=len,
            reverse=True,
        )
        for ch in chapters:
            if ch.characters_appearing and ch.characters_appearing.strip():
                continue
            if not ch.synopsis_points:
                continue
            found: list[str] = []
            text = ch.synopsis_points
            for name in sorted_names:
                if name in text and name not in found:
                    found.append(name)
            ch.characters_appearing = "、".join(found)

    def _validate_synopsis_length(self, synopsis: str) -> tuple[bool, str]:
        """字数 100-300 返回 (True, "")，偏离返回 (False, 提示)."""
        count = len(synopsis)
        if 100 <= count <= 300:
            return True, ""
        return False, f"梗概要点 {count} 字，建议 100-300 字"

    async def _write_outline(
        self,
        project_id: str,
        draft: OutlineDraft,
        gen_status: str,
        source: str,
    ) -> OutlineDto:
        """单事务覆盖写入三张表."""
        result = await self.session.execute(
            select(Outline).where(Outline.project_id == project_id)
        )
        existing = result.scalars().first()
        if existing:
            await self.session.delete(existing)
            await self.session.flush()

        now = datetime.now(timezone.utc)
        outline = Outline(
            outline_id=str(uuid.uuid4()),
            project_id=project_id,
            gen_status=gen_status,
            source=source,
            generated_at=now,
            saved_at=now if gen_status == "已保存" else None,
        )
        self.session.add(outline)
        await self.session.flush()

        for v in draft.volumes:
            vol = VolumeOutline(
                volume_outline_id=str(uuid.uuid4()),
                outline_id=outline.outline_id,
                volume_no=v.volume_no,
                volume_name=v.volume_name or f"第{v.volume_no}卷",
                chapter_count=len(v.chapters),
            )
            self.session.add(vol)
            await self.session.flush()

            for ch in v.chapters:
                ch_outline = ChapterOutline(
                    chapter_outline_id=str(uuid.uuid4()),
                    volume_outline_id=vol.volume_outline_id,
                    volume_no=v.volume_no,
                    chapter_no=ch.chapter_no,
                    chapter_name=ch.chapter_name or f"第{ch.chapter_no}章",
                    synopsis_points=ch.synopsis_points,
                    characters_appearing=ch.characters_appearing or None,
                    gen_source="AI生成" if source == "AI生成" else "手动编辑",
                )
                self.session.add(ch_outline)

        ch_all_result = await self.session.execute(
            select(Chapter).where(Chapter.project_id == project_id)
        )
        ch_all_map = {(c.volume_no, c.chapter_no): c for c in ch_all_result.scalars().all()}
        for v in draft.volumes:
            for ch in v.chapters:
                ch_entity = ch_all_map.get((v.volume_no, ch.chapter_no))
                ch_title = ch.chapter_name or f"第{ch.chapter_no}章"
                if ch_entity is None:
                    self.session.add(
                        Chapter(
                            chapter_id=str(uuid.uuid4()),
                            project_id=project_id,
                            volume_no=v.volume_no,
                            chapter_no=ch.chapter_no,
                            title=ch_title,
                            content=None,
                            word_count=0,
                            gen_status="outlined",
                            modify_status="none",
                        )
                    )
                else:
                    ch_entity.title = ch_title
                    if ch_entity.gen_status == "pending":
                        ch_entity.gen_status = "outlined"

        await self.session.commit()
        return await self._to_dto(outline)

    async def _to_dto(self, outline: Outline) -> OutlineDto:
        """ORM 转 DTO."""
        ch_map_result = await self.session.execute(
            select(Chapter).where(Chapter.project_id == outline.project_id)
        )
        ch_id_map = {(c.volume_no, c.chapter_no): c.chapter_id for c in ch_map_result.scalars().all()}
        try:
            scene_count_result = await self.session.execute(
                select(ChapterScene.chapter_id, func.count()).group_by(ChapterScene.chapter_id)
            )
            scene_count_map = dict(scene_count_result.all())
        except Exception as e:
            self.logger.warning(f"场景数量批量查询失败，降级为 0: {e}")
            scene_count_map = {}
        vol_result = await self.session.execute(
            select(VolumeOutline)
            .where(VolumeOutline.outline_id == outline.outline_id)
            .order_by(VolumeOutline.volume_no)
        )
        volumes: list[VolumeOutlineDto] = []
        for vol in vol_result.scalars().all():
            ch_result = await self.session.execute(
                select(ChapterOutline)
                .where(ChapterOutline.volume_outline_id == vol.volume_outline_id)
                .order_by(ChapterOutline.chapter_no)
            )
            chapters = [
                ChapterOutlineDto(
                    chapter_id=ch_id_map.get((ch.volume_no, ch.chapter_no), ""),
                    chapter_no=ch.chapter_no,
                    chapter_name=ch.chapter_name,
                    synopsis_points=ch.synopsis_points,
                    characters_appearing=ch.characters_appearing or "",
                    gen_source=ch.gen_source,
                    scene_count=scene_count_map.get(ch_id_map.get((ch.volume_no, ch.chapter_no), ""), 0),
                )
                for ch in ch_result.scalars().all()
            ]
            volumes.append(
                VolumeOutlineDto(
                    volume_no=vol.volume_no,
                    volume_name=vol.volume_name,
                    chapters=chapters,
                )
            )
        return OutlineDto(
            outline_id=outline.outline_id,
            project_id=outline.project_id,
            gen_status=outline.gen_status,
            source=outline.source,
            generated_at=outline.generated_at,
            volumes=volumes,
        )
    async def fill_appearing(
        self, project_id: str, req: FillAppearingRequest
    ) -> FillAppearingResponse:
        """AI 智能填充出场人物为空的章节."""
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        if not synopsis or not synopsis.content.strip():
            raise ValueError("请先输入故事梗概")
        confirmed = await self.character_service.list_confirmed(project_id)
        if not confirmed:
            raise ValueError("请先确认人物清单")
        outline = await self._get_outline_entity(project_id)
        if outline is None:
            raise ValueError("请先生成大纲")

        dto = await self._to_dto(outline)
        confirmed_names = {c.name for c in confirmed if c.name}
        results: list[FillAppearingResultItem] = []
        matched_count = 0
        pending_count = 0
        skipped_count = 0

        for vol in dto.volumes:
            for ch in vol.chapters:
                if req.volume_no is not None and vol.volume_no != req.volume_no:
                    continue
                if req.chapter_start is not None and ch.chapter_no < req.chapter_start:
                    continue
                if req.chapter_count is not None and ch.chapter_no > req.chapter_start + req.chapter_count - 1:
                    continue
                if (ch.characters_appearing or "").strip():
                    results.append(FillAppearingResultItem(chapter_no=ch.chapter_no, skipped=True))
                    skipped_count += 1
                    continue
                chapter_dict = {
                    "chapter_no": ch.chapter_no,
                    "chapter_name": ch.chapter_name,
                    "synopsis_points": ch.synopsis_points,
                }
                await release_write_lock(self.session)
                try:
                    names = await self.builder.build_fill_appearing_and_call(
                        synopsis=synopsis.content,
                        worldview=worldview.content if worldview else "",
                        characters=confirmed,
                        chapter=chapter_dict,
                        project_id=project_id,
                        timeout_seconds=get_config().outline_fill_appearing_timeout_seconds,
                    )
                except TimeoutError:
                    results.append(FillAppearingResultItem(chapter_no=ch.chapter_no, skipped=True, fail_reason="AI 超时"))
                    skipped_count += 1
                    continue
                except Exception as e:
                    results.append(FillAppearingResultItem(chapter_no=ch.chapter_no, skipped=True, fail_reason=str(e)))
                    skipped_count += 1
                    continue

                matched = [n for n in names if n in confirmed_names]
                pending = [n for n in names if n not in confirmed_names]
                if matched:
                    ch_outline = await self.session.execute(
                        select(ChapterOutline).where(
                            ChapterOutline.volume_outline_id == (
                                select(VolumeOutline.volume_outline_id).where(
                                    VolumeOutline.outline_id == outline.outline_id,
                                    VolumeOutline.volume_no == vol.volume_no,
                                )
                            ),
                            ChapterOutline.chapter_no == ch.chapter_no,
                        )
                    )
                    ch_entity = ch_outline.scalars().first()
                    if ch_entity:
                        ch_entity.characters_appearing = "、".join(matched)
                        await self.session.commit()
                results.append(FillAppearingResultItem(chapter_no=ch.chapter_no, matched=matched, pending=pending))
                matched_count += len(matched)
                pending_count += len(pending)

        summary = f"命中 {matched_count} 章，待确认 {pending_count} 章，跳过 {skipped_count} 章"
        return FillAppearingResponse(results=results, summary=summary)

    async def repair_outline_stream(
        self,
        project_id: str,
        issues: list[OutlineConsistencyIssue],
        repair_scope: str = "all",
        garbled_config: "GarbledConfig | None" = None,
    ) -> AsyncGenerator[RepairStreamChunk, None]:
        """逐章 AI 修复大纲，问题驱动，支持暂停/续写."""
        from src.services.garbled_config_service import GarbledConfigService
        from src.services.garbled_normalizer import GarbledNormalizer

        project = await self.session.get(Project, project_id)
        if not project:
            yield RepairStreamChunk(type="error", message="项目不存在")
            return

        if garbled_config is None:
            cfg_svc = GarbledConfigService(self.session)
            garbled_config = await cfg_svc.resolve_effective_config(project_id)
        normalizer = GarbledNormalizer()
        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        if not synopsis or not synopsis.content.strip():
            yield RepairStreamChunk(type="error", message="请先输入故事梗概")
            return
        confirmed = await self.character_service.list_confirmed(project_id)
        if not confirmed:
            yield RepairStreamChunk(type="error", message="请先确认人物清单")
            return
        if not issues:
            yield RepairStreamChunk(type="error", message="问题清单为空")
            return

        outline = await self._get_outline_entity(project_id)
        if outline is None:
            yield RepairStreamChunk(type="error", message="请先生成大纲")
            return

        confirmed_names = {c.name for c in confirmed if c.name}

        scope_filter = {"all": None, "severe": "严重", "general": "一般"}
        target_level = scope_filter.get(repair_scope)

        issue_chapters: set[tuple[int, int]] = set()
        for issue in issues:
            if target_level and issue.level != target_level:
                if repair_scope == "general" and issue.level == "严重":
                    pass
                elif repair_scope == "severe":
                    continue
            if issue.chapter_no and issue.chapter_no > 0:
                issue_chapters.add((0, issue.chapter_no))

        dto = await self._to_dto(outline)
        target_chapters = []
        for vol in dto.volumes:
            for ch in vol.chapters:
                if (vol.volume_no, ch.chapter_no) in issue_chapters or any(
                    (0, ch.chapter_no) in issue_chapters for _ in [1]
                ):
                    target_chapters.append((vol, ch))
        if not target_chapters:
            for vol in dto.volumes:
                for ch in vol.chapters:
                    if any(i.chapter_no == ch.chapter_no for i in issues):
                        target_chapters.append((vol, ch))

        target_chapters.sort(key=lambda x: (x[0].volume_no, x[1].chapter_no))
        total = len(target_chapters)
        success = 0
        failed = 0
        skipped = 0

        for idx, (vol, ch) in enumerate(target_chapters, 1):
            ch_issues = [
                {"level": i.level, "type": i.type, "detail": i.detail, "suggestion": i.suggestion}
                for i in issues if i.chapter_no == ch.chapter_no
            ]
            yield RepairStreamChunk(
                type="progress",
                chapter_no=ch.chapter_no,
                volume_no=vol.volume_no,
                done=idx,
                total=total,
            )
            self.logger.info(f"修复第 {idx}/{total} 章：第{vol.volume_no}卷第{ch.chapter_no}章")

            chapter_dict = {
                "chapter_no": ch.chapter_no,
                "chapter_name": ch.chapter_name,
                "synopsis_points": ch.synopsis_points,
                "characters_appearing": ch.characters_appearing,
            }
            await release_write_lock(self.session)
            try:
                parsed = await self.builder.build_repair_and_call(
                    synopsis=synopsis.content,
                    worldview=worldview.content if worldview else "",
                    characters=confirmed,
                    chapter=chapter_dict,
                    chapter_issues=ch_issues,
                    project_id=project_id,
                    timeout_seconds=get_config().outline_repair_timeout_seconds,
                    garbled_config=garbled_config,
                )
            except TimeoutError:
                skipped += 1
                yield RepairStreamChunk(type="chapter_skip", chapter_no=ch.chapter_no, volume_no=vol.volume_no, status="跳过", fail_reason="AI 超时")
                continue
            except Exception as e:
                skipped += 1
                yield RepairStreamChunk(type="chapter_skip", chapter_no=ch.chapter_no, volume_no=vol.volume_no, status="跳过", fail_reason=str(e))
                continue

            synopsis_new = parsed.get("synopsis_points_new", "")
            appearing_new = parsed.get("characters_appearing_new", "")
            adjust_notes = parsed.get("adjust_notes", [])

            if garbled_config.enabled:
                synopsis_new, _ = normalizer.detect_and_normalize(synopsis_new, garbled_config)
                appearing_new, _ = normalizer.detect_and_normalize(appearing_new, garbled_config)

            if len(synopsis_new) < get_config().min_ai_content_length:
                failed += 1
                yield RepairStreamChunk(type="chapter_rollback", chapter_no=ch.chapter_no, volume_no=vol.volume_no, status="回滚", fail_reason="修复内容过短已放弃")
                continue

            appearing_names = [n.strip() for n in appearing_new.replace("，", "、").split("、") if n.strip()]
            appearing_filtered = [n for n in appearing_names if n in confirmed_names]
            appearing_new = "、".join(appearing_filtered)

            ch_outline = await self.session.execute(
                select(ChapterOutline).where(
                    ChapterOutline.volume_outline_id == (
                        select(VolumeOutline.volume_outline_id).where(
                            VolumeOutline.outline_id == outline.outline_id,
                            VolumeOutline.volume_no == vol.volume_no,
                        )
                    ),
                    ChapterOutline.chapter_no == ch.chapter_no,
                )
            )
            ch_entity = ch_outline.scalars().first()
            if ch_entity:
                ch_entity.synopsis_points = synopsis_new
                ch_entity.characters_appearing = appearing_new
                await self.session.commit()

            success += 1
            yield RepairStreamChunk(
                type="chapter_done",
                chapter_no=ch.chapter_no,
                volume_no=vol.volume_no,
                synopsis_points_new=synopsis_new,
                characters_appearing_new=appearing_new,
                adjust_notes=adjust_notes,
            )

        yield RepairStreamChunk(
            type="completed",
            success=success,
            failed=failed,
            skipped=skipped,
            message=f"修复完成：成功 {success}，失败 {failed}，跳过 {skipped}",
        )