"""自动生成配角服务 - 三处触发入口（撰写/大纲生成/爽点钩子设计）.

检测配角缺口 → 自动生成 → 增量去重合并 → 持久化判定 → 来源标记 → 局限性告知.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.character_schema import (
    CharacterDto,
    EnsureResult,
    PersistDecision,
    SupportingDraft,
)
from src.config.settings import get_config
from src.db.session import release_write_lock
from src.services.character_service import CharacterService
from src.services.supporting_builder import SupportingBuilder
from src.utils.logger import get_logger

_MAX_BATCH = 5
_SUPPORTING_TIMEOUT = 60


class AutoSupportingService:
    """自动生成配角统一服务，提供三个触发入口."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()
        self.character_service = CharacterService(session)
        self.builder = SupportingBuilder()

    async def ensure_sufficient_for_writing(
        self,
        project_id: str,
        volume_no: int,
        chapter_no: int,
        context: dict[str, Any] | None = None,
    ) -> EnsureResult:
        """撰写过程配角不足自动触发."""
        ctx = context or {}
        ctx.setdefault("scene_type", "撰写过程")
        ctx.setdefault("volume_no", volume_no)
        ctx.setdefault("chapter_no", chapter_no)
        return await self._ensure(project_id, ctx)

    async def ensure_sufficient_for_outline(
        self,
        project_id: str,
        synopsis: str,
        worldview: str,
        characters: list[CharacterDto],
    ) -> EnsureResult:
        """大纲生成配角不足自动触发."""
        ctx = {
            "scene_type": "大纲生成",
            "plot_requirement": "根据梗概与世界观规划所需配角",
            "synopsis": synopsis,
            "worldview": worldview,
            "existing_characters": characters,
        }
        return await self._ensure(project_id, ctx)

    async def ensure_sufficient_for_hook(
        self,
        project_id: str,
        volume_no: int,
        chapter_no: int,
        context: dict[str, Any] | None = None,
    ) -> EnsureResult:
        """爽点钩子设计配角不足自动触发."""
        ctx = context or {}
        ctx.setdefault("scene_type", "爽点钩子设计")
        ctx.setdefault("volume_no", volume_no)
        ctx.setdefault("chapter_no", chapter_no)
        return await self._ensure(project_id, ctx)

    async def _ensure(self, project_id: str, context: dict[str, Any]) -> EnsureResult:
        """统一检测-生成-合并流程."""
        # 本流程会发起多次 AI 网关调用（缺口检测 + 分批生成，单次最长
        # _SUPPORTING_TIMEOUT）。调用方（大纲/撰写/爽点钩子）的事务里可能已有
        # 未提交的写（例如大纲 reset 的 flush），必须先结束事务释放 SQLite 写锁，
        # 否则这些 AI 调用期间写锁一直被本连接持有，网关自身的计数器写回都会
        # 撞 database is locked。
        await release_write_lock(self.session)

        gap = await self._detect_gap(project_id, context)
        if gap <= 0:
            return EnsureResult()

        added, temporary, warnings = await self._generate_supporting(
            project_id, gap, context
        )

        decisions = self._determine_persistence(added, context)
        persisted: list[CharacterDto] = []
        for dec in decisions:
            if dec.should_persist:
                persisted.append(dec.character)
            else:
                temporary.append(
                    SupportingDraft(
                        name=dec.character.name,
                        identity=dec.character.identity,
                        intro=dec.character.intro or "",
                        relation=dec.character.relation or "",
                        future_reference=False,
                    )
                )
                await self._remove_temporary(dec.character.character_id or "")

        worldview = context.get("worldview", "")
        limitation = self._notify_limitations(worldview, gap)

        # 流程内 merge_characters 已 flush 落库（持有写锁），必须在返回前释放，
        # 否则调用方（撰写/大纲/爽点钩子）随后的 AI 调用期间写锁一直被持有，
        # 撞 database is locked（详见本方法开头的注释）。
        await release_write_lock(self.session)

        return EnsureResult(
            added=persisted,
            temporary=temporary,
            skipped=0,
            warnings=warnings,
            limitation_notice=limitation,
        )

    async def _detect_gap(
        self, project_id: str, context: dict[str, Any]
    ) -> int:
        """检测配角缺口数量."""
        confirmed = await self.character_service.list_confirmed(project_id)
        supporting_count = sum(
            1 for c in confirmed if "配角" in c.identity
        )
        if supporting_count >= 3:
            return 0

        scene_type = context.get("scene_type", "撰写过程")
        plot_req = context.get("plot_requirement", "根据剧情需要补充配角")
        synopsis = context.get("synopsis", "")
        worldview = context.get("worldview", "")

        try:
            result = await self.gateway.call_and_parse(
                module="character",
                scene="auto-generate-supporting",
                params={
                    "synopsis": synopsis,
                    "worldview": worldview,
                    "existing_characters": [c.model_dump() for c in confirmed],
                    "scene_context": {
                        "scene_type": scene_type,
                        "plot_requirement": plot_req,
                    },
                    "count": 1,
                },
                project_id=project_id,
                timeout_seconds=_SUPPORTING_TIMEOUT,
            )
            parsed = result.get("parsed", {})
            needed = parsed.get("needed_count", 3)
            return max(0, int(needed) - supporting_count)
        except Exception as e:
            self.logger.warning(f"配角缺口检测失败，使用默认值: {e}")
            return max(0, 3 - supporting_count)

    async def _generate_supporting(
        self,
        project_id: str,
        count: int,
        context: dict[str, Any],
    ) -> tuple[list[CharacterDto], list[SupportingDraft], list[str]]:
        """生成配角，数量超限分批，返回(新增DTO, 临时配角, 警告列表)."""
        warnings: list[str] = []
        all_added: list[CharacterDto] = []
        temporary: list[SupportingDraft] = []

        batches = self._split_batches(count)
        for batch_size in batches:
            if batch_size == 0:
                continue
            drafts = await self.builder.build_and_call(
                synopsis=context.get("synopsis", ""),
                worldview=context.get("worldview", ""),
                existing=await self.character_service.list_by_project(project_id),
                scene_context=context,
                count=batch_size,
                project_id=project_id,
                timeout_seconds=_SUPPORTING_TIMEOUT,
            )

            for d in drafts:
                if not d.name.strip():
                    warnings.append("存在缺姓名的配角，已跳过")
                    continue

            dtos = [
                CharacterDto(
                    name=d.name,
                    identity=d.identity,
                    intro=d.intro,
                    relation=d.relation,
                    source="auto_generated",
                    confirmed=False,
                    future_reference=d.future_reference,
                    supporting_type="正式配角" if d.future_reference else "临时配角",
                    auto_gen_context=json.dumps(
                        {
                            "scene_type": context.get("scene_type", ""),
                            "volume_no": context.get("volume_no", 1),
                            "chapter_no": context.get("chapter_no", 1),
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        ensure_ascii=False,
                    ),
                )
                for d in drafts
                if d.name.strip()
            ]

            if dtos:
                merge_result = await self.character_service.merge_characters(
                    project_id, dtos
                )
                all_added.extend(merge_result.added)
                if merge_result.skipped_count > 0:
                    warnings.append(
                        f"有 {merge_result.skipped_count} 个同名人物已跳过"
                    )

            overlap = await self._check_role_overlap(project_id, dtos)
            warnings.extend(overlap)

        if count > _MAX_BATCH:
            warnings.append(
                f"本次需生成 {count} 个配角超过上限 {_MAX_BATCH} 人，已分批生成"
            )

        return all_added, temporary, warnings

    def _split_batches(self, count: int) -> list[int]:
        """将 count 拆分为每批不超过 _MAX_BATCH 的列表."""
        if count <= _MAX_BATCH:
            return [count]
        batches: list[int] = []
        remaining = count
        while remaining > 0:
            batch = min(remaining, _MAX_BATCH)
            batches.append(batch)
            remaining -= batch
        return batches

    def _determine_persistence(
        self,
        generated: list[CharacterDto],
        context: dict[str, Any],
    ) -> list[PersistDecision]:
        """判定每个配角是否持久化."""
        decisions: list[PersistDecision] = []
        for ch in generated:
            if ch.future_reference is True:
                decisions.append(
                    PersistDecision(
                        character=ch,
                        should_persist=True,
                        reason="AI标注后续剧情有引用价值",
                    )
                )
            elif ch.future_reference is False:
                decisions.append(
                    PersistDecision(
                        character=ch,
                        should_persist=False,
                        reason="仅单章一次性出场，后续无引用",
                    )
                )
            else:
                decisions.append(
                    PersistDecision(
                        character=ch,
                        should_persist=True,
                        reason="无法判断后续引用，保守持久化",
                    )
                )
        return decisions

    async def _remove_temporary(self, character_id: str) -> None:
        """从 characters 表删除临时配角."""
        if not character_id:
            return
        try:
            await self.character_service.delete(character_id)
            await self.session.commit()
        except Exception as e:
            self.logger.warning(f"删除临时配角失败: {e}")

    async def _check_role_overlap(
        self, project_id: str, new_chars: list[CharacterDto]
    ) -> list[str]:
        """检测角色定位重叠."""
        if not new_chars:
            return []
        existing = await self.character_service.list_by_project(project_id)
        existing_identities = {c.identity for c in existing if c.identity}
        warnings: list[str] = []
        for ch in new_chars:
            if ch.identity in existing_identities:
                warnings.append(
                    f'配角"{ch.name}"身份"{ch.identity}"与已有人物重叠，请确认'
                )
        return warnings

    def _notify_limitations(self, worldview: str, count: int) -> str:
        """生成局限性提醒文案."""
        notice = "AI生成配角可能存在质量或历史信息准确性问题，请确认核实"
        historical_keywords = ("历史", "神话", "封神", "洪荒", "西游", "三国", "春秋", "战国")
        if any(kw in worldview for kw in historical_keywords):
            notice += "。历史/神话题材人物信息请核实准确性"
        return notice