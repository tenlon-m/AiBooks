"""故事单元服务单元测试 - 雪花式5级分层大纲."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.schemas.story_unit_schema import (
    StoryUnitDto,
    StoryUnitTreeDto,
    StoryUnitUpdateRequest,
)


def _make_project():
    project = MagicMock()
    project.project_id = "proj-1"
    project.book_title = "测试小说"
    project.volume_count = 3
    project.chapters_per_volume = 10
    project.words_per_chapter = 3000
    return project


def _make_synopsis():
    synopsis = MagicMock()
    synopsis.content = "主角是一个普通人，意外获得上古神功传承，从此踏上修炼之路，经历无数艰难险阻，最终成为一代宗师。"
    return synopsis


def _make_worldview():
    worldview = MagicMock()
    worldview.content = "修仙世界，分为凡人界和修仙界，修仙者按境界划分为练气、筑基、金丹、元婴、化神五个大境界，各大门派林立。"
    return worldview


def _make_character():
    char = MagicMock()
    char.name = "林动"
    char.identity = "主角"
    char.intro = "普通少年，意外获得神功"
    return char


def _make_story_unit(unit_id, project_id, parent_id, level_type, unit_no, name, synopsis, chapter_count, gen_status="已生成", duty=""):
    unit = MagicMock()
    unit.story_unit_id = unit_id
    unit.project_id = project_id
    unit.parent_unit_id = parent_id
    unit.level_type = level_type
    unit.unit_no = unit_no
    unit.unit_name = name
    unit.synopsis = synopsis
    unit.chapter_count = chapter_count
    unit.gen_status = gen_status
    unit.narrative_duty = duty
    unit.cascade_dirty = False
    unit.created_at = None
    return unit


def _mock_execute_result(items):
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=items)
    scalars_mock.first = MagicMock(return_value=items[0] if items else None)
    result.scalars = MagicMock(return_value=scalars_mock)
    return result


class TestStoryUnitSchema:
    def test_story_unit_dto(self):
        dto = StoryUnitDto(
            story_unit_id="u1",
            project_id="p1",
            parent_unit_id=None,
            level_type="volume",
            unit_no=1,
            unit_name="第一卷",
            synopsis="主角开始修炼之路的起始卷",
            chapter_count=30,
            gen_status="已生成",
            narrative_duty="引入主角与世界观",
        )
        assert dto.level_type == "volume"
        assert dto.chapter_count == 30

    def test_tree_dto_empty(self):
        dto = StoryUnitTreeDto(project_id="p1")
        assert dto.units == []

    def test_update_request(self):
        req = StoryUnitUpdateRequest(
            unit_name="新名称",
            synopsis="新的叙事概要内容，足够长的描述用于测试",
            narrative_duty="新的叙事职责描述",
        )
        assert req.unit_name == "新名称"


class TestStoryUnitServiceGenerateVolumeLayer:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_project_not_found(self, mock_session):
        mock_session.get = AsyncMock(return_value=None)
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(mock_session)
            with pytest.raises(ValueError, match="项目不存在"):
                await service.generate_volume_layer("nonexistent")

    @pytest.mark.asyncio
    async def test_synopsis_missing(self, mock_session):
        mock_session.get = AsyncMock(side_effect=[_make_project(), None, None])
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(mock_session)
            with pytest.raises(ValueError, match="请先输入故事梗概"):
                await service.generate_volume_layer("proj-1")

    @pytest.mark.asyncio
    async def test_characters_missing(self, mock_session):
        project = _make_project()
        synopsis = _make_synopsis()
        worldview = _make_worldview()
        mock_session.get = AsyncMock(side_effect=[project, synopsis, worldview])
        mock_session.execute = AsyncMock(return_value=_mock_execute_result([]))
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(mock_session)
            with pytest.raises(ValueError, match="请先确认人物清单"):
                await service.generate_volume_layer("proj-1")

    @pytest.mark.asyncio
    async def test_volume_already_exists(self, mock_session):
        project = _make_project()
        synopsis = _make_synopsis()
        worldview = _make_worldview()
        char = _make_character()
        existing_unit = _make_story_unit("u0", "proj-1", None, "volume", 1, "第一卷", "已有分卷", 30)
        mock_session.get = AsyncMock(side_effect=[project, synopsis, worldview])
        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([char]),
                _mock_execute_result([existing_unit]),
            ]
        )
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"), \
             patch("src.services.story_unit_service.release_write_lock", new_callable=AsyncMock):
            service = StoryUnitService(mock_session)
            with pytest.raises(ValueError, match="分卷层已生成"):
                await service.generate_volume_layer("proj-1")

    @pytest.mark.asyncio
    async def test_volume_layer_success(self, mock_session):
        project = _make_project()
        synopsis = _make_synopsis()
        worldview = _make_worldview()
        char = _make_character()
        mock_session.get = AsyncMock(side_effect=[project, synopsis, worldview])
        ai_response = {
            "parsed": {
                "units": [
                    {"unit_name": "初入修仙", "synopsis": "主角初入修仙界，拜入门派开始修炼，展现天赋与毅力", "chapter_count": 30, "narrative_duty": "引入主角与世界观"},
                    {"unit_name": "崭露头角", "synopsis": "主角在门派大比中崭露头角，引起各方关注与势力博弈", "chapter_count": 30, "narrative_duty": "主角成长与冲突升级"},
                    {"unit_name": "终成宗师", "synopsis": "主角突破重重困难，终成一代宗师，收束全书主线", "chapter_count": 30, "narrative_duty": "高潮与结局"},
                ]
            },
            "content": "",
        }
        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([char]),
                _mock_execute_result([]),
            ]
        )
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway") as mock_gw, \
             patch("src.services.story_unit_service.release_write_lock", new_callable=AsyncMock):
            mock_gw_instance = MagicMock()
            mock_gw_instance.call_and_parse = AsyncMock(return_value=ai_response)
            mock_gw.return_value = mock_gw_instance
            service = StoryUnitService(mock_session)
            result = await service.generate_volume_layer("proj-1")
            assert len(result) == 3
            assert result[0].unit_name == "初入修仙"
            assert result[0].level_type == "volume"
            assert result[2].unit_name == "终成宗师"
            call_args = mock_gw_instance.call_and_parse.call_args
            assert call_args.kwargs["module"] == "outline"
            assert call_args.kwargs["scene"] == "generate-story-unit"


class TestStoryUnitServiceGenerateLayer:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_parent_not_found(self, mock_session):
        project = _make_project()
        mock_session.get = AsyncMock(side_effect=[project, None])
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(mock_session)
            with pytest.raises(ValueError, match="父单元不存在"):
                await service.generate_layer("proj-1", "nonexistent", "major")

    @pytest.mark.asyncio
    async def test_parent_not_generated(self, mock_session):
        project = _make_project()
        parent = _make_story_unit("vol-1", "proj-1", None, "volume", 1, "第一卷", "概要", 30, gen_status="未生成")
        mock_session.get = AsyncMock(side_effect=[project, parent])
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(mock_session)
            with pytest.raises(ValueError, match="上层尚未生成"):
                await service.generate_layer("proj-1", "vol-1", "major")

    @pytest.mark.asyncio
    async def test_level_mismatch(self, mock_session):
        project = _make_project()
        parent = _make_story_unit("mid-1", "proj-1", "maj-1", "middle", 1, "中篇一", "概要", 10)
        mock_session.get = AsyncMock(side_effect=[project, parent])
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(mock_session)
            with pytest.raises(ValueError, match="层级不匹配"):
                await service.generate_layer("proj-1", "mid-1", "major")

    @pytest.mark.asyncio
    async def test_major_layer_success(self, mock_session):
        project = _make_project()
        parent = _make_story_unit("vol-1", "proj-1", None, "volume", 1, "第一卷", "主角开始修炼之路", 30, duty="引入主角")
        synopsis = _make_synopsis()
        worldview = _make_worldview()
        mock_session.get = AsyncMock(side_effect=[project, parent, synopsis, worldview])
        ai_response = {
            "parsed": {
                "units": [
                    {"unit_name": "大篇一", "synopsis": "主角拜入门派，初识修仙体系，展现过人天赋与坚韧意志", "chapter_count": 25, "narrative_duty": "主角入门"},
                    {"unit_name": "大篇二", "synopsis": "门派大比展开，主角与各方势力弟子激烈交锋，崭露头角", "chapter_count": 30, "narrative_duty": "冲突升级"},
                ]
            },
            "content": "",
        }
        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([]),
                _mock_execute_result([]),
            ]
        )
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway") as mock_gw, \
             patch("src.services.story_unit_service.release_write_lock", new_callable=AsyncMock):
            mock_gw_instance = MagicMock()
            mock_gw_instance.call_and_parse = AsyncMock(return_value=ai_response)
            mock_gw.return_value = mock_gw_instance
            service = StoryUnitService(mock_session)
            result = await service.generate_layer("proj-1", "vol-1", "major")
            assert len(result) == 2
            assert result[0].level_type == "major"
            assert 21 <= result[0].chapter_count <= 100
            assert 21 <= result[1].chapter_count <= 100

    @pytest.mark.asyncio
    async def test_chapter_range_retry(self, mock_session):
        project = _make_project()
        parent = _make_story_unit("vol-1", "proj-1", None, "volume", 1, "第一卷", "主角开始修炼之路", 30, duty="引入主角")
        synopsis = _make_synopsis()
        worldview = _make_worldview()
        mock_session.get = AsyncMock(side_effect=[project, parent, synopsis, worldview])
        first_response = {
            "parsed": {
                "units": [
                    {"unit_name": "大篇一", "synopsis": "章数超区间的测试单元，内容足够长用于验证重试逻辑", "chapter_count": 5, "narrative_duty": "测试"},
                ]
            },
            "content": "",
        }
        retry_response = {
            "parsed": {
                "units": [
                    {"unit_name": "大篇一", "synopsis": "重试后章数合规的测试单元，内容足够长用于验证重试逻辑", "chapter_count": 25, "narrative_duty": "测试"},
                ]
            },
            "content": "",
        }
        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([]),
                _mock_execute_result([]),
            ]
        )
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway") as mock_gw, \
             patch("src.services.story_unit_service.release_write_lock", new_callable=AsyncMock):
            mock_gw_instance = MagicMock()
            mock_gw_instance.call_and_parse = AsyncMock(
                side_effect=[first_response, retry_response]
            )
            mock_gw.return_value = mock_gw_instance
            service = StoryUnitService(mock_session)
            result = await service.generate_layer("proj-1", "vol-1", "major")
            assert mock_gw_instance.call_and_parse.call_count == 2
            assert result[0].chapter_count == 25


class TestStoryUnitServiceCascadeMark:
    @pytest.mark.asyncio
    async def test_cascade_mark_recursive(self):
        session = AsyncMock()
        major = _make_story_unit("maj-1", "proj-1", "vol-1", "major", 1, "大篇一", "概要", 25)
        middle1 = _make_story_unit("mid-1", "proj-1", "maj-1", "middle", 1, "中篇一", "概要", 10, gen_status="已生成")
        middle2 = _make_story_unit("mid-2", "proj-1", "maj-1", "middle", 2, "中篇二", "概要", 10, gen_status="已生成")
        minor1 = _make_story_unit("min-1", "proj-1", "mid-1", "minor", 1, "小篇一", "概要", 3, gen_status="已生成")
        session.get = AsyncMock(return_value=major)
        session.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([middle1, middle2]),
                _mock_execute_result([minor1]),
                _mock_execute_result([]),
                _mock_execute_result([]),
                _mock_execute_result([]),
                _mock_execute_result([]),
                _mock_execute_result([]),
                _mock_execute_result([]),
            ]
        )
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(session)
            count = await service.cascade_mark("maj-1")
            assert count >= 3
            assert middle1.gen_status == "待重新生成"
            assert middle2.gen_status == "待重新生成"
            assert minor1.gen_status == "待重新生成"
            assert middle1.cascade_dirty is True

    @pytest.mark.asyncio
    async def test_cascade_mark_unit_not_found(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(session)
            with pytest.raises(ValueError, match="单元不存在"):
                await service.cascade_mark("nonexistent")


class TestStoryUnitServiceUpdateUnit:
    @pytest.mark.asyncio
    async def test_update_triggers_cascade(self):
        session = AsyncMock()
        unit = _make_story_unit("maj-1", "proj-1", "vol-1", "major", 1, "大篇一", "原概要内容", 25)
        child = _make_story_unit("mid-1", "proj-1", "maj-1", "middle", 1, "中篇一", "子概要", 10, gen_status="已生成")
        session.get = AsyncMock(return_value=unit)
        session.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([child]),
                _mock_execute_result([]),
                _mock_execute_result([]),
                _mock_execute_result([]),
            ]
        )
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(session)
            req = StoryUnitUpdateRequest(
                unit_name="大篇一（修改）",
                synopsis="修改后的概要内容，触发级联标记下层单元待重新生成",
            )
            result = await service.update_unit("maj-1", req)
            assert result.unit_name == "大篇一（修改）"
            assert child.gen_status == "待重新生成"
            assert unit.cascade_dirty is True

    @pytest.mark.asyncio
    async def test_update_name_only_no_cascade(self):
        session = AsyncMock()
        unit = _make_story_unit("maj-1", "proj-1", "vol-1", "major", 1, "大篇一", "原概要内容", 25)
        session.get = AsyncMock(return_value=unit)
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(session)
            req = StoryUnitUpdateRequest(unit_name="新大篇名")
            result = await service.update_unit("maj-1", req)
            assert result.unit_name == "新大篇名"
            assert unit.cascade_dirty is False


class TestStoryUnitServiceListTree:
    @pytest.mark.asyncio
    async def test_empty_tree(self):
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_result([]))
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(session)
            result = await service.list_tree("proj-1")
            assert result.project_id == "proj-1"
            assert result.units == []

    @pytest.mark.asyncio
    async def test_tree_with_units(self):
        session = AsyncMock()
        vol = _make_story_unit("vol-1", "proj-1", None, "volume", 1, "第一卷", "概要", 30)
        maj = _make_story_unit("maj-1", "proj-1", "vol-1", "major", 1, "大篇一", "概要", 25)
        session.execute = AsyncMock(return_value=_mock_execute_result([vol, maj]))
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(session)
            result = await service.list_tree("proj-1")
            assert len(result.units) == 2
            assert result.units[0].level_type == "volume"


class TestExportStoryUnitOutline:
    @pytest.mark.asyncio
    async def test_export_with_story_units(self):
        session = AsyncMock()
        vol = _make_story_unit("vol-1", "proj-1", None, "volume", 1, "初入修仙", "主角初入修仙界开始修炼", 30)
        maj = _make_story_unit("maj-1", "proj-1", "vol-1", "major", 1, "大篇一", "主角拜入门派展现天赋", 25)
        mid = _make_story_unit("mid-1", "proj-1", "maj-1", "middle", 1, "中篇一", "门派日常修炼", 10)
        min_unit = _make_story_unit("min-1", "proj-1", "mid-1", "minor", 1, "小篇一", "入门考核", 3)
        outline = MagicMock()
        outline.outline_id = "outline-1"
        session.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([vol, maj, mid, min_unit]),
                _mock_execute_result([outline]),
                _mock_execute_result([]),
            ]
        )
        from src.services.export_service import ExportService
        service = ExportService(session)
        text = await service._get_outline_text("proj-1")
        assert "【分卷】" in text
        assert "初入修仙" in text
        assert "【大篇】" in text
        assert "【中篇】" in text
        assert "【小篇】" in text

    @pytest.mark.asyncio
    async def test_export_legacy_two_level(self):
        session = AsyncMock()
        outline = MagicMock()
        outline.outline_id = "outline-1"
        outline.project_id = "proj-1"
        vol = MagicMock()
        vol.volume_outline_id = "vol-1"
        vol.volume_no = 1
        vol.volume_name = "第一卷"
        ch = MagicMock()
        ch.chapter_no = 1
        ch.chapter_name = "第一章"
        ch.synopsis_points = "主角初入修仙界，拜入门派开始修炼，展现天赋与毅力"
        session.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([]),
                _mock_execute_result([outline]),
                _mock_execute_result([vol]),
                _mock_execute_result([ch]),
            ]
        )
        from src.services.export_service import ExportService
        service = ExportService(session)
        text = await service._get_outline_text("proj-1")
        assert "第1卷" in text
        assert "第一卷" in text
        assert "第1章" in text
        assert "【分卷】" not in text


class TestRegressionTwoLevelOutline:
    """回归测试：确认现有两级大纲功能不受分层改动影响."""

    @pytest.mark.asyncio
    async def test_legacy_outline_text_no_story_units(self):
        session = AsyncMock()
        outline = MagicMock()
        outline.outline_id = "outline-1"
        outline.project_id = "proj-1"
        vol = MagicMock()
        vol.volume_outline_id = "vol-1"
        vol.volume_no = 1
        vol.volume_name = "起始之卷"
        ch = MagicMock()
        ch.chapter_no = 1
        ch.chapter_name = "初入江湖"
        ch.synopsis_points = "主角踏入江湖，初识各路英豪，展开冒险旅程的序幕篇章"
        session.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([]),
                _mock_execute_result([outline]),
                _mock_execute_result([vol]),
                _mock_execute_result([ch]),
            ]
        )
        from src.services.export_service import ExportService
        service = ExportService(session)
        text = await service._get_outline_text("proj-1")
        assert "第1卷 起始之卷" in text
        assert "第1章 初入江湖" in text
        assert "主角踏入江湖" in text

    @pytest.mark.asyncio
    async def test_writing_no_story_unit_context(self):
        session = AsyncMock()
        from src.services.writing_service import WritingService
        with patch("src.services.writing_service.get_gateway"):
            service = WritingService(session)
            outline = MagicMock()
            outline.outline_id = "outline-1"
            vol = MagicMock()
            vol.volume_outline_id = "vol-1"
            ch_outline = MagicMock()
            ch_outline.story_unit_id = None
            session.execute = AsyncMock(
                side_effect=[
                    _mock_execute_result([outline]),
                    _mock_execute_result([vol]),
                    _mock_execute_result([ch_outline]),
                ]
            )
            ctx = await service._get_story_unit_context("proj-1", 1, 1)
            assert ctx == {}

    @pytest.mark.asyncio
    async def test_writing_with_story_unit_context(self):
        session = AsyncMock()
        from src.services.writing_service import WritingService
        with patch("src.services.writing_service.get_gateway"):
            service = WritingService(session)
            outline = MagicMock()
            outline.outline_id = "outline-1"
            vol = MagicMock()
            vol.volume_outline_id = "vol-1"
            ch_outline = MagicMock()
            ch_outline.story_unit_id = "min-1"
            minor = _make_story_unit("min-1", "proj-1", "mid-1", "minor", 1, "小篇一", "入门考核情节", 3)
            middle = _make_story_unit("mid-1", "proj-1", "maj-1", "middle", 1, "中篇一", "门派日常修炼", 10)
            major = _make_story_unit("maj-1", "proj-1", "vol-1", "major", 1, "大篇一", "主角拜入门派", 25)
            vol_unit = _make_story_unit("vol-1", "proj-1", None, "volume", 1, "第一卷", "主角开始修炼", 30)
            session.execute = AsyncMock(
                side_effect=[
                    _mock_execute_result([outline]),
                    _mock_execute_result([vol]),
                    _mock_execute_result([ch_outline]),
                ]
            )
            session.get = AsyncMock(
                side_effect=[minor, middle, major, vol_unit]
            )
            ctx = await service._get_story_unit_context("proj-1", 1, 1)
            assert "unit_chain" in ctx
            assert len(ctx["unit_chain"]) == 4
            assert ctx["unit_chain"][0]["level_type"] == "volume"
            assert ctx["unit_chain"][3]["level_type"] == "minor"


class TestLayerGenerationOrder:
    """逐层生成顺序校验：分卷→大篇→中篇→小篇."""

    @pytest.mark.asyncio
    async def test_cannot_generate_major_without_volume(self):
        session = AsyncMock()
        project = _make_project()
        session.get = AsyncMock(side_effect=[project, None])
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(session)
            with pytest.raises(ValueError, match="父单元不存在"):
                await service.generate_layer("proj-1", "nonexistent-vol", "major")

    @pytest.mark.asyncio
    async def test_cannot_skip_level(self):
        session = AsyncMock()
        project = _make_project()
        vol_unit = _make_story_unit("vol-1", "proj-1", None, "volume", 1, "第一卷", "概要", 30)
        session.get = AsyncMock(side_effect=[project, vol_unit])
        from src.services.story_unit_service import StoryUnitService
        with patch("src.services.story_unit_service.get_gateway"):
            service = StoryUnitService(session)
            with pytest.raises(ValueError, match="层级不匹配"):
                await service.generate_layer("proj-1", "vol-1", "minor")