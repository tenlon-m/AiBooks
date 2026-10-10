"""章节修改与AI再校验润色服务 - 最复杂闭环流程.

包含：编辑、再校验、润色、确认、批量再校验、历史回滚。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.chapter_schema import HistoryRecordDto, RollbackResponse
from src.api.schemas.validation_schema import (
    AdjustNoteDto,
    BatchRevalidateResponse,
    PolishResponse,
    RevalidateResponse,
    ValidationItemDto,
)
from src.db.models import (
    Chapter,
    Character,
    Item,
    ModifyRecord,
    Project,
    Synopsis,
    Worldview,
)
from src.db.session import release_write_lock
from src.utils.logger import get_logger


class EditPolishService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def update_chapter_content(
        self, chapter_id: str, new_content: str,
        garbled_config: "GarbledConfig | None" = None,
    ) -> Chapter:
        """更新章节内容并留存修改记录（同事务）."""
        from src.services._chapter_guard import assert_not_locked, create_auto_version_snapshot
        from src.services.garbled_config_service import GarbledConfigService
        from src.services.garbled_normalizer import GarbledNormalizer

        if not new_content.strip():
            raise ValueError("章节内容不能为空")
        chapter = await self.session.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError(f"章节不存在: {chapter_id}")
        await assert_not_locked(self.session, chapter_id)
        if chapter.gen_status == "writing":
            raise ValueError("章节正在生成中，无法编辑")

        if garbled_config is None:
            cfg_svc = GarbledConfigService(self.session)
            garbled_config = await cfg_svc.resolve_effective_config(chapter.project_id)
        if garbled_config.enabled:
            normalizer = GarbledNormalizer()
            new_content, _ = normalizer.detect_and_normalize(new_content, garbled_config)

        content_before = chapter.content
        now = datetime.now(timezone.utc)

        record = ModifyRecord(
            record_id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            modify_type="manual_edit",
            content_before=content_before,
            content_after=new_content,
            modified_at=now,
            is_rollbackable=True,
            polish_confirm_status="none",
        )
        self.session.add(record)

        await create_auto_version_snapshot(self.session, chapter)
        chapter.content = new_content
        chapter.word_count = len(new_content)
        chapter.modify_status = "modified"
        chapter.last_modified_at = now
        await self.session.flush()
        return chapter

    async def revalidate_chapter(self, chapter_id: str) -> RevalidateResponse:
        """单章再校验（4维）."""
        chapter = await self.session.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError(f"章节不存在: {chapter_id}")

        synopsis = await self.session.get(Synopsis, chapter.project_id)
        worldview = await self.session.get(Worldview, chapter.project_id)
        if not synopsis or not worldview:
            raise ValueError("梗概或世界观未设定")

        chars_result = await self.session.execute(
            select(Character).where(Character.project_id == chapter.project_id, Character.confirmed == True)
        )
        characters = list(chars_result.scalars().all())

        params = {
            "synopsis": synopsis.content,
            "worldview": worldview.content,
            "characters": [{"name": c.name, "identity": c.identity} for c in characters],
            "chapter_content": chapter.content or "",
        }

        # 下面要发起 AI 调用。只要本会话（或调用方）还有未提交的 DML，
        # 写锁就会一直被持有到 commit，期间并发的自动保存 / 网关计数器写回
        # 都会撞 database is locked。进入 AI 调用前先结束事务。
        await release_write_lock(self.session)

        try:
            result = await self.gateway.call_and_parse(
                module="validation",
                scene="single-chapter",
                params=params,
                project_id=chapter.project_id,
            )
            parsed = result.get("parsed", {})
            items_data = parsed.get("items", [])
            items = [
                ValidationItemDto(
                    check_type=item.get("check_type", "unknown"),
                    result=item.get("result", "pass"),
                    problem_desc=item.get("problem_desc"),
                )
                for item in items_data
            ]
        except Exception as e:
            self.logger.error(f"再校验失败: {e}")
            items = [ValidationItemDto(check_type="ai_call", result="fail", problem_desc=str(e))]

        all_pass = all(i.result == "pass" for i in items)
        return RevalidateResponse(chapter_id=chapter_id, items=items, all_pass=all_pass)

    async def polish_chapter(
        self, chapter_id: str, user_ideas: str = "",
        garbled_config: "GarbledConfig | None" = None,
    ) -> PolishResponse:
        """AI 自动润色修改内容."""
        from src.services.garbled_config_service import GarbledConfigService
        from src.services.garbled_normalizer import GarbledNormalizer

        chapter = await self.session.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError(f"章节不存在: {chapter_id}")
        if chapter.gen_status == "writing":
            raise ValueError("章节正在生成中，无法润色，请等待撰写完成")

        if garbled_config is None:
            cfg_svc = GarbledConfigService(self.session)
            garbled_config = await cfg_svc.resolve_effective_config(chapter.project_id)
        normalizer = GarbledNormalizer()

        revalidate = await self.revalidate_chapter(chapter_id)
        problems = [i for i in revalidate.items if i.result == "fail"]

        synopsis = await self.session.get(Synopsis, chapter.project_id)
        worldview = await self.session.get(Worldview, chapter.project_id)
        chars_result = await self.session.execute(
            select(Character).where(Character.project_id == chapter.project_id, Character.confirmed == True)
        )
        characters = list(chars_result.scalars().all())

        params = {
            "synopsis": synopsis.content if synopsis else "",
            "worldview": worldview.content if worldview else "",
            "characters": [{"name": c.name, "identity": c.identity} for c in characters],
            "original_content": chapter.content or "",
            "problems": [{"check_type": p.check_type, "problem_desc": p.problem_desc or ""} for p in problems],
            "user_ideas": user_ideas,
            "garbled_config_enabled": garbled_config.enabled,
        }

        # 润色是最长耗时的 AI 调用之一。只要本会话（或调用方）还有未提交的 DML，
        # 写锁就会一直被持有到 commit，期间会阻塞自动保存与网关计数器写回
        # （database is locked）。进入 AI 调用前先结束事务。
        await release_write_lock(self.session)

        result = await self.gateway.call_and_parse(
            module="polish",
            scene="auto-polish",
            params=params,
            project_id=chapter.project_id,
        )
        parsed = result.get("parsed", {})
        polished = parsed.get("polished_content", chapter.content or "")
        if garbled_config.enabled:
            polished, _ = normalizer.detect_and_normalize(polished, garbled_config)
        notes_data = parsed.get("adjust_notes", [])
        notes = [
            AdjustNoteDto(
                position=n.get("position", ""),
                reason=n.get("reason", ""),
                original=n.get("original"),
                polished=n.get("polished"),
            )
            for n in notes_data
        ]

        records_result = await self.session.execute(
            select(ModifyRecord).where(ModifyRecord.chapter_id == chapter_id).order_by(ModifyRecord.modified_at.desc())
        )
        latest_record = records_result.scalars().first()
        if latest_record:
            latest_record.triggered_polish = True
            latest_record.polished_content = polished
            latest_record.polish_notes = str(notes_data)
            await self.session.flush()

        return PolishResponse(polished_content=polished, adjust_notes=notes)

    async def confirm_polish(
        self, chapter_id: str, action: str,
        garbled_config: "GarbledConfig | None" = None,
    ) -> Chapter:
        """确认或拒绝润色结果."""
        from src.services._chapter_guard import assert_not_locked, create_auto_version_snapshot
        from src.services.garbled_config_service import GarbledConfigService
        from src.services.garbled_normalizer import GarbledNormalizer

        chapter = await self.session.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError(f"章节不存在: {chapter_id}")
        await assert_not_locked(self.session, chapter_id)

        if garbled_config is None:
            cfg_svc = GarbledConfigService(self.session)
            garbled_config = await cfg_svc.resolve_effective_config(chapter.project_id)

        records_result = await self.session.execute(
            select(ModifyRecord).where(ModifyRecord.chapter_id == chapter_id).order_by(ModifyRecord.modified_at.desc())
        )
        latest_record = records_result.scalars().first()
        if not latest_record or not latest_record.polished_content:
            raise ValueError("无待确认的润色结果")

        now = datetime.now(timezone.utc)
        if action == "accept":
            polished = latest_record.polished_content
            if garbled_config.enabled:
                normalizer = GarbledNormalizer()
                polished, _ = normalizer.detect_and_normalize(polished, garbled_config)
            await create_auto_version_snapshot(self.session, chapter)
            chapter.content = polished
            chapter.word_count = len(polished)
            chapter.last_modified_at = now
            latest_record.final_content = polished
            latest_record.polish_confirm_status = "accepted"
            latest_record.confirmed_at = now
        else:
            latest_record.final_content = latest_record.content_after
            latest_record.polish_confirm_status = "rejected"
            latest_record.confirmed_at = now
        await self.session.flush()
        return chapter

    async def batch_revalidate(self, project_id: str, chapter_ids: list[str]) -> BatchRevalidateResponse:
        """批量再校验（≤50章）+ 全书人物物品变化汇总."""
        per_chapter = []
        for cid in chapter_ids:
            try:
                result = await self.revalidate_chapter(cid)
                per_chapter.append(result)
            except Exception as e:
                per_chapter.append(RevalidateResponse(
                    chapter_id=cid,
                    items=[ValidationItemDto(check_type="error", result="fail", problem_desc=str(e))],
                    all_pass=False,
                ))

        char_problems = await self._check_character_changes(project_id, chapter_ids)
        item_problems = await self._check_item_changes(project_id, chapter_ids)
        item_consistency_problems = await self._check_item_consistency(project_id)

        return BatchRevalidateResponse(
            per_chapter=per_chapter,
            global_character_change=ValidationItemDto(
                check_type="character_change_consistency",
                result="pass" if not char_problems else "fail",
                problem_desc="; ".join(char_problems) if char_problems else None,
            ),
            global_item_change=ValidationItemDto(
                check_type="item_change_consistency",
                result="pass" if not item_problems else "fail",
                problem_desc="; ".join(item_problems) if item_problems else None,
            ),
            global_item_consistency=ValidationItemDto(
                check_type="item_global_consistency",
                result="pass" if not item_consistency_problems else "fail",
                problem_desc="; ".join(item_consistency_problems) if item_consistency_problems else None,
            ),
        )

    async def _check_character_changes(self, project_id: str, chapter_ids: list[str]) -> list[str]:
        """检查人物变化一致性：章节中出现的人物是否都在已确认列表中，已确认人物是否都出场."""
        problems: list[str] = []
        chars_result = await self.session.execute(
            select(Character).where(Character.project_id == project_id, Character.confirmed == True)
        )
        confirmed_names = {c.name for c in chars_result.scalars().all()}
        if not confirmed_names:
            return problems
        ch_result = await self.session.execute(
            select(Chapter).where(Chapter.chapter_id.in_(chapter_ids))
        )
        appearing_names: set[str] = set()
        for ch in ch_result.scalars().all():
            if ch.characters_appearing:
                for name in ch.characters_appearing.split(","):
                    name = name.strip()
                    if name:
                        appearing_names.add(name)
        undocumented = appearing_names - confirmed_names
        if undocumented:
            problems.append(f"章节中出现未确认人物：{', '.join(sorted(undocumented))}")
        unused = confirmed_names - appearing_names
        if unused:
            problems.append(f"已确认人物未在章节中出场：{', '.join(sorted(unused))}")
        return problems

    async def _check_item_changes(self, project_id: str, chapter_ids: list[str]) -> list[str]:
        """检查物品变化一致性：已定义物品是否在章节内容中被使用."""
        problems: list[str] = []
        items_result = await self.session.execute(
            select(Item).where(Item.project_id == project_id)
        )
        items = list(items_result.scalars().all())
        if not items:
            return problems
        ch_result = await self.session.execute(
            select(Chapter).where(Chapter.chapter_id.in_(chapter_ids))
        )
        all_content = " ".join((ch.content or "") for ch in ch_result.scalars().all())
        unused_items = [it.name for it in items if it.name and it.name not in all_content]
        if unused_items:
            problems.append(f"已定义物品未在章节中出现：{', '.join(sorted(unused_items))}")
        return problems

    async def _check_item_consistency(self, project_id: str) -> list[str]:
        items_result = await self.session.execute(select(Item).where(Item.project_id == project_id))
        items = list(items_result.scalars().all())
        problems = []
        name_type: dict[str, str] = {}
        for it in items:
            if it.name in name_type and name_type[it.name] != it.item_type:
                problems.append(f"物品'{it.name}'类型不一致")
            else:
                name_type[it.name] = it.item_type
        return problems

    async def list_history(self, chapter_id: str) -> list[HistoryRecordDto]:
        """列出章节修改历史."""
        result = await self.session.execute(
            select(ModifyRecord).where(ModifyRecord.chapter_id == chapter_id).order_by(ModifyRecord.modified_at.desc())
        )
        records = list(result.scalars().all())
        return [
            HistoryRecordDto(
                record_id=r.record_id,
                modify_type=r.modify_type,
                modified_at=r.modified_at,
                final_content_preview=(r.final_content or r.content_after or "")[:200],
                is_rollbackable=r.is_rollbackable,
            )
            for r in records
        ]

    async def rollback_chapter(self, chapter_id: str, target_record_id: str) -> RollbackResponse:
        """回滚到历史版本."""
        from src.services._chapter_guard import assert_not_locked

        target = await self.session.get(ModifyRecord, target_record_id)
        if not target:
            raise ValueError(f"历史记录不存在: {target_record_id}")
        if not target.is_rollbackable:
            raise ValueError("该记录不可回滚")
        target_content = target.final_content or target.content_after
        if not target_content:
            raise ValueError("目标记录内容为空")

        chapter = await self.session.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError(f"章节不存在: {chapter_id}")
        await assert_not_locked(self.session, chapter_id)

        content_before = chapter.content
        now = datetime.now(timezone.utc)
        chapter.content = target_content
        chapter.word_count = len(target_content)
        chapter.last_modified_at = now

        rollback_record = ModifyRecord(
            record_id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            modify_type="rollback",
            content_before=content_before,
            content_after=target_content,
            rollback_target_id=target_record_id,
            modified_at=now,
            is_rollbackable=True,
            polish_confirm_status="none",
        )
        self.session.add(rollback_record)
        await self.session.flush()

        return RollbackResponse(chapter_id=chapter_id, success=True, message="回滚成功")
    async def check_chapter_consistency(
        self,
        chapter_id: str,
        user_ideas: str = "",
        garbled_config: "GarbledConfig | None" = None,
    ):
        """校验单章内容与大纲/风格库的一致性，返回 ChapterConsistencyResult."""
        from src.services.outline_service import OutlineService
        from src.services.style_library_service import StyleLibraryService
        from src.api.schemas.validation_schema import (
            ChapterConsistencyIssue,
            ChapterConsistencyResult,
        )
        from src.config.settings import get_config
        from src.services.garbled_config_service import GarbledConfigService

        chapter = await self.session.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError("章节不存在")

        if garbled_config is None:
            cfg_svc = GarbledConfigService(self.session)
            garbled_config = await cfg_svc.resolve_effective_config(chapter.project_id)

        outline_service = OutlineService(self.session)
        outline = await outline_service.get_outline(chapter.project_id)
        if outline is None:
            raise ValueError("大纲不存在")

        chapter_synopsis = await outline_service.get_chapter_synopsis(
            chapter.project_id, chapter.volume_no, chapter.chapter_no
        )

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

        # 下面是最长 chapter_check_consistency_timeout_seconds 的 AI 调用。只要本会话
        # （或调用方）还有未提交的 DML，写锁就会一直被持有到 commit，期间并发的
        # 自动保存 / 网关计数器写回都会撞 database is locked。进入 AI 调用前先结束事务。
        await release_write_lock(self.session)

        result = await self.gateway.call_and_parse(
            module="chapter",
            scene="check-consistency",
            params={
                "volume_no": chapter.volume_no,
                "chapter_no": chapter.chapter_no,
                "chapter_title": chapter.title,
                "chapter_content": chapter.content or "",
                "outline_chapter": chapter_synopsis or "",
                "style_features": style_features_payload,
                "user_ideas": user_ideas,
                "garbled_config_enabled": garbled_config.enabled,
            },
            project_id=chapter.project_id,
            timeout_seconds=get_config().chapter_check_consistency_timeout_seconds,
            max_tokens=8192,
        )
        parsed = result.get("parsed", {})

        issues: list[ChapterConsistencyIssue] = [
            ChapterConsistencyIssue(
                level=iss.get("level", "一般"),
                type=iss.get("type", "其他"),
                detail=iss.get("detail", ""),
                suggestion=iss.get("suggestion", ""),
            )
            for iss in parsed.get("issues", [])
        ]

        issues.extend(
            self._rule_check_chapter_consistency(
                chapter.content or "", chapter_synopsis or "", style_features,
                garbled_config,
            )
        )

        score = parsed.get("score", 100)
        summary = parsed.get("summary", "")
        text = self._format_chapter_consistency_text(score, summary, issues)
        return ChapterConsistencyResult(
            score=score,
            summary=summary,
            issues=issues,
            text=text,
        )

    @staticmethod
    def _rule_check_chapter_consistency(
        content: str,
        outline_chapter: str,
        style_features: list,
        garbled_config: "GarbledConfig | None" = None,
    ) -> list:
        """确定性规则检查：(1)大纲梗概关键词匹配 (2)风格关键词缺失."""
        from src.api.schemas.validation_schema import ChapterConsistencyIssue

        issues: list[ChapterConsistencyIssue] = []

        if outline_chapter and content:
            keywords = [
                w.strip()
                for w in outline_chapter.replace("，", " ").replace("、", " ").split()
                if len(w.strip()) >= 2
            ]
            missed = [kw for kw in keywords[:5] if kw and kw not in content]
            if missed and len(missed) >= 3:
                issues.append(ChapterConsistencyIssue(
                    level="一般",
                    type="偏离大纲",
                    detail=f"章节内容与大纲梗概要点关键词匹配度低，缺失关键词: {('、'.join(missed[:3]))}",
                    suggestion="对照大纲梗概要点补充对应情节",
                ))

        style_keywords: list[str] = []
        for f in style_features:
            desc = getattr(f, "description", "") or ""
            for w in desc.replace("，", " ").replace("、", " ").split():
                w = w.strip()
                if len(w) >= 2:
                    style_keywords.append(w)

        if style_keywords and content:
            hit = sum(1 for kw in style_keywords if kw in content)
            ratio = hit / len(style_keywords) if style_keywords else 0
            if ratio < 0.05 and len(style_keywords) >= 6:
                issues.append(ChapterConsistencyIssue(
                    level="轻微",
                    type="风格偏差",
                    detail=f"风格关键词命中率过低（{ratio:.0%}），可能与风格库特征偏离",
                    suggestion="对照风格库特征调整用词与句式",
                ))

        if garbled_config and garbled_config.enabled and content:
            from src.services.garbled_normalizer import GarbledNormalizer

            normalizer = GarbledNormalizer()
            garbled_issues = normalizer.detect_only(content, garbled_config)
            for gi in garbled_issues:
                issues.append(ChapterConsistencyIssue(
                    level=gi.level,
                    type=gi.category,
                    detail=f"位置{gi.position}：{gi.category}",
                    suggestion=gi.suggestion,
                ))

        return issues

    @staticmethod
    def _format_chapter_consistency_text(score: int, summary: str, issues: list) -> str:
        """生成便于整段复制的纯文本报告."""
        lines = [
            f"章节一致性评分：{score} / 100",
            f"总体评价：{summary}" if summary else "",
            "",
        ]
        if issues:
            level_order = {"严重": 0, "一般": 1, "轻微": 2}
            sorted_issues = sorted(
                issues,
                key=lambda x: level_order.get(x.level, 9),
            )
            lines.append(f"发现问题：{len(sorted_issues)} 条")
            lines.append("=" * 44)
            for idx, issue in enumerate(sorted_issues, 1):
                lines.append(f"[{idx}]【{issue.level}】（{issue.type}）")
                lines.append(f"    问题：{issue.detail}")
                if issue.suggestion:
                    lines.append(f"    建议：{issue.suggestion}")
                lines.append("")
        else:
            lines.append("未发现问题：本章内容与大纲、风格库基本一致。")
            lines.append("")
        return "\n".join(lines)