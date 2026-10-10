"""批量提取/改写服务单元测试."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.batch_edit_schema import (
    BatchProgressEvent,
    ExtractRequest,
    ExtractResultDto,
)


def _make_chapter(
    chapter_id: str,
    chapter_no: int,
    content: str,
    title: str = "测试章节",
    project_id: str = "proj-1",
):
    ch = MagicMock()
    ch.chapter_id = chapter_id
    ch.chapter_no = chapter_no
    ch.title = title
    ch.content = content
    ch.word_count = len(content)
    ch.modify_status = "none"
    ch.project_id = project_id
    ch.volume_no = 1
    return ch


def _mock_execute(chapters):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = chapters
    result.scalars.return_value = scalars
    return AsyncMock(return_value=result)


def _long_text(seed: str) -> str:
    return (
        f"{seed}在这片广袤的大陆上，主角踏上了漫长而艰辛的旅途，"
        f"沿途经历了无数风雨与考验，结识了各色人物，逐渐成长为一个"
        f"能够独当一面的强者，他的故事才刚刚拉开序幕。"
    )


@pytest.fixture
def mock_session():
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.in_transaction = MagicMock(return_value=False)
    return session


class TestExtractByCharacter:
    @pytest.mark.asyncio
    async def test_extract_by_character_returns_items(self, mock_session):
        chapters = [
            _make_chapter(
                "c1", 1,
                "林动走在远古森林深处，周围古木参天藤蔓缠绕，他小心翼翼地"
                "前行，感受到天地间元气的波动，这股气息强大而陌生。",
            ),
            _make_chapter(
                "c2", 3,
                "林动终于抵达山脚下，仰望巍峨的主峰，心中涌起无限感慨"
                "与豪情壮志，决心攀登顶峰一探究竟。",
            ),
        ]
        mock_session.execute = _mock_execute(chapters)
        ai_json = json.dumps(
            {
                "results": [
                    {
                        "chapter_no": 1,
                        "excerpt": "林动走在远古森林深处，感受到天地间元气的波动。",
                    },
                    {
                        "chapter_no": 3,
                        "excerpt": "林动终于抵达山脚下，仰望巍峨的主峰。",
                    },
                ]
            },
            ensure_ascii=False,
        )
        with patch(
            "src.services.batch_edit_service.get_gateway"
        ) as mock_gw, patch(
            "src.services.batch_edit_service.release_write_lock",
            new_callable=AsyncMock,
        ):
            gw = MagicMock()
            gw.call = AsyncMock(return_value={"content": ai_json})
            mock_gw.return_value = gw
            from src.services.batch_edit_service import BatchEditService

            service = BatchEditService(mock_session)
            result = await service.extract_by_character("proj-1", "林动")

        assert result.dimension == "角色"
        assert result.target_name == "林动"
        assert len(result.items) == 2
        assert result.items[0].chapter_no == 1
        assert "林动" in result.items[0].excerpt
        assert result.items[1].chapter_no == 3
        call_kwargs = gw.call.call_args.kwargs
        assert call_kwargs["module"] == "analysis"
        assert call_kwargs["scene"] == "extract"
        assert call_kwargs["params"]["dimension"] == "角色"
        assert call_kwargs["params"]["target_name"] == "林动"

    @pytest.mark.asyncio
    async def test_extract_no_match_returns_empty(self, mock_session):
        mock_session.execute = _mock_execute([])
        with patch(
            "src.services.batch_edit_service.get_gateway"
        ) as mock_gw, patch(
            "src.services.batch_edit_service.release_write_lock",
            new_callable=AsyncMock,
        ):
            gw = MagicMock()
            gw.call = AsyncMock()
            mock_gw.return_value = gw
            from src.services.batch_edit_service import BatchEditService

            service = BatchEditService(mock_session)
            result = await service.extract_by_character("proj-1", "不存在角色")

        assert result.dimension == "角色"
        assert result.target_name == "不存在角色"
        assert result.items == []
        gw.call.assert_not_awaited()


class TestExtractByPlace:
    @pytest.mark.asyncio
    async def test_extract_by_place_returns_items(self, mock_session):
        chapters = [
            _make_chapter(
                "c1", 2,
                "青云山脉绵延千里，云雾缭绕间隐约可见飞瀑流泉，山间灵气充沛"
                "乃是修行者梦寐以求的洞天福地。",
            ),
        ]
        mock_session.execute = _mock_execute(chapters)
        ai_json = json.dumps(
            {
                "results": [
                    {
                        "chapter_no": 2,
                        "excerpt": "青云山脉绵延千里，云雾缭绕间隐约可见飞瀑流泉。",
                    },
                ]
            },
            ensure_ascii=False,
        )
        with patch(
            "src.services.batch_edit_service.get_gateway"
        ) as mock_gw, patch(
            "src.services.batch_edit_service.release_write_lock",
            new_callable=AsyncMock,
        ):
            gw = MagicMock()
            gw.call = AsyncMock(return_value={"content": ai_json})
            mock_gw.return_value = gw
            from src.services.batch_edit_service import BatchEditService

            service = BatchEditService(mock_session)
            result = await service.extract_by_place("proj-1", "青云山脉")

        assert result.dimension == "地点"
        assert result.target_name == "青云山脉"
        assert len(result.items) == 1
        assert result.items[0].chapter_no == 2
        assert "青云山脉" in result.items[0].excerpt

    @pytest.mark.asyncio
    async def test_extract_place_no_match_returns_empty(self, mock_session):
        mock_session.execute = _mock_execute([])
        with patch(
            "src.services.batch_edit_service.get_gateway"
        ) as mock_gw, patch(
            "src.services.batch_edit_service.release_write_lock",
            new_callable=AsyncMock,
        ):
            gw = MagicMock()
            gw.call = AsyncMock()
            mock_gw.return_value = gw
            from src.services.batch_edit_service import BatchEditService

            service = BatchEditService(mock_session)
            result = await service.extract_by_place("proj-1", "未知地点")

        assert result.items == []
        gw.call.assert_not_awaited()


class TestBatchRewrite:
    @pytest.mark.asyncio
    async def test_batch_rewrite_batches_of_twenty(self, mock_session):
        chapters = [
            _make_chapter(f"c{i}", i, _long_text(f"第{i}章原文")) for i in range(1, 26)
        ]
        mock_session.execute = _mock_execute(chapters)
        rewritten = _long_text("改写后的完整章节正文内容")
        with patch(
            "src.services.batch_edit_service.get_gateway"
        ) as mock_gw, patch(
            "src.services.batch_edit_service.release_write_lock",
            new_callable=AsyncMock,
        ):
            gw = MagicMock()
            gw.call = AsyncMock(return_value={"content": rewritten})
            mock_gw.return_value = gw
            from src.services.batch_edit_service import BatchEditService

            service = BatchEditService(mock_session)
            events = [
                e async for e in service.batch_rewrite(
                    [f"c{i}" for i in range(1, 26)], "将语气改为更紧凑"
                )
            ]

        assert mock_session.add.call_count == 2
        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1
        assert "成功25章" in done_events[0].message
        assert "失败0章" in done_events[0].message
        chapter_events = [e for e in events if e.type == "chapter"]
        assert len(chapter_events) == 25
        assert all(e.content == rewritten for e in chapter_events)

    @pytest.mark.asyncio
    async def test_batch_rewrite_partial_failure_continues(self, mock_session):
        chapters = [
            _make_chapter("c1", 1, _long_text("第一章原文内容")),
            _make_chapter("c2", 2, _long_text("第二章原文内容")),
            _make_chapter("c3", 3, _long_text("第三章原文内容")),
        ]
        mock_session.execute = _mock_execute(chapters)
        good = _long_text("改写后的合格正文内容")
        with patch(
            "src.services.batch_edit_service.get_gateway"
        ) as mock_gw, patch(
            "src.services.batch_edit_service.release_write_lock",
            new_callable=AsyncMock,
        ):
            gw = MagicMock()
            gw.call = AsyncMock(
                side_effect=[
                    {"content": good},
                    RuntimeError("AI调用超时失败"),
                    {"content": good},
                ]
            )
            mock_gw.return_value = gw
            from src.services.batch_edit_service import BatchEditService

            service = BatchEditService(mock_session)
            events = [
                e async for e in service.batch_rewrite(
                    ["c1", "c2", "c3"], "统一战斗描写风格"
                )
            ]

        failed_events = [e for e in events if e.type == "failed"]
        assert len(failed_events) == 1
        assert failed_events[0].chapter_no == 2
        chapter_events = [e for e in events if e.type == "chapter"]
        assert len(chapter_events) == 2
        assert {e.chapter_no for e in chapter_events} == {1, 3}
        summary_events = [e for e in events if e.type == "summary"]
        assert len(summary_events) == 1
        assert "2" in summary_events[0].message
        done_events = [e for e in events if e.type == "done"]
        assert "成功2章" in done_events[0].message
        assert "失败1章" in done_events[0].message

    @pytest.mark.asyncio
    async def test_batch_rewrite_empty_ids_returns_error(self, mock_session):
        with patch(
            "src.services.batch_edit_service.get_gateway"
        ) as mock_gw, patch(
            "src.services.batch_edit_service.release_write_lock",
            new_callable=AsyncMock,
        ):
            mock_gw.return_value = MagicMock()
            from src.services.batch_edit_service import BatchEditService

            service = BatchEditService(mock_session)
            events = [e async for e in service.batch_rewrite([], "指令")]

        assert len(events) == 1
        assert events[0].type == "error"


class TestBatchExpand:
    @pytest.mark.asyncio
    async def test_batch_expand_success(self, mock_session):
        chapters = [
            _make_chapter("c1", 1, _long_text("待扩写的原始正文")),
        ]
        mock_session.execute = _mock_execute(chapters)
        expanded = _long_text("扩写后更加丰满详尽的正文内容")
        with patch(
            "src.services.batch_edit_service.get_gateway"
        ) as mock_gw, patch(
            "src.services.batch_edit_service.release_write_lock",
            new_callable=AsyncMock,
        ):
            gw = MagicMock()
            gw.call = AsyncMock(return_value={"content": expanded})
            mock_gw.return_value = gw
            from src.services.batch_edit_service import BatchEditService

            service = BatchEditService(mock_session)
            events = [
                e async for e in service.batch_expand(["c1"], "增加环境描写与心理活动")
            ]

        call_kwargs = gw.call.call_args.kwargs
        assert call_kwargs["params"]["mode"] == "扩写"
        chapter_events = [e for e in events if e.type == "chapter"]
        assert len(chapter_events) == 1
        assert chapter_events[0].content == expanded
        done_events = [e for e in events if e.type == "done"]
        assert "批量扩写完成" in done_events[0].message


class TestSchemaRegression:
    def test_extract_request_valid(self):
        req = ExtractRequest(
            project_id="proj-1", dimension="角色", target_name="林动"
        )
        assert req.dimension == "角色"
        assert req.target_name == "林动"

    def test_extract_result_dto_defaults(self):
        dto = ExtractResultDto(dimension="地点", target_name="青云山脉")
        assert dto.items == []

    def test_batch_progress_event_defaults(self):
        evt = BatchProgressEvent(type="start")
        assert evt.chapter_no is None
        assert evt.content is None
        assert evt.message is None
        assert evt.progress is None

    def test_batch_progress_event_full(self):
        evt = BatchProgressEvent(
            type="chapter",
            chapter_no=5,
            content="一段足够长的改写后正文内容用于回归验证",
            message=None,
            progress=50,
        )
        assert evt.chapter_no == 5
        assert evt.progress == 50