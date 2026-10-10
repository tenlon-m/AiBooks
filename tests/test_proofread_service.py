"""AB稿/ABC稿多AI接力纠错服务单元测试."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.schemas.proofread_schema import (
    EvaluateResultDto,
    ProofreadABRequest,
    ProofreadABCRequest,
    ProofreadResultDto,
)


LONG_CONTENT = (
    "这是一段足够长的测试正文内容，用于确保超过五十字的最低阈值要求，"
    "从而不会触发重试逻辑，保证接力纠错流程能够正常进行下去。"
)
SHORT_CONTENT = "短内容"


def _make_chapter(chapter_id: str = "ch-1", content: str | None = None) -> MagicMock:
    chapter = MagicMock()
    chapter.chapter_id = chapter_id
    chapter.project_id = "proj-1"
    chapter.content = content
    return chapter


def _make_session(chapter: MagicMock | None = None) -> MagicMock:
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.in_transaction = MagicMock(return_value=False)
    session.get = AsyncMock(return_value=chapter)
    return session


def _make_gateway_result(content: str) -> dict:
    return {
        "content": content,
        "source_id": "src-1",
        "source_name": "测试源",
        "model_name": "test-model",
    }


def _build_service(session: MagicMock) -> "ProofreadService":
    from src.services.proofread_service import ProofreadService
    return ProofreadService(session)


def _patch_gateway(mock_gw: MagicMock):
    return patch("src.services.proofread_service.get_gateway", return_value=mock_gw)


class TestProofreadSchema:
    def test_ab_request(self):
        req = ProofreadABRequest(
            chapter_id="ch-1", source_a="a", source_b="b",
        )
        assert req.chapter_id == "ch-1"
        assert req.source_a == "a"
        assert req.source_b == "b"

    def test_abc_request(self):
        req = ProofreadABCRequest(
            chapter_id="ch-1",
            source_a="a", source_b="b", source_c="c", source_eval="e",
        )
        assert req.source_c == "c"
        assert req.source_eval == "e"

    def test_evaluate_result_dto(self):
        dto = EvaluateResultDto(
            draft_id="d-1",
            score=88.0,
            dimensions={"情节连贯性": 90},
            summary="良好",
        )
        assert dto.score == 88.0
        assert dto.dimensions["情节连贯性"] == 90


class TestProofreadAB:
    @pytest.mark.asyncio
    async def test_ab_stage_order(self):
        chapter = _make_chapter(content="原文内容")
        session = _make_session(chapter)
        mock_gw = MagicMock()
        mock_gw.call = AsyncMock(
            side_effect=[_make_gateway_result(LONG_CONTENT), _make_gateway_result(LONG_CONTENT + "B")]
        )
        with _patch_gateway(mock_gw):
            service = _build_service(session)
            result = await service.proofread_ab("ch-1", "src-a", "src-b")
        assert isinstance(result, ProofreadResultDto)
        assert result.chapter_id == "ch-1"
        assert len(result.drafts) == 2
        assert result.drafts[0].draft_stage == "A"
        assert result.drafts[1].draft_stage == "B"
        stages = [c.kwargs["params"]["proofread_stage"] for c in mock_gw.call.call_args_list]
        assert stages == ["A", "B"]

    @pytest.mark.asyncio
    async def test_ab_different_ai_sources(self):
        chapter = _make_chapter(content="原文内容")
        session = _make_session(chapter)
        mock_gw = MagicMock()
        mock_gw.call = AsyncMock(
            side_effect=[_make_gateway_result(LONG_CONTENT), _make_gateway_result(LONG_CONTENT)]
        )
        with _patch_gateway(mock_gw):
            service = _build_service(session)
            await service.proofread_ab("ch-1", "src-a", "src-b")
        source_ids = [c.kwargs["source_id"] for c in mock_gw.call.call_args_list]
        assert source_ids == ["src-a", "src-b"]

    @pytest.mark.asyncio
    async def test_ab_b_uses_a_output(self):
        chapter = _make_chapter(content="原文内容")
        session = _make_session(chapter)
        mock_gw = MagicMock()
        mock_gw.call = AsyncMock(
            side_effect=[_make_gateway_result(LONG_CONTENT), _make_gateway_result(LONG_CONTENT + "B")]
        )
        with _patch_gateway(mock_gw):
            service = _build_service(session)
            result = await service.proofread_ab("ch-1", "src-a", "src-b")
        b_call = mock_gw.call.call_args_list[1]
        assert b_call.kwargs["params"]["input_content"] == LONG_CONTENT
        assert b_call.kwargs["params"]["previous_draft"] == LONG_CONTENT
        assert result.drafts[0].content == LONG_CONTENT


class TestProofreadABC:
    @pytest.mark.asyncio
    async def test_abc_stage_order_and_evaluate(self):
        chapter = _make_chapter(content="原文内容")
        session = _make_session(chapter)
        eval_draft = MagicMock()
        eval_draft.draft_id = "draft-c"
        eval_draft.content = LONG_CONTENT
        eval_draft.score = None
        session.get = AsyncMock(side_effect=[chapter, eval_draft])
        mock_gw = MagicMock()
        mock_gw.call = AsyncMock(
            side_effect=[
                _make_gateway_result(LONG_CONTENT + "A"),
                _make_gateway_result(LONG_CONTENT + "B"),
                _make_gateway_result(LONG_CONTENT + "C"),
            ]
        )
        mock_gw.call_and_parse = AsyncMock(
            return_value={
                "parsed": {"score": 88, "dimensions": {"情节连贯性": 90}, "summary": "良好"},
                "content": "{}",
            }
        )
        with _patch_gateway(mock_gw):
            service = _build_service(session)
            result = await service.proofread_abc("ch-1", "a", "b", "c", "e")
        assert len(result.drafts) == 3
        stages = [d.draft_stage for d in result.drafts]
        assert stages == ["A", "B", "C"]
        call_stages = [c.kwargs["params"]["proofread_stage"] for c in mock_gw.call.call_args_list]
        assert call_stages == ["A", "B", "C"]
        assert mock_gw.call_and_parse.call_count == 1
        eval_kwargs = mock_gw.call_and_parse.call_args.kwargs
        assert eval_kwargs["module"] == "writing"
        assert eval_kwargs["scene"] == "evaluate"
        assert eval_kwargs["source_id"] == "e"

    @pytest.mark.asyncio
    async def test_abc_different_ai_sources(self):
        chapter = _make_chapter(content="原文内容")
        session = _make_session(chapter)
        eval_draft = MagicMock()
        eval_draft.content = LONG_CONTENT
        eval_draft.score = None
        session.get = AsyncMock(side_effect=[chapter, eval_draft])
        mock_gw = MagicMock()
        mock_gw.call = AsyncMock(
            side_effect=[_make_gateway_result(LONG_CONTENT)] * 3
        )
        mock_gw.call_and_parse = AsyncMock(
            return_value={"parsed": {"score": 80, "dimensions": {}, "summary": ""}, "content": "{}"}
        )
        with _patch_gateway(mock_gw):
            service = _build_service(session)
            await service.proofread_abc("ch-1", "a", "b", "c", "e")
        source_ids = [c.kwargs["source_id"] for c in mock_gw.call.call_args_list]
        assert source_ids == ["a", "b", "c"]


class TestRetryOnShortContent:
    @pytest.mark.asyncio
    async def test_short_content_retries_once(self):
        chapter = _make_chapter(content="原文内容")
        session = _make_session(chapter)
        mock_gw = MagicMock()
        mock_gw.call = AsyncMock(
            side_effect=[
                _make_gateway_result(SHORT_CONTENT),
                _make_gateway_result(LONG_CONTENT),
                _make_gateway_result(LONG_CONTENT),
            ]
        )
        with _patch_gateway(mock_gw):
            service = _build_service(session)
            result = await service.proofread_ab("ch-1", "a", "b")
        assert mock_gw.call.call_count == 3
        assert result.drafts[0].content == LONG_CONTENT


class TestFailureKeepsPreviousDrafts:
    @pytest.mark.asyncio
    async def test_b_failure_keeps_a(self):
        chapter = _make_chapter(content="原文内容")
        session = _make_session(chapter)
        mock_gw = MagicMock()
        mock_gw.call = AsyncMock(
            side_effect=[_make_gateway_result(LONG_CONTENT), RuntimeError("B源不可用")]
        )
        with _patch_gateway(mock_gw):
            service = _build_service(session)
            result = await service.proofread_ab("ch-1", "a", "b")
        assert len(result.drafts) == 1
        assert result.drafts[0].draft_stage == "A"
        assert result.drafts[0].content == LONG_CONTENT

    @pytest.mark.asyncio
    async def test_a_failure_raises(self):
        chapter = _make_chapter(content="原文内容")
        session = _make_session(chapter)
        mock_gw = MagicMock()
        mock_gw.call = AsyncMock(side_effect=RuntimeError("A源不可用"))
        with _patch_gateway(mock_gw):
            service = _build_service(session)
            with pytest.raises(RuntimeError, match="A源不可用"):
                await service.proofread_ab("ch-1", "a", "b")


class TestEvaluate:
    @pytest.mark.asyncio
    async def test_evaluate_returns_score(self):
        draft = MagicMock()
        draft.draft_id = "d-1"
        draft.content = LONG_CONTENT
        draft.score = None
        session = _make_session()
        session.get = AsyncMock(return_value=draft)
        mock_gw = MagicMock()
        mock_gw.call_and_parse = AsyncMock(
            return_value={
                "parsed": {"score": 92, "dimensions": {"文笔流畅度": 95}, "summary": "优秀"},
                "content": "{}",
            }
        )
        with _patch_gateway(mock_gw):
            service = _build_service(session)
            result = await service.evaluate("d-1")
        assert isinstance(result, EvaluateResultDto)
        assert result.score == 92.0
        assert result.dimensions["文笔流畅度"] == 95
        assert result.summary == "优秀"
        assert draft.score == 92.0


class TestAdoptAndList:
    @pytest.mark.asyncio
    async def test_adopt_draft(self):
        draft = MagicMock()
        draft.draft_id = "d-1"
        draft.chapter_id = "ch-1"
        draft.content = LONG_CONTENT
        draft.adopt_status = "待采纳"
        chapter = _make_chapter(content="旧内容")
        session = _make_session()
        session.get = AsyncMock(side_effect=[draft, chapter])
        mock_gw = MagicMock()
        with _patch_gateway(mock_gw):
            service = _build_service(session)
            result = await service.adopt_draft("d-1")
        assert result["adopt_status"] == "已采纳"
        assert chapter.content == LONG_CONTENT
        assert chapter.word_count == len(LONG_CONTENT)
        assert draft.adopt_status == "已采纳"

    @pytest.mark.asyncio
    async def test_list_drafts(self):
        d1 = MagicMock()
        d1.draft_id = "d1"
        d1.chapter_id = "ch-1"
        d1.draft_stage = "A"
        d1.ai_source_id = "a"
        d1.content = LONG_CONTENT
        d1.score = None
        d1.adopt_status = "待采纳"
        d1.created_at = MagicMock()
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [d1]
        session = _make_session()
        session.execute = AsyncMock(return_value=exec_result)
        mock_gw = MagicMock()
        with _patch_gateway(mock_gw):
            service = _build_service(session)
            drafts = await service.list_drafts("ch-1")
        assert len(drafts) == 1
        assert drafts[0].draft_stage == "A"


class TestRegressionWritingUnchanged:
    def test_writing_still_uses_write_chapter_scene(self):
        import inspect

        from src.services.writing_service import WritingService

        source = inspect.getsource(WritingService._generate_chapter)
        assert '"write-chapter"' in source or "'write-chapter'" in source
        assert "proofread" not in source.replace("proofread_mode", "").replace("proofread_sources", "")