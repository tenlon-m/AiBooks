"""迭代生成服务单元测试."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.schemas.iteration_schema import (
    IterationDto,
    IterationProgressEvent,
    IterationStartRequest,
)
from src.db.models import Chapter, ChapterVersion, IterationRecord


ORIGINAL_CONTENT = "原始正文内容用于测试迭代生成服务的输入数据" * 2
LONG_CONTENT = "这是一段足够长的迭代输出正文内容，用于测试迭代生成服务的渐进改进逻辑，确保内容长度超过五十字的最低要求，包含情节细节与人物刻画。"
SHORT_CONTENT = "太短"
C1 = "第一轮迭代输出内容，这是一段足够长的正文，用于验证渐进改进逻辑，确保超过五十字的最低要求标准，包含丰富的情节细节。"
C2 = "第二轮迭代输出内容，在第一轮基础上继续改进，这是一段足够长的正文，确保超过五十字的最低要求标准，包含更丰富的细节。"
C3 = "第三轮迭代输出内容，在前两轮基础上最终打磨，这是一段足够长的正文，确保超过五十字的最低要求标准，完成度更高。"


def _make_chapter(chapter_id: str = "ch-1", content: str = ORIGINAL_CONTENT):
    ch = MagicMock()
    ch.chapter_id = chapter_id
    ch.content = content
    ch.word_count = len(content)
    ch.last_modified_at = None
    return ch


def _make_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.in_transaction = MagicMock(return_value=False)
    get_map: dict = {}

    async def _get(model, oid):
        return get_map.get((model, oid))

    session.get = AsyncMock(side_effect=_get)
    session._get_map = get_map
    return session


def _mock_scalars(items=None, first=None):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items or []
    scalars.first.return_value = first
    result.scalars.return_value = scalars
    return result


def _make_config(timeout: int = 90, min_len: int = 50):
    cfg = MagicMock()
    cfg.iteration_timeout_seconds = timeout
    cfg.min_ai_content_length = min_len
    return cfg


def _make_gateway(contents: list[str]):
    gw = MagicMock()
    calls: list[dict] = []

    async def _call(**kwargs):
        calls.append(kwargs)
        idx = len(calls) - 1
        c = contents[idx] if idx < len(contents) else contents[-1]
        return {
            "content": c,
            "source_id": "s1",
            "source_name": "test",
            "model_name": "m1",
        }

    gw.call = AsyncMock(side_effect=_call)
    gw._calls = calls
    return gw


def _patch_env(gw, cfg):
    return (
        patch("src.services.iteration_service.get_gateway", return_value=gw),
        patch("src.services.iteration_service.get_config", return_value=cfg),
    )


class TestIterationSchema:
    def test_start_request_default_unit(self):
        req = IterationStartRequest(
            project_id="p1", target_id="ch1", total_rounds=3
        )
        assert req.iteration_unit == "章"

    def test_start_request_custom_unit(self):
        for unit in ("卷", "阶段", "章"):
            req = IterationStartRequest(
                project_id="p1",
                iteration_unit=unit,
                target_id="ch1",
                total_rounds=2,
            )
            assert req.iteration_unit == unit

    def test_progress_event_defaults(self):
        ev = IterationProgressEvent(type="round_start")
        assert ev.round_no is None
        assert ev.content is None
        assert ev.message is None
        assert ev.progress is None
        assert ev.iteration_id is None

    def test_dto(self):
        from datetime import datetime

        dto = IterationDto(
            iteration_id="i1",
            project_id="p1",
            iteration_unit="章",
            target_id="ch1",
            round_no=2,
            total_rounds=3,
            iteration_status="完成",
            created_at=datetime.now(),
        )
        assert dto.round_no == 2


class TestIterationService:
    @pytest.mark.asyncio
    async def test_target_not_found(self):
        session = _make_session()
        gw = _make_gateway([LONG_CONTENT])
        cfg = _make_config()
        p1, p2 = _patch_env(gw, cfg)
        with p1, p2:
            from src.services.iteration_service import IterationService

            service = IterationService(session)
            with pytest.raises(ValueError, match="目标章节不存在"):
                async for _ in service.start_iteration("p-1", "章", "no-ch", 2):
                    pass

    @pytest.mark.asyncio
    async def test_total_rounds_invalid(self):
        session = _make_session()
        chapter = _make_chapter()
        session._get_map[(Chapter, "ch-1")] = chapter
        gw = _make_gateway([LONG_CONTENT])
        cfg = _make_config()
        p1, p2 = _patch_env(gw, cfg)
        with p1, p2:
            from src.services.iteration_service import IterationService

            service = IterationService(session)
            with pytest.raises(ValueError, match="总轮数必须大于0"):
                async for _ in service.start_iteration("p-1", "章", "ch-1", 0):
                    pass

    @pytest.mark.asyncio
    async def test_iteration_unit_selection(self):
        for unit in ("卷", "阶段", "章"):
            session = _make_session()
            chapter = _make_chapter()
            session._get_map[(Chapter, "ch-1")] = chapter
            gw = _make_gateway([LONG_CONTENT])
            cfg = _make_config()
            p1, p2 = _patch_env(gw, cfg)
            with p1, p2:
                from src.services.iteration_service import IterationService

                service = IterationService(session)
                events = [
                    e
                    async for e in service.start_iteration(
                        "p-1", unit, "ch-1", 1
                    )
                ]
                assert any(e.type == "completed" for e in events)
                assert gw.call.call_count >= 1

    @pytest.mark.asyncio
    async def test_progressive_improvement(self):
        session = _make_session()
        chapter = _make_chapter()
        session._get_map[(Chapter, "ch-1")] = chapter
        gw = _make_gateway([C1, C2])
        cfg = _make_config()
        p1, p2 = _patch_env(gw, cfg)
        with p1, p2:
            from src.services.iteration_service import IterationService

            service = IterationService(session)
            events = [
                e
                async for e in service.start_iteration("p-1", "章", "ch-1", 2)
            ]
            assert len(gw._calls) == 2
            assert gw._calls[0]["params"]["input_content"] == ORIGINAL_CONTENT
            assert gw._calls[0]["params"]["round_no"] == 1
            assert gw._calls[1]["params"]["input_content"] == C1
            assert gw._calls[1]["params"]["round_no"] == 2
            round_done_events = [e for e in events if e.type == "round_done"]
            assert len(round_done_events) == 2
            assert round_done_events[0].content == C1
            assert round_done_events[1].content == C2
            assert any(e.type == "completed" for e in events)

    @pytest.mark.asyncio
    async def test_pause_and_resume(self):
        session = _make_session()
        chapter = _make_chapter()
        session._get_map[(Chapter, "ch-1")] = chapter
        gw = _make_gateway([C1, C2, C3])
        cfg = _make_config()
        p1, p2 = _patch_env(gw, cfg)
        with p1, p2:
            from src.services.iteration_service import IterationService

            service = IterationService(session)
            events = []
            async for event in service.start_iteration("p-1", "章", "ch-1", 3):
                events.append(event)
                if event.type == "round_done" and event.round_no == 1:
                    service._paused = True

            assert any(e.type == "paused" for e in events)
            assert service._iteration_id is not None

            iteration_id = service._iteration_id
            mock_record = MagicMock()
            mock_record.iteration_id = iteration_id
            mock_record.project_id = "p-1"
            mock_record.target_id = "ch-1"
            mock_record.total_rounds = 3
            mock_record.round_no = 1
            mock_record.iteration_status = "已暂停"
            mock_record.output_version_id = "v-out-1"
            session._get_map[(IterationRecord, iteration_id)] = mock_record

            mock_version = MagicMock()
            mock_version.version_id = "v-out-1"
            mock_version.content = C1
            session._get_map[(ChapterVersion, "v-out-1")] = mock_version

            resume_events = [
                e async for e in service.resume_iteration(iteration_id)
            ]
            resume_done = [
                e for e in resume_events if e.type == "round_done"
            ]
            assert len(resume_done) == 2
            assert resume_done[0].round_no == 2
            assert resume_done[1].round_no == 3
            assert any(e.type == "completed" for e in resume_events)

    @pytest.mark.asyncio
    async def test_adopt_iteration(self):
        session = _make_session()
        chapter = _make_chapter()
        session._get_map[(Chapter, "ch-1")] = chapter
        gw = _make_gateway([C1, C2])
        cfg = _make_config()
        p1, p2 = _patch_env(gw, cfg)
        with p1, p2:
            from src.services.iteration_service import IterationService

            service = IterationService(session)
            events = [
                e
                async for e in service.start_iteration("p-1", "章", "ch-1", 2)
            ]
            assert any(e.type == "completed" for e in events)

            iteration_id = service._iteration_id
            mock_record = MagicMock()
            mock_record.iteration_id = iteration_id
            mock_record.target_id = "ch-1"
            mock_record.iteration_status = "完成"
            session._get_map[(IterationRecord, iteration_id)] = mock_record

            mock_version = MagicMock()
            mock_version.version_id = "v-round-1"
            mock_version.content = C1
            mock_version.word_count = len(C1)
            session.execute = AsyncMock(
                return_value=_mock_scalars(first=mock_version)
            )

            result = await service.adopt_iteration(iteration_id, 1)
            assert result["adopted"] is True
            assert result["round_no"] == 1
            assert result["word_count"] == len(C1)
            assert chapter.content == C1
            assert chapter.word_count == len(C1)

    @pytest.mark.asyncio
    async def test_content_too_short_retry(self):
        session = _make_session()
        chapter = _make_chapter()
        session._get_map[(Chapter, "ch-1")] = chapter
        gw = _make_gateway([SHORT_CONTENT, LONG_CONTENT])
        cfg = _make_config()
        p1, p2 = _patch_env(gw, cfg)
        with p1, p2:
            from src.services.iteration_service import IterationService

            service = IterationService(session)
            events = [
                e
                async for e in service.start_iteration("p-1", "章", "ch-1", 1)
            ]
            assert gw.call.call_count == 2
            round_done = [e for e in events if e.type == "round_done"]
            assert len(round_done) == 1
            assert round_done[0].content == LONG_CONTENT
            assert any(e.type == "completed" for e in events)

    @pytest.mark.asyncio
    async def test_content_too_short_retry_still_fails(self):
        session = _make_session()
        chapter = _make_chapter()
        session._get_map[(Chapter, "ch-1")] = chapter
        gw = _make_gateway([SHORT_CONTENT, SHORT_CONTENT])
        cfg = _make_config()
        p1, p2 = _patch_env(gw, cfg)
        with p1, p2:
            from src.services.iteration_service import IterationService

            service = IterationService(session)
            events = [
                e
                async for e in service.start_iteration("p-1", "章", "ch-1", 1)
            ]
            assert gw.call.call_count == 2
            assert any(e.type == "error" for e in events)
            assert not any(e.type == "completed" for e in events)

    @pytest.mark.asyncio
    async def test_sufficient_content_no_retry(self):
        session = _make_session()
        chapter = _make_chapter()
        session._get_map[(Chapter, "ch-1")] = chapter
        gw = _make_gateway([LONG_CONTENT])
        cfg = _make_config()
        p1, p2 = _patch_env(gw, cfg)
        with p1, p2:
            from src.services.iteration_service import IterationService

            service = IterationService(session)
            events = [
                e
                async for e in service.start_iteration("p-1", "章", "ch-1", 1)
            ]
            assert gw.call.call_count == 1
            round_done = [e for e in events if e.type == "round_done"]
            assert round_done[0].content == LONG_CONTENT
            assert any(e.type == "completed" for e in events)

    @pytest.mark.asyncio
    async def test_list_iterations(self):
        session = _make_session()
        from datetime import datetime

        rec1 = MagicMock()
        rec1.iteration_id = "i1"
        rec1.project_id = "p-1"
        rec1.iteration_unit = "章"
        rec1.target_id = "ch-1"
        rec1.round_no = 2
        rec1.total_rounds = 3
        rec1.iteration_status = "完成"
        rec1.created_at = datetime.now()
        rec2 = MagicMock()
        rec2.iteration_id = "i2"
        rec2.project_id = "p-1"
        rec2.iteration_unit = "卷"
        rec2.target_id = "ch-1"
        rec2.round_no = 1
        rec2.total_rounds = 2
        rec2.iteration_status = "进行中"
        rec2.created_at = datetime.now()
        session.execute = AsyncMock(
            return_value=_mock_scalars(items=[rec1, rec2])
        )
        gw = _make_gateway([LONG_CONTENT])
        cfg = _make_config()
        p1, p2 = _patch_env(gw, cfg)
        with p1, p2:
            from src.services.iteration_service import IterationService

            service = IterationService(session)
            result = await service.list_iterations("ch-1")
            assert len(result) == 2
            assert all(isinstance(dto, IterationDto) for dto in result)
            assert result[0].iteration_id == "i1"
            assert result[1].iteration_id == "i2"

    @pytest.mark.asyncio
    async def test_adopt_not_found(self):
        session = _make_session()
        gw = _make_gateway([LONG_CONTENT])
        cfg = _make_config()
        p1, p2 = _patch_env(gw, cfg)
        with p1, p2:
            from src.services.iteration_service import IterationService

            service = IterationService(session)
            with pytest.raises(ValueError, match="迭代记录不存在"):
                await service.adopt_iteration("no-id", 1)

    @pytest.mark.asyncio
    async def test_pause_nonexistent(self):
        session = _make_session()
        gw = _make_gateway([LONG_CONTENT])
        cfg = _make_config()
        p1, p2 = _patch_env(gw, cfg)
        with p1, p2:
            from src.services.iteration_service import IterationService

            service = IterationService(session)
            with pytest.raises(ValueError, match="迭代记录不存在"):
                await service.pause_iteration("no-id")

    @pytest.mark.asyncio
    async def test_improvement_focus_progression(self):
        session = _make_session()
        chapter = _make_chapter()
        session._get_map[(Chapter, "ch-1")] = chapter
        gw = _make_gateway([C1, C2, C3])
        cfg = _make_config()
        p1, p2 = _patch_env(gw, cfg)
        with p1, p2:
            from src.services.iteration_service import IterationService

            service = IterationService(session)
            async for _ in service.start_iteration("p-1", "章", "ch-1", 3):
                pass
            focuses = [c["params"]["improvement_focus"] for c in gw._calls]
            assert len(focuses) == 3
            assert focuses[0] != focuses[1]
            assert focuses[1] != focuses[2]