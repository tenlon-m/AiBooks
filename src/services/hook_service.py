"""爽点钩子服务 - AI辅助设定、回收跟踪、基调校验."""
from __future__ import annotations

import uuid
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.hook_schema import (
    AiDesignHooksResponse,
    ChapterHookDto,
    ChapterPlanItem,
    CoolPointDto,
    HookConsistencyIssue,
    HookConsistencyResult,
    HookDto,
    HookRepairStreamChunk,
)
from src.config.settings import get_config
from src.db.models import CoolPoint, Hook, NameFavorite, Project
from src.db.session import release_write_lock
from src.services.naming_service import NAME_TYPE_LABELS, NamingService
from src.utils.logger import get_logger

MAX_RECYCLE_DISTANCE_VOLUMES = 3


class HookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def ai_design(self, project_id: str, synopsis: str, worldview: str, characters: list[dict], chapter_plan: list[ChapterPlanItem], user_ideas: str = "") -> AiDesignHooksResponse:
        """AI 辅助设定每章爽点+钩子+回收计划 - 逐章生成模式，避免全量输出超时."""
        project = await self.session.get(Project, project_id)
        volume_count = project.volume_count if project else 1
        chapters_per_volume = project.chapters_per_volume if project else 10

        cool_points: list[CoolPointDto] = []
        hooks: list[HookDto] = []
        failed_chapters: list[list[int]] = []

        for cp in chapter_plan:
            v, c = cp.volume_no, cp.chapter_no
            try:
                cp_list, hook_list = await self._generate_chapter_data(
                    project_id, v, c, user_ideas
                )
                for h in hook_list:
                    fixed, _ = self._fix_recycle_order(h, volume_count, chapters_per_volume)
                    hooks.append(fixed)
                cool_points.extend(cp_list)
            except Exception as e:
                self.logger.warning(f"生成第{v}卷第{c}章爽点钩子失败: {e}")
                failed_chapters.append([v, c])

        return AiDesignHooksResponse(
            cool_points=cool_points,
            hooks=hooks,
            missing_chapters=failed_chapters,
            failed_chapters=failed_chapters,
        )

    async def save_cool_points(self, project_id: str, cool_points: list[CoolPointDto]) -> list[CoolPointDto]:
        result = []
        for cp in cool_points:
            entity = CoolPoint(
                cool_id=str(uuid.uuid4()),
                project_id=project_id,
                volume_no=cp.volume_no,
                chapter_no=cp.chapter_no,
                cool_type=cp.cool_type,
                content_desc=cp.content_desc,
                source=cp.source,
            )
            self.session.add(entity)
            await self.session.flush()
            cp.cool_id = entity.cool_id
            cp.project_id = project_id
            result.append(cp)
        return result

    async def save_hooks(self, project_id: str, hooks: list[HookDto]) -> list[HookDto]:
        result = []
        for h in hooks:
            entity = Hook(
                hook_id=str(uuid.uuid4()),
                project_id=project_id,
                volume_no=h.volume_no,
                chapter_no=h.chapter_no,
                hook_content=h.hook_content,
                recycle_volume_no=h.recycle_volume_no,
                recycle_chapter_no=h.recycle_chapter_no,
                recycle_status=h.recycle_status,
                source=h.source,
            )
            self.session.add(entity)
            await self.session.flush()
            h.hook_id = entity.hook_id
            h.project_id = project_id
            result.append(h)
        return result

    async def list_cool_points(self, project_id: str) -> list[CoolPointDto]:
        result = await self.session.execute(
            select(CoolPoint)
            .where(CoolPoint.project_id == project_id)
            .order_by(CoolPoint.volume_no, CoolPoint.chapter_no)
        )
        return [
            CoolPointDto(
                cool_id=cp.cool_id,
                project_id=cp.project_id,
                volume_no=cp.volume_no,
                chapter_no=cp.chapter_no,
                cool_type=cp.cool_type,
                content_desc=cp.content_desc,
                source=cp.source,
            )
            for cp in result.scalars().all()
        ]

    async def list_hooks(self, project_id: str) -> list[HookDto]:
        result = await self.session.execute(
            select(Hook)
            .where(Hook.project_id == project_id)
            .order_by(Hook.volume_no, Hook.chapter_no)
        )
        return [
            HookDto(
                hook_id=h.hook_id,
                project_id=h.project_id,
                volume_no=h.volume_no,
                chapter_no=h.chapter_no,
                hook_content=h.hook_content,
                recycle_volume_no=h.recycle_volume_no,
                recycle_chapter_no=h.recycle_chapter_no,
                recycle_status=h.recycle_status,
                source=h.source,
            )
            for h in result.scalars().all()
        ]

    async def update_recycle_status(self, project_id: str) -> None:
        """扫描全书更新钩子回收状态."""
        hooks = await self.list_hooks(project_id)
        for h in hooks:
            if h.recycle_status == "pending":
                chapter = await self.session.execute(
                    select(Chapter).where(
                        Chapter.project_id == project_id,
                        Chapter.volume_no == h.recycle_volume_no,
                        Chapter.chapter_no == h.recycle_chapter_no,
                        Chapter.gen_status == "completed",
                    )
                )
                if chapter.scalars().first():
                    entity = await self.session.get(Hook, h.hook_id)
                    if entity:
                        entity.recycle_status = "recycled"
        await self.session.flush()

    async def check_completeness(self, project_id: str, volume_count: int, chapters_per_volume: int) -> list[str]:
        """检查每章是否都有爽点和钩子."""
        problems = []
        cool_points = await self.list_cool_points(project_id)
        hooks = await self.list_hooks(project_id)
        cool_map = {(cp.volume_no, cp.chapter_no) for cp in cool_points}
        hook_map = {(h.volume_no, h.chapter_no) for h in hooks}
        for v in range(1, volume_count + 1):
            for c in range(1, chapters_per_volume + 1):
                if (v, c) not in cool_map:
                    problems.append(f"第{v}卷第{c}章缺少爽点")
                if (v, c) not in hook_map:
                    problems.append(f"第{v}卷第{c}章缺少钩子")
        for h in hooks:
            dist = abs(h.recycle_volume_no - h.volume_no)
            if dist > MAX_RECYCLE_DISTANCE_VOLUMES:
                problems.append(f"第{h.volume_no}卷第{h.chapter_no}章钩子回收距离超3卷")
        return problems

    async def _generate_chapter_data(
        self,
        project_id: str,
        volume_no: int,
        chapter_no: int,
        user_ideas: str = "",
    ) -> tuple[list[CoolPointDto], list[HookDto]]:
        """装配上下文并调用 AI 生成单章爽点钩子，不落库."""
        from src.services.outline_service import OutlineService
        from src.services.character_service import CharacterService
        from src.services.auto_supporting_service import AutoSupportingService
        from src.db.models import Synopsis, Worldview

        outline_service = OutlineService(self.session)
        chapter_synopsis = await outline_service.get_chapter_synopsis(
            project_id, volume_no, chapter_no
        )
        if not chapter_synopsis or not chapter_synopsis.strip():
            raise ValueError(f"第{volume_no}卷第{chapter_no}章大纲梗概要点缺失")

        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        if not synopsis or not worldview:
            raise ValueError("故事梗概或世界观缺失")

        char_service = CharacterService(self.session)
        confirmed = await char_service.list_confirmed(project_id)

        try:
            auto_supporting = AutoSupportingService(self.session)
            await auto_supporting.ensure_sufficient_for_hook(
                project_id, volume_no, chapter_no
            )
        except Exception as e:
            self.logger.warning(f"自动生成配角失败，降级跳过: {e}")
        confirmed = await char_service.list_confirmed(project_id)

        prev_hooks = await self._get_prev_hooks(project_id, volume_no, chapter_no)
        naming_favorites = await NamingService(self.session).list_favorites_grouped(project_id)

        await release_write_lock(self.session)

        result = await self.gateway.call_and_parse(
            module="hook",
            scene="generate-chapter",
            params={
                "synopsis": synopsis.content,
                "worldview": worldview.content,
                "characters": [c.model_dump() for c in confirmed],
                "chapter_synopsis": chapter_synopsis,
                "prev_hooks": [h.model_dump() for h in prev_hooks],
                "naming_favorites": naming_favorites,
                "volume_no": volume_no,
                "chapter_no": chapter_no,
                "user_ideas": user_ideas,
            },
            project_id=project_id,
            timeout_seconds=get_config().hook_chapter_timeout_seconds,
        )
        parsed = result.get("parsed", {})

        cool_points = [
            CoolPointDto(
                volume_no=volume_no,
                chapter_no=chapter_no,
                cool_type=cp.get("type", cp.get("cool_type", "")),
                content_desc=cp.get("content", cp.get("content_desc", "")),
                source="ai_design",
            )
            for cp in parsed.get("cool_points", [])
        ]
        hooks = [
            HookDto(
                volume_no=volume_no,
                chapter_no=chapter_no,
                hook_content=h.get("content", h.get("hook_content", "")),
                recycle_volume_no=h.get("recycle_volume_no", volume_no),
                recycle_chapter_no=h.get("recycle_chapter_no", chapter_no),
                source="ai_design",
            )
            for h in parsed.get("hooks", [])
        ]

        return cool_points, hooks

    async def generate_chapter_outline(
        self,
        project_id: str,
        volume_no: int,
        chapter_no: int,
        context: dict | None = None,
        user_ideas: str = "",
    ) -> ChapterHookDto:
        """逐章生成爽点钩子，读取该章大纲梗概要点作为核心情节参考."""
        cool_points, hooks = await self._generate_chapter_data(
            project_id, volume_no, chapter_no, user_ideas
        )

        project = await self.session.get(Project, project_id)
        volume_count = project.volume_count if project else 1
        chapters_per_volume = project.chapters_per_volume if project else 10

        fixed_hooks = []
        for h in hooks:
            fixed, _ = self._fix_recycle_order(h, volume_count, chapters_per_volume)
            fixed_hooks.append(fixed)

        await self.save_chapter_hooks(project_id, volume_no, chapter_no, cool_points, fixed_hooks)

        return ChapterHookDto(
            volume_no=volume_no,
            chapter_no=chapter_no,
            cool_points=cool_points,
            hooks=fixed_hooks,
        )

    async def save_chapter_hooks(
        self,
        project_id: str,
        volume_no: int,
        chapter_no: int,
        cool_points: list[CoolPointDto],
        hooks: list[HookDto],
    ) -> None:
        """单事务内删除该章原有爽点钩子后写入新的."""
        project = await self.session.get(Project, project_id)
        vc = project.volume_count if project else 20
        cc = project.chapters_per_volume if project else 100

        existing_cool = await self.session.execute(
            select(CoolPoint).where(
                CoolPoint.project_id == project_id,
                CoolPoint.volume_no == volume_no,
                CoolPoint.chapter_no == chapter_no,
            )
        )
        for cp in existing_cool.scalars().all():
            await self.session.delete(cp)

        existing_hooks = await self.session.execute(
            select(Hook).where(
                Hook.project_id == project_id,
                Hook.volume_no == volume_no,
                Hook.chapter_no == chapter_no,
            )
        )
        for h in existing_hooks.scalars().all():
            await self.session.delete(h)

        await self.session.flush()

        for cp in cool_points:
            entity = CoolPoint(
                cool_id=str(uuid.uuid4()),
                project_id=project_id,
                volume_no=volume_no,
                chapter_no=chapter_no,
                cool_type=cp.cool_type,
                content_desc=cp.content_desc,
                source=cp.source,
            )
            self.session.add(entity)

        for h in hooks:
            fixed, _ = self._fix_recycle_order(h, vc, cc)
            entity = Hook(
                hook_id=str(uuid.uuid4()),
                project_id=project_id,
                volume_no=volume_no,
                chapter_no=chapter_no,
                hook_content=fixed.hook_content,
                recycle_volume_no=fixed.recycle_volume_no,
                recycle_chapter_no=fixed.recycle_chapter_no,
                recycle_status=fixed.recycle_status,
                source=fixed.source,
            )
            self.session.add(entity)

        await self.session.commit()

    async def get_generation_progress(self, project_id: str) -> dict:
        """返回已生成爽点钩子的章节列表."""
        cool_points = await self.list_cool_points(project_id)
        hooks = await self.list_hooks(project_id)
        cool_map = {(cp.volume_no, cp.chapter_no) for cp in cool_points}
        hook_map = {(h.volume_no, h.chapter_no) for h in hooks}
        generated = sorted(cool_map & hook_map)
        return {
            "generated_chapters": [[v, c] for v, c in generated],
            "total_generated": len(generated),
            "is_complete": False,
        }

    async def get_chapter_hooks(
        self, project_id: str, volume_no: int, chapter_no: int
    ) -> tuple[list[CoolPointDto], list[HookDto]]:
        """返回指定章节的爽点钩子."""
        all_cool = await self.list_cool_points(project_id)
        all_hooks = await self.list_hooks(project_id)
        cool = [cp for cp in all_cool if cp.volume_no == volume_no and cp.chapter_no == chapter_no]
        hooks = [h for h in all_hooks if h.volume_no == volume_no and h.chapter_no == chapter_no]
        return cool, hooks

    async def _get_prev_hooks(
        self, project_id: str, volume_no: int, chapter_no: int, count: int = 3
    ) -> list[HookDto]:
        """获取前 N 章已生成钩子作为上下文."""
        all_hooks = await self.list_hooks(project_id)
        prev: list[HookDto] = []
        sorted_hooks = sorted(all_hooks, key=lambda h: (h.volume_no, h.chapter_no))
        for h in sorted_hooks:
            if (h.volume_no, h.chapter_no) < (volume_no, chapter_no):
                prev.append(h)
        return prev[-count:] if len(prev) > count else prev

    async def delete_cool_points(self, project_id: str, cool_ids: list[str]) -> int:
        """单事务内批量删除当前项目的爽点."""
        if not cool_ids:
            raise ValueError("未选中任何爽点")
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        result = await self.session.execute(
            select(CoolPoint).where(
                CoolPoint.project_id == project_id,
                CoolPoint.cool_id.in_(cool_ids),
            )
        )
        entities = result.scalars().all()
        for entity in entities:
            await self.session.delete(entity)
        await self.session.commit()
        return len(entities)

    async def delete_hooks(self, project_id: str, hook_ids: list[str]) -> int:
        """单事务内批量删除当前项目的钩子."""
        if not hook_ids:
            raise ValueError("未选中任何钩子")
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        result = await self.session.execute(
            select(Hook).where(
                Hook.project_id == project_id,
                Hook.hook_id.in_(hook_ids),
            )
        )
        entities = result.scalars().all()
        for entity in entities:
            await self.session.delete(entity)
        await self.session.commit()
        return len(entities)

    async def save_cool_points_batch(self, project_id: str, cool_points: list[CoolPointDto]) -> list[CoolPointDto]:
        """单事务内覆盖式保存当前项目全部爽点."""
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        for cp in cool_points:
            if not (1 <= cp.volume_no <= 20):
                raise ValueError(f"卷号超出范围: {cp.volume_no}")
            if not (1 <= cp.chapter_no <= 100):
                raise ValueError(f"章号超出范围: {cp.chapter_no}")
            if not cp.cool_type.strip():
                raise ValueError("爽点类型不能为空")
            if not cp.content_desc.strip():
                raise ValueError("爽点描述不能为空")
        existing = await self.session.execute(
            select(CoolPoint).where(CoolPoint.project_id == project_id)
        )
        for entity in existing.scalars().all():
            await self.session.delete(entity)
        await self.session.flush()
        result: list[CoolPointDto] = []
        for cp in cool_points:
            entity = CoolPoint(
                cool_id=str(uuid.uuid4()),
                project_id=project_id,
                volume_no=cp.volume_no,
                chapter_no=cp.chapter_no,
                cool_type=cp.cool_type,
                content_desc=cp.content_desc,
                source=cp.source,
            )
            self.session.add(entity)
            await self.session.flush()
            new_dto = cp.model_copy()
            new_dto.cool_id = entity.cool_id
            new_dto.project_id = project_id
            result.append(new_dto)
        await self.session.commit()
        return result

    async def save_hooks_batch(self, project_id: str, hooks: list[HookDto]) -> list[HookDto]:
        """单事务内覆盖式保存当前项目全部钩子."""
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        vc = project.volume_count
        cc = project.chapters_per_volume
        for h in hooks:
            if not (1 <= h.volume_no <= vc):
                raise ValueError(f"卷号超出范围: {h.volume_no}")
            if not (1 <= h.chapter_no <= cc):
                raise ValueError(f"章号超出范围: {h.chapter_no}")
            if not h.hook_content.strip():
                raise ValueError("钩子内容不能为空")
        existing = await self.session.execute(
            select(Hook).where(Hook.project_id == project_id)
        )
        for entity in existing.scalars().all():
            await self.session.delete(entity)
        await self.session.flush()
        result: list[HookDto] = []
        for h in hooks:
            fixed, _ = self._fix_recycle_order(h, vc, cc)
            entity = Hook(
                hook_id=str(uuid.uuid4()),
                project_id=project_id,
                volume_no=h.volume_no,
                chapter_no=h.chapter_no,
                hook_content=h.hook_content,
                recycle_volume_no=fixed.recycle_volume_no,
                recycle_chapter_no=fixed.recycle_chapter_no,
                recycle_status=fixed.recycle_status,
                source=h.source,
            )
            self.session.add(entity)
            await self.session.flush()
            new_dto = h.model_copy()
            new_dto.hook_id = entity.hook_id
            new_dto.project_id = project_id
            result.append(new_dto)
        await self.session.commit()
        return result

    async def check_consistency(
        self, project_id: str,
        garbled_config: "GarbledConfig | None" = None,
    ) -> HookConsistencyResult:
        """校验爽点钩子与梗概/世界观/人物/大纲的一致性."""
        from src.services.outline_service import OutlineService
        from src.services.character_service import CharacterService
        from src.db.models import Synopsis, Worldview
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

        char_service = CharacterService(self.session)
        confirmed = await char_service.list_confirmed(project_id)
        if not confirmed:
            raise ValueError("请先确认人物清单")

        outline_service = OutlineService(self.session)
        outline = await outline_service.get_outline(project_id)
        if outline is None:
            raise ValueError("请先在大纲管理中生成大纲")

        cool_points = await self.list_cool_points(project_id)
        hooks = await self.list_hooks(project_id)

        outline_chapters = []
        for vol in outline.volumes:
            for ch in vol.chapters:
                outline_chapters.append({
                    "volume_no": vol.volume_no,
                    "chapter_no": ch.chapter_no,
                    "synopsis_points": ch.synopsis_points,
                })

        await release_write_lock(self.session)

        try:
            result = await self.gateway.call_and_parse(
                module="hook",
                scene="check-consistency",
                params={
                    "synopsis": synopsis.content,
                    "worldview": worldview.content,
                    "characters": [c.model_dump() for c in confirmed],
                    "outline_chapters": outline_chapters,
                    "cool_points": [cp.model_dump() for cp in cool_points],
                    "hooks": [h.model_dump() for h in hooks],
                    "garbled_config_enabled": garbled_config.enabled,
                },
                project_id=project_id,
                timeout_seconds=get_config().hook_check_consistency_timeout_seconds,
                max_tokens=8192,
            )
            parsed = result.get("parsed", {})
            ai_issues = [
                HookConsistencyIssue(
                    level=iss.get("level", "一般"),
                    volume_no=iss.get("volume_no", 0),
                    chapter_no=iss.get("chapter_no", 0),
                    type=iss.get("type", "其他"),
                    detail=iss.get("detail", ""),
                    suggestion=iss.get("suggestion", ""),
                )
                for iss in parsed.get("issues", [])
            ]
            score = parsed.get("score", 100)
            summary = parsed.get("summary", "")
        except TimeoutError:
            ai_issues = []
            score = 0
            summary = "AI校验超时，仅展示规则校验结果，建议重试"
        except Exception as e:
            self.logger.warning(f"AI校验异常降级: {e}")
            ai_issues = []
            score = 0
            summary = f"AI校验异常，仅展示规则校验结果：{e}"

        issues = ai_issues + self._rule_check_hooks(
            confirmed, cool_points, hooks,
            volume_count=project.volume_count,
            chapters_per_volume=project.chapters_per_volume,
            garbled_config=garbled_config,
        )

        seen: dict[tuple, HookConsistencyIssue] = {}
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
        return HookConsistencyResult(
            score=score,
            summary=summary,
            issues=issues,
            text=text,
        )

    @staticmethod
    def _fix_recycle_order(
        hook: HookDto, volume_count: int, chapters_per_volume: int
    ) -> tuple[HookDto, bool]:
        """修正钩子回收顺序：回收点必须严格晚于埋钩点且在全书范围内."""
        v, c = hook.volume_no, hook.chapter_no
        rv, rc = hook.recycle_volume_no, hook.recycle_chapter_no
        fixed = False
        if rv < 1 or rv > volume_count:
            rv = min(max(rv, 1), volume_count)
            fixed = True
        if rc < 1 or rc > chapters_per_volume:
            rc = min(max(rc, 1), chapters_per_volume)
            fixed = True
        if (rv, rc) > (v, c):
            if fixed:
                return hook.model_copy(update={"recycle_volume_no": rv, "recycle_chapter_no": rc}), True
            return hook, False
        if c < chapters_per_volume:
            rv, rc = v, chapters_per_volume
        elif v < volume_count and (v + 1 - hook.volume_no) <= MAX_RECYCLE_DISTANCE_VOLUMES:
            rv, rc = v + 1, 1
        else:
            rv, rc = v, c
            hook.recycle_status = "unrecycled"
            return hook.model_copy(update={"recycle_volume_no": rv, "recycle_chapter_no": rc}), True
        return hook.model_copy(update={"recycle_volume_no": rv, "recycle_chapter_no": rc}), True

    @staticmethod
    def _rule_check_hooks(
        characters: list, cool_points: list[CoolPointDto], hooks: list[HookDto],
        volume_count: int = 20, chapters_per_volume: int = 100,
        garbled_config: "GarbledConfig | None" = None,
    ) -> list[HookConsistencyIssue]:
        """确定性规则检查：钩子未回收、回收距离超限、回收顺序、回收超出范围、回收过于集中."""
        issues: list[HookConsistencyIssue] = []
        known_names = {c.name for c in characters if c.name}

        for h in hooks:
            if h.recycle_status == "pending":
                issues.append(HookConsistencyIssue(
                    level="一般",
                    volume_no=h.volume_no,
                    chapter_no=h.chapter_no,
                    type="钩子未回收",
                    detail=f"第{h.volume_no}卷第{h.chapter_no}章钩子尚未回收",
                    suggestion=f"检查第{h.recycle_volume_no}卷第{h.recycle_chapter_no}章是否已生成并回收该钩子",
                ))
            dist = abs(h.recycle_volume_no - h.volume_no)
            if dist > MAX_RECYCLE_DISTANCE_VOLUMES:
                issues.append(HookConsistencyIssue(
                    level="严重",
                    volume_no=h.volume_no,
                    chapter_no=h.chapter_no,
                    type="回收距离超限",
                    detail=f"钩子回收距离为 {dist} 卷，超过 {MAX_RECYCLE_DISTANCE_VOLUMES} 卷上限",
                    suggestion=f"将回收章节调整到第{h.volume_no + MAX_RECYCLE_DISTANCE_VOLUMES}卷以内",
                ))
            if (h.recycle_volume_no, h.recycle_chapter_no) <= (h.volume_no, h.chapter_no):
                issues.append(HookConsistencyIssue(
                    level="严重",
                    volume_no=h.volume_no,
                    chapter_no=h.chapter_no,
                    type="回收顺序错误",
                    detail=f"回收点第{h.recycle_volume_no}卷第{h.recycle_chapter_no}章早于或等于埋钩点第{h.volume_no}卷第{h.chapter_no}章",
                    suggestion=f"将回收章节调整至第{h.volume_no}卷第{h.chapter_no}章之后",
                ))
            if h.recycle_volume_no > volume_count or h.recycle_chapter_no > chapters_per_volume:
                issues.append(HookConsistencyIssue(
                    level="严重",
                    volume_no=h.volume_no,
                    chapter_no=h.chapter_no,
                    type="回收超出范围",
                    detail=f"回收点第{h.recycle_volume_no}卷第{h.recycle_chapter_no}章超出全书范围（{volume_count}卷{chapters_per_volume}章）",
                    suggestion=f"将回收章节调整至全书范围内（1-{volume_count}卷，1-{chapters_per_volume}章）",
                ))

        recycle_counts: dict[tuple[int, int], int] = {}
        for h in hooks:
            key = (h.recycle_volume_no, h.recycle_chapter_no)
            recycle_counts[key] = recycle_counts.get(key, 0) + 1
        threshold = max(3, len(hooks) // 5)
        for (rv, rc), count in recycle_counts.items():
            if count > threshold:
                issues.append(HookConsistencyIssue(
                    level="一般",
                    volume_no=rv,
                    chapter_no=rc,
                    type="回收过于集中",
                    detail=f"第{rv}卷第{rc}章被 {count} 个钩子同时设为回收点，超过阈值 {threshold}，回收过于集中",
                    suggestion="分散钩子回收点至不同章节，避免同一章集中回收大量钩子",
                ))

        for cp in cool_points:
            desc = cp.content_desc or ""
            for name in known_names:
                if name and name in desc:
                    break
            else:
                mentioned = [w for w in desc if w in "，。、；：！？"]
                if mentioned or len(desc) > 5:
                    pass

        if garbled_config and garbled_config.enabled:
            from src.services.garbled_normalizer import GarbledNormalizer
            normalizer = GarbledNormalizer()
            for cp in cool_points:
                desc = cp.content_desc or ""
                if not desc:
                    continue
                for gi in normalizer.detect_only(desc, garbled_config):
                    issues.append(HookConsistencyIssue(
                        level=gi.level,
                        volume_no=cp.volume_no,
                        chapter_no=cp.chapter_no,
                        type=gi.category,
                        detail=f"爽点描述位置{gi.position}：{gi.category}",
                        suggestion=gi.suggestion,
                    ))
            for h in hooks:
                hc = h.hook_content or ""
                if not hc:
                    continue
                for gi in normalizer.detect_only(hc, garbled_config):
                    issues.append(HookConsistencyIssue(
                        level=gi.level,
                        volume_no=h.volume_no,
                        chapter_no=h.chapter_no,
                        type=gi.category,
                        detail=f"钩子内容位置{gi.position}：{gi.category}",
                        suggestion=gi.suggestion,
                    ))

        return issues

    @staticmethod
    def _format_consistency_text(score: int, summary: str, issues: list[HookConsistencyIssue]) -> str:
        """生成便于整段复制的纯文本报告."""
        lines = [
            f"爽点钩子一致性评分：{score} / 100",
            f"总体评价：{summary}" if summary else "",
            "",
        ]
        if issues:
            level_order = {"严重": 0, "一般": 1, "轻微": 2}
            sorted_issues = sorted(issues, key=lambda x: (level_order.get(x.level, 9), x.volume_no, x.chapter_no))
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
            lines.append("未发现问题：爽点钩子与梗概、世界观、人物设定、大纲基本一致。")
            lines.append("")
        return "\n".join(lines)


    async def _build_repair_context(
        self, project_id: str, volume_no: int, chapter_no: int
    ) -> dict:
        """装配修复提示词所需上下文."""
        from src.services.outline_service import OutlineService
        from src.services.character_service import CharacterService
        from src.db.models import Synopsis, Worldview

        outline_service = OutlineService(self.session)
        chapter_synopsis = await outline_service.get_chapter_synopsis(
            project_id, volume_no, chapter_no
        )
        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        if not synopsis or not worldview:
            raise ValueError("故事梗概或世界观缺失")

        char_service = CharacterService(self.session)
        confirmed = await char_service.list_confirmed(project_id)
        prev_hooks = await self._get_prev_hooks(project_id, volume_no, chapter_no)
        naming_favorites = await NamingService(self.session).list_favorites_grouped(project_id)
        cool_points, hooks = await self.get_chapter_hooks(project_id, volume_no, chapter_no)

        return {
            "synopsis": synopsis.content,
            "worldview": worldview.content,
            "characters": [c.model_dump() for c in confirmed],
            "chapter_synopsis": chapter_synopsis or "",
            "prev_hooks": [h.model_dump() for h in prev_hooks],
            "naming_favorites": naming_favorites,
            "cool_points": [cp.model_dump() for cp in cool_points],
            "hooks": [h.model_dump() for h in hooks],
        }

    async def repair_hook_stream(
        self,
        project_id: str,
        issues: list[HookConsistencyIssue],
        repair_scope: str = "all",
        garbled_config: "GarbledConfig | None" = None,
    ) -> AsyncGenerator[HookRepairStreamChunk, None]:
        """SSE 流式逐章修复爽点钩子."""
        from src.services.garbled_config_service import GarbledConfigService
        from src.services.garbled_normalizer import GarbledNormalizer

        project = await self.session.get(Project, project_id)
        if not project:
            yield HookRepairStreamChunk(type="error", message="项目不存在")
            return

        if garbled_config is None:
            cfg_svc = GarbledConfigService(self.session)
            garbled_config = await cfg_svc.resolve_effective_config(project_id)
        normalizer = GarbledNormalizer()
        if not issues:
            yield HookRepairStreamChunk(type="error", message="问题清单为空")
            return

        volume_count = project.volume_count
        chapters_per_volume = project.chapters_per_volume

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
            yield HookRepairStreamChunk(type="error", message="未找到需修复的章节")
            return

        success = 0
        failed = 0
        skipped = 0

        for idx, (v, c) in enumerate(target_chapters, 1):
            ch_issues = [
                {"level": i.level, "type": i.type, "detail": i.detail, "suggestion": i.suggestion}
                for i in issues if i.volume_no == v and i.chapter_no == c
            ]
            yield HookRepairStreamChunk(
                type="progress", volume_no=v, chapter_no=c, done=idx, total=total
            )

            try:
                ctx = await self._build_repair_context(project_id, v, c)
            except Exception as e:
                skipped += 1
                yield HookRepairStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    status="跳过", fail_reason=str(e),
                )
                continue

            await release_write_lock(self.session)

            try:
                result = await self.gateway.call_and_parse(
                    module="hook",
                    scene="repair-hook",
                    params={
                        **ctx,
                        "volume_no": v,
                        "chapter_no": c,
                        "chapter_issues": ch_issues,
                        "garbled_config_enabled": garbled_config.enabled,
                    },
                    project_id=project_id,
                    timeout_seconds=get_config().hook_repair_timeout_seconds,
                )
                parsed = result.get("parsed", {})
            except TimeoutError:
                skipped += 1
                yield HookRepairStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    status="跳过", fail_reason="AI 超时",
                )
                continue
            except Exception as e:
                skipped += 1
                yield HookRepairStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    status="跳过", fail_reason=str(e),
                )
                continue

            cool_new = parsed.get("cool_points_new", [])
            hooks_new = parsed.get("hooks_new", [])

            existing_cool = ctx.get("cool_points", []) or []
            existing_hooks = ctx.get("hooks", []) or []
            if len(cool_new) < len(existing_cool) or len(hooks_new) < len(existing_hooks):
                self.logger.warning(
                    f"AI修复返回数据不完整(爽点{len(cool_new)}/{len(existing_cool)}，"
                    f"钩子{len(hooks_new)}/{len(existing_hooks)})，跳过覆盖写入保留原数据"
                )
                skipped += 1
                yield HookRepairStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    status="跳过", fail_reason="AI返回数据不完整，保留原数据",
                )
                continue

            min_len = get_config().min_ai_content_length
            has_short = any(
                len(str(cp.get("content", ""))) < min_len for cp in cool_new
            ) or any(
                len(str(h.get("content", ""))) < min_len for h in hooks_new
            )
            if has_short:
                failed += 1
                yield HookRepairStreamChunk(
                    type="chapter_skip", volume_no=v, chapter_no=c,
                    status="失败", fail_reason="修复内容过短",
                )
                continue

            cool_dtos = [
                CoolPointDto(
                    volume_no=v, chapter_no=c,
                    cool_type=cp.get("type", cp.get("cool_type", "")),
                    content_desc=cp.get("content", cp.get("content_desc", "")),
                    source="ai_design",
                )
                for cp in cool_new
            ]
            hook_dtos = []
            auto_fixed = False
            for h in hooks_new:
                dto = HookDto(
                    volume_no=v, chapter_no=c,
                    hook_content=h.get("content", h.get("hook_content", "")),
                    recycle_volume_no=h.get("recycle_volume_no", v),
                    recycle_chapter_no=h.get("recycle_chapter_no", c),
                    recycle_status=h.get("recycle_status", "pending"),
                    source="ai_design",
                )
                fixed, was_fixed = self._fix_recycle_order(dto, volume_count, chapters_per_volume)
                if was_fixed:
                    auto_fixed = True
                hook_dtos.append(fixed)

            char_repair_stat = None
            if garbled_config.enabled:
                stat_total = {"garbled_detected": 0, "format_detected": 0, "irreversible_cleared": 0}
                for cp_dto in cool_dtos:
                    normalized, stat = normalizer.detect_and_normalize(cp_dto.content_desc, garbled_config)
                    cp_dto.content_desc = normalized
                    stat_total["garbled_detected"] += stat.garbled_detected
                    stat_total["format_detected"] += stat.format_detected
                    stat_total["irreversible_cleared"] += stat.irreversible_cleared
                for h_dto in hook_dtos:
                    normalized, stat = normalizer.detect_and_normalize(h_dto.hook_content, garbled_config)
                    h_dto.hook_content = normalized
                    stat_total["garbled_detected"] += stat.garbled_detected
                    stat_total["format_detected"] += stat.format_detected
                    stat_total["irreversible_cleared"] += stat.irreversible_cleared
                if stat_total["garbled_detected"] or stat_total["format_detected"]:
                    char_repair_stat = stat_total

            await self.save_chapter_hooks(project_id, v, c, cool_dtos, hook_dtos)

            success += 1
            yield HookRepairStreamChunk(
                type="chapter_done",
                volume_no=v, chapter_no=c,
                cool_points_new=[cp.model_dump() for cp in cool_dtos],
                hooks_new=[h.model_dump() for h in hook_dtos],
                auto_fixed=auto_fixed,
                char_repair_stat=char_repair_stat,
            )

        yield HookRepairStreamChunk(
            type="completed",
            success=success,
            failed=failed,
            skipped=skipped,
            message=f"修复完成：成功 {success}，失败 {failed}，跳过 {skipped}",
        )


from src.db.models import Chapter