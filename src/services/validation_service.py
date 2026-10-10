"""内容校验服务 - 全书7维校验+分批+AI化评估."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.validation_schema import (
    CharacterCountIntegrityItem,
    FullBookValidationResponse,
    ValidationItemDto,
)
from src.config.settings import get_config
from src.db.models import (
    Chapter,
    Character,
    Hook,
    Item,
    Project,
    StyleFeature,
    Synopsis,
    ValidationReport,
    Worldview,
)
from src.db.session import release_write_lock
from src.utils.logger import get_logger

VALIDATION_BATCH_THRESHOLD = 500000


class ValidationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def validate_full_book(self, project_id: str, user_ideas: str = "") -> FullBookValidationResponse:
        """全书7维校验."""
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")

        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        if not synopsis or not worldview:
            raise ValueError("梗概或世界观未设定")

        chars_result = await self.session.execute(
            select(Character).where(Character.project_id == project_id, Character.confirmed == True)
        )
        characters = list(chars_result.scalars().all())

        hooks_result = await self.session.execute(select(Hook).where(Hook.project_id == project_id))
        hooks = list(hooks_result.scalars().all())

        items_result = await self.session.execute(select(Item).where(Item.project_id == project_id))
        items = list(items_result.scalars().all())

        chapters_result = await self.session.execute(
            select(Chapter).where(
                Chapter.project_id == project_id,
                Chapter.gen_status == "completed",
            ).order_by(Chapter.volume_no, Chapter.chapter_no)
        )
        chapters = list(chapters_result.scalars().all())
        if not chapters:
            raise ValueError("无已完成章节")

        style_features = []
        if project.style_library_id:
            feat_result = await self.session.execute(
                select(StyleFeature).where(StyleFeature.style_library_id == project.style_library_id)
            )
            style_features = list(feat_result.scalars().all())

        total_chars = sum(c.word_count for c in chapters)
        report_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # 下面的校验会发起 1~N 次 AI 调用（分批时每卷一次，单次可达数十秒）。
        # 只要本会话（或调用方）还有未提交的 DML，写锁就会一直被持有到 commit，
        # 期间并发的自动保存 / 网关计数器写回都会撞 database is locked。
        # 进入这批长 AI 调用前先结束事务，确保不攥着写锁。
        await release_write_lock(self.session)

        if total_chars > VALIDATION_BATCH_THRESHOLD:
            all_items = await self._validate_in_batches(project_id, synopsis, worldview, characters, chapters, hooks, items, style_features, user_ideas)
        else:
            all_items = await self._validate_single_batch(project_id, synopsis, worldview, characters, chapters, hooks, items, style_features, user_ideas)

        char_count_item = await self._check_character_count_integrity(project_id, chapters, characters)
        if char_count_item is not None:
            all_items.append(char_count_item)

        ai_degree_score = "good"
        ai_degree_problems = []
        for item in all_items:
            if item.check_type == "ai_degree_assessment" and item.result == "fail":
                ai_degree_score = "medium"
                if item.problem_desc:
                    ai_degree_problems.append({"problem": item.problem_desc})

        for item in all_items:
            report = ValidationReport(
                report_id=report_id,
                project_id=project_id,
                check_type=item.check_type,
                result=item.result,
                problem_desc=item.problem_desc,
                volume_no=item.volume_no,
                chapter_no=item.chapter_no,
                ai_degree_score=ai_degree_score if item.check_type == "ai_degree_assessment" else None,
                validation_category="full_book",
                validated_at=now,
            )
            self.session.add(report)
        await self.session.flush()

        return FullBookValidationResponse(
            report_id=report_id,
            project_id=project_id,
            items=all_items,
            ai_degree_score=ai_degree_score,
            ai_degree_problems=ai_degree_problems,
            validated_at=now,
        )

    async def _extract_content_characters(
        self, project_id: str, chapters: list, characters: list
    ) -> set[str]:
        """从正文提取出现的人物姓名（姓名匹配 + AI 识别补充）."""
        content_characters: set[str] = set()
        for char in characters:
            name = (char.name or "").strip()
            if not name:
                continue
            for c in chapters:
                if name in (c.content or ""):
                    content_characters.add(name)
                    break

        try:
            await release_write_lock(self.session)
            result = await self.gateway.call_and_parse(
                module="validation",
                scene="character-count-integrity",
                params={
                    "chapters": [
                        {
                            "volume_no": c.volume_no,
                            "chapter_no": c.chapter_no,
                            "content": (c.content or "")[:20000],
                        }
                        for c in chapters
                    ],
                    "characters": [
                        {"name": char.name, "identity": char.identity}
                        for char in characters
                    ],
                },
                project_id=project_id,
                timeout_seconds=get_config().validation_character_count_timeout_seconds,
                max_tokens=8192,
            )
            extra = result.get("parsed", {}).get("extra_characters", [])
            if isinstance(extra, list):
                for name in extra:
                    n = str(name).strip()
                    if n:
                        content_characters.add(n)
        except Exception as e:
            self.logger.warning(f"AI 识别正文人物失败，降级为仅姓名匹配: {e}")

        return content_characters

    async def _check_character_count_integrity(
        self, project_id: str, chapters: list, characters: list
    ) -> CharacterCountIntegrityItem | None:
        """全书人物数量完整性校验."""
        if not chapters or not characters:
            return None
        content_characters = await self._extract_content_characters(project_id, chapters, characters)
        content_character_count = len(content_characters)
        confirmed_character_count = len(characters)
        if content_character_count >= confirmed_character_count:
            result = "pass"
            problem_desc = None
        else:
            result = "fail"
            problem_desc = (
                f"全书正文中实际出现的人物数量为 {content_character_count}，"
                f"已确认人物数量为 {confirmed_character_count}，"
                f"差距 {confirmed_character_count - content_character_count}。"
                f"请检查已确认人物是否均在正文出场，"
                f"或正文是否过于依赖既有人物未引入新人物。"
            )
        return CharacterCountIntegrityItem(
            check_type="character_count_integrity",
            result=result,
            problem_desc=problem_desc,
            volume_no=None,
            chapter_no=None,
            content_character_count=content_character_count,
            confirmed_character_count=confirmed_character_count,
        )

    async def _validate_single_batch(
        self, project_id, synopsis, worldview, characters, chapters, hooks, items, style_features, user_ideas: str = ""
    ) -> list[ValidationItemDto]:
        """单批全量校验."""
        params = {
            "synopsis": synopsis.content,
            "worldview": worldview.content,
            "characters": [{"name": c.name, "identity": c.identity, "relation": c.relation or ""} for c in characters],
            "chapters": [
                {"volume_no": c.volume_no, "chapter_no": c.chapter_no, "title": c.title, "content": c.content or ""}
                for c in chapters
            ],
            "hooks": [
                {"volume_no": h.volume_no, "chapter_no": h.chapter_no, "hook_content": h.hook_content,
                 "recycle_volume_no": h.recycle_volume_no, "recycle_chapter_no": h.recycle_chapter_no,
                 "recycle_status": h.recycle_status}
                for h in hooks
            ],
            "items": [{"name": i.name, "item_type": i.item_type, "owner_character": i.owner_character or ""} for i in items],
            "style_features": [{"dimension": f.dimension, "description": f.description} for f in style_features] if style_features else [],
            "user_ideas": user_ideas,
        }

        try:
            result = await self.gateway.call_and_parse(
                module="validation",
                scene="full-book",
                params=params,
                project_id=project_id,
                max_tokens=8192,
                timeout_seconds=get_config().validation_full_book_timeout,
            )
            parsed = result.get("parsed", {})
            items_data = parsed.get("items", [])
            return [
                ValidationItemDto(
                    check_type=item.get("check_type", "unknown"),
                    result=item.get("result", "pass"),
                    problem_desc=item.get("problem_desc"),
                    volume_no=item.get("volume_no"),
                    chapter_no=item.get("chapter_no"),
                )
                for item in items_data
            ]
        except Exception as e:
            self.logger.error(f"全书校验AI调用失败: {e}")
            return [ValidationItemDto(check_type="ai_call", result="fail", problem_desc=str(e))]

    async def _validate_in_batches(
        self, project_id, synopsis, worldview, characters, chapters, hooks, items, style_features, user_ideas: str = ""
    ) -> list[ValidationItemDto]:
        """按卷分批校验并合并结果."""
        all_items: list[ValidationItemDto] = []
        volume_map: dict[int, list[Chapter]] = {}
        for c in chapters:
            volume_map.setdefault(c.volume_no, []).append(c)

        for vol, vol_chapters in volume_map.items():
            batch_items = await self._validate_single_batch(
                project_id, synopsis, worldview, characters, vol_chapters, hooks, items, style_features, user_ideas
            )
            all_items.extend(batch_items)
        return all_items

    async def get_report(self, report_id: str) -> list[ValidationReport]:
        result = await self.session.execute(
            select(ValidationReport).where(ValidationReport.report_id == report_id)
        )
        return list(result.scalars().all())

    async def list_latest_results(self, project_id: str) -> dict:
        """返回项目最近一次校验报告的全部条目（供校验报告页刷新列表）."""
        latest = await self.session.execute(
            select(ValidationReport.report_id, ValidationReport.validated_at)
            .where(
                ValidationReport.project_id == project_id,
                ValidationReport.validation_category == "full_book",
            )
            .order_by(ValidationReport.validated_at.desc())
            .limit(1)
        )
        row = latest.first()
        if row is None:
            return {"report_id": None, "items": []}
        report_id = row[0]
        reports = await self.get_report(report_id)
        items = [
            {
                "check_type": r.check_type,
                "result": r.result,
                "problem_desc": r.problem_desc,
                "volume_no": r.volume_no,
                "chapter_no": r.chapter_no,
            }
            for r in reports
        ]
        return {"report_id": report_id, "items": items}