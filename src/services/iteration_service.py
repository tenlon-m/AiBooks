"""迭代生成服务 - 多轮渐进改进、断点续传、版本快照."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import AiGateway, get_gateway
from src.api.schemas.iteration_schema import IterationDto, IterationProgressEvent
from src.config.settings import get_config
from src.db.models import Chapter, ChapterVersion, IterationRecord
from src.utils.logger import get_logger


class IterationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway: AiGateway = get_gateway()
        self.config = get_config()
        self._running = False
        self._paused = False
        self._iteration_id: str | None = None

    async def _load_original_content(self, target_id: str) -> str:
        chapter = await self.session.get(Chapter, target_id)
        if not chapter:
            raise ValueError(f"目标章节不存在: {target_id}")
        if not chapter.content:
            raise ValueError(f"目标章节无正文内容: {target_id}")
        return chapter.content

    async def _create_version_snapshot(
        self, chapter_id: str, content: str, round_label: str
    ) -> ChapterVersion:
        version = ChapterVersion(
            version_id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            version_type="iteration",
            name=round_label,
            content=content,
            word_count=len(content),
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(version)
        await self.session.flush()
        return version

    def _improvement_focus(self, round_no: int, total_rounds: int) -> str:
        if round_no == 1:
            return "在原始正文基础上，丰富情节细节，增强人物刻画，使叙事更加生动立体"
        if round_no >= total_rounds:
            return "在上一轮基础上，打磨语言节奏，优化段落衔接，提升整体完成度与感染力"
        return "在上一轮基础上，深化冲突张力，补充细节描写，使情节推进更自然紧凑"

    async def _call_iterate(
        self, project_id: str, input_content: str, round_no: int, total_rounds: int
    ) -> str:
        params = {
            "input_content": input_content,
            "round_no": round_no,
            "total_rounds": total_rounds,
            "improvement_focus": self._improvement_focus(round_no, total_rounds),
        }
        timeout = self.config.iteration_timeout_seconds
        result = await self.gateway.call(
            module="writing",
            scene="iterate",
            params=params,
            project_id=project_id,
            max_tokens=8192,
            timeout_seconds=timeout,
        )
        return result.get("content", "")

    async def _run_rounds(
        self,
        record: IterationRecord,
        project_id: str,
        target_id: str,
        total_rounds: int,
        start_round: int,
        input_content: str,
        is_resuming: bool = False,
    ) -> AsyncGenerator[IterationProgressEvent, None]:
        for round_no in range(start_round, total_rounds + 1):
            if self._paused:
                record.iteration_status = "已暂停"
                await self.session.flush()
                await self.session.commit()
                yield IterationProgressEvent(
                    type="paused",
                    round_no=round_no,
                    message="迭代已暂停",
                    progress=int((round_no - 1) / total_rounds * 100),
                    iteration_id=record.iteration_id,
                )
                return

            yield IterationProgressEvent(
                type="round_start",
                round_no=round_no,
                message=f"{'续传' if is_resuming else '开始'}第{round_no}轮迭代",
                progress=int((round_no - 1) / total_rounds * 100),
                iteration_id=record.iteration_id,
            )

            try:
                content = await self._call_iterate(
                    project_id, input_content, round_no, total_rounds
                )
            except asyncio.TimeoutError:
                record.iteration_status = "失败"
                await self.session.flush()
                await self.session.commit()
                yield IterationProgressEvent(
                    type="error",
                    round_no=round_no,
                    message=f"第{round_no}轮迭代超时",
                    progress=int((round_no - 1) / total_rounds * 100),
                    iteration_id=record.iteration_id,
                )
                return
            except Exception as e:
                record.iteration_status = "失败"
                await self.session.flush()
                await self.session.commit()
                yield IterationProgressEvent(
                    type="error",
                    round_no=round_no,
                    message=f"第{round_no}轮迭代失败: {e}",
                    progress=int((round_no - 1) / total_rounds * 100),
                    iteration_id=record.iteration_id,
                )
                return

            min_length = self.config.min_ai_content_length
            if len(content) < min_length:
                self.logger.warning(
                    f"第{round_no}轮内容过短({len(content)}字)，重试一次"
                )
                try:
                    retry_content = await self._call_iterate(
                        project_id, input_content, round_no, total_rounds
                    )
                    if len(retry_content) > len(content):
                        content = retry_content
                except Exception as e:
                    self.logger.warning(f"第{round_no}轮重试失败: {e}")
                if len(content) < min_length:
                    record.iteration_status = "失败"
                    await self.session.flush()
                    await self.session.commit()
                    yield IterationProgressEvent(
                        type="error",
                        round_no=round_no,
                        message=f"第{round_no}轮内容不足{min_length}字",
                        progress=int((round_no - 1) / total_rounds * 100),
                        iteration_id=record.iteration_id,
                    )
                    return

            output_version = await self._create_version_snapshot(
                target_id, content, f"迭代第{round_no}轮输出"
            )

            record.round_no = round_no
            record.output_version_id = output_version.version_id
            await self.session.flush()
            await self.session.commit()

            yield IterationProgressEvent(
                type="round_done",
                round_no=round_no,
                content=content,
                message=f"第{round_no}轮迭代完成",
                progress=int(round_no / total_rounds * 100),
                iteration_id=record.iteration_id,
            )

            input_content = content

        record.iteration_status = "完成"
        await self.session.flush()
        await self.session.commit()
        self._running = False
        yield IterationProgressEvent(
            type="completed",
            round_no=total_rounds,
            message="迭代全部完成",
            progress=100,
            iteration_id=record.iteration_id,
        )

    async def start_iteration(
        self,
        project_id: str,
        target_unit: str,
        target_id: str,
        total_rounds: int,
    ) -> AsyncGenerator[IterationProgressEvent, None]:
        if total_rounds <= 0:
            raise ValueError("总轮数必须大于0")
        original_content = await self._load_original_content(target_id)

        iteration_id = str(uuid.uuid4())
        self._iteration_id = iteration_id
        self._running = True
        self._paused = False

        input_version = await self._create_version_snapshot(
            target_id, original_content, "迭代原始输入"
        )

        record = IterationRecord(
            iteration_id=iteration_id,
            project_id=project_id,
            iteration_unit=target_unit,
            target_id=target_id,
            round_no=0,
            total_rounds=total_rounds,
            input_version_id=input_version.version_id,
            output_version_id=input_version.version_id,
            iteration_status="进行中",
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(record)
        await self.session.flush()
        await self.session.commit()

        input_content = original_content
        async for event in self._run_rounds(
            record, project_id, target_id, total_rounds, 1, input_content
        ):
            yield event

    async def pause_iteration(self, iteration_id: str) -> bool:
        record = await self.session.get(IterationRecord, iteration_id)
        if not record:
            raise ValueError(f"迭代记录不存在: {iteration_id}")
        record.iteration_status = "已暂停"
        await self.session.flush()
        await self.session.commit()
        self._paused = True
        return True

    async def resume_iteration(
        self, iteration_id: str
    ) -> AsyncGenerator[IterationProgressEvent, None]:
        record = await self.session.get(IterationRecord, iteration_id)
        if not record:
            raise ValueError(f"迭代记录不存在: {iteration_id}")
        if record.iteration_status not in ("已暂停", "进行中"):
            raise ValueError(f"迭代状态不允许续传: {record.iteration_status}")

        project_id = record.project_id
        target_id = record.target_id
        total_rounds = record.total_rounds
        start_round = record.round_no + 1

        if start_round > total_rounds:
            yield IterationProgressEvent(
                type="completed",
                round_no=total_rounds,
                message="迭代已完成，无需续传",
                progress=100,
                iteration_id=iteration_id,
            )
            return

        output_version = await self.session.get(
            ChapterVersion, record.output_version_id
        )
        input_content = output_version.content if output_version else ""

        self._iteration_id = iteration_id
        self._running = True
        self._paused = False
        record.iteration_status = "进行中"
        await self.session.flush()
        await self.session.commit()

        async for event in self._run_rounds(
            record,
            project_id,
            target_id,
            total_rounds,
            start_round,
            input_content,
            is_resuming=True,
        ):
            yield event

    async def list_iterations(self, target_id: str) -> list[IterationDto]:
        result = await self.session.execute(
            select(IterationRecord)
            .where(IterationRecord.target_id == target_id)
            .order_by(IterationRecord.created_at.desc())
        )
        records = list(result.scalars().all())
        return [
            IterationDto(
                iteration_id=r.iteration_id,
                project_id=r.project_id,
                iteration_unit=r.iteration_unit,
                target_id=r.target_id,
                round_no=r.round_no,
                total_rounds=r.total_rounds,
                iteration_status=r.iteration_status,
                created_at=r.created_at,
            )
            for r in records
        ]

    async def adopt_iteration(self, iteration_id: str, round_no: int) -> dict:
        record = await self.session.get(IterationRecord, iteration_id)
        if not record:
            raise ValueError(f"迭代记录不存在: {iteration_id}")
        version_result = await self.session.execute(
            select(ChapterVersion)
            .where(
                ChapterVersion.chapter_id == record.target_id,
                ChapterVersion.name == f"迭代第{round_no}轮输出",
                ChapterVersion.version_type == "iteration",
            )
            .order_by(ChapterVersion.created_at.desc())
        )
        version = version_result.scalars().first()
        if not version:
            raise ValueError(f"未找到第{round_no}轮迭代输出版本")
        chapter = await self.session.get(Chapter, record.target_id)
        if not chapter:
            raise ValueError(f"目标章节不存在: {record.target_id}")
        chapter.content = version.content
        chapter.word_count = version.word_count
        chapter.last_modified_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.commit()
        return {
            "iteration_id": iteration_id,
            "round_no": round_no,
            "version_id": version.version_id,
            "word_count": version.word_count,
            "adopted": True,
        }