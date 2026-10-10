"""AI写剧本服务单元测试."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.schemas.script_schema import (
    ScriptEpisodeDto,
    ScriptExportRequest,
    ScriptGenerateRequest,
    ScriptProgressEvent,
)


def _make_long_text(prefix: str) -> str:
    return (
        prefix
        + "这是一段足够长的内容用于通过最小字数校验，包含场景描述和角色对白等详细信息，"
        "确保总长度超过五十字的最低要求门槛，从而不会触发重试逻辑。"
    )


def _mock_scalars_first(value):
    result = MagicMock()
    result.scalars.return_value.first.return_value = value
    return result


def _mock_scalars_all(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


class TestScriptSchema:
    def test_script_generate_request(self):
        req = ScriptGenerateRequest(project_id="test-project")
        assert req.project_id == "test-project"

    def test_script_export_request_default_format(self):
        req = ScriptExportRequest(project_id="test-project", target_dir="/tmp")
        assert req.format == "txt"

    def test_script_export_request_custom_format(self):
        req = ScriptExportRequest(
            project_id="test-project", target_dir="/tmp", format="md"
        )
        assert req.format == "md"

    def test_script_progress_event_minimal(self):
        event = ScriptProgressEvent(type="progress")
        assert event.type == "progress"
        assert event.episode_no is None
        assert event.progress is None

    def test_script_progress_event_full(self):
        event = ScriptProgressEvent(
            type="episode_done",
            episode_no=1,
            scene_description="场景",
            character_dialogue="对白",
            message="完成",
            progress=50,
        )
        assert event.episode_no == 1
        assert event.scene_description == "场景"
        assert event.character_dialogue == "对白"
        assert event.progress == 50

    def test_script_episode_dto(self):
        dto = ScriptEpisodeDto(
            script_id="s1",
            project_id="p1",
            episode_no=1,
            scene_description="场景",
            character_dialogue="对白",
            created_at=datetime.now(),
        )
        assert dto.episode_no == 1
        assert dto.script_id == "s1"


class TestScriptService:
    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture
    def mock_project(self):
        project = MagicMock()
        project.project_id = "test-project-id"
        project.book_title = "测试小说"
        return project

    @pytest.fixture
    def mock_outline(self):
        outline = MagicMock()
        outline.outline_id = "outline-1"
        outline.gen_status = "已生成"
        return outline

    @pytest.fixture
    def mock_volume(self):
        vol = MagicMock()
        vol.volume_outline_id = "vol-1"
        vol.volume_no = 1
        vol.volume_name = "第一卷"
        return vol

    @pytest.fixture
    def mock_chapters(self):
        ch1 = MagicMock()
        ch1.chapter_no = 1
        ch1.chapter_name = "第一章"
        ch1.synopsis_points = "主角踏上修炼之路，初入宗门"
        ch1.characters_appearing = "主角"
        ch1.story_unit_id = None

        ch2 = MagicMock()
        ch2.chapter_no = 2
        ch2.chapter_name = "第二章"
        ch2.synopsis_points = "主角遇到强敌，首次交锋"
        ch2.characters_appearing = "主角"
        ch2.story_unit_id = None
        return [ch1, ch2]

    @pytest.fixture
    def mock_character(self):
        char = MagicMock()
        char.name = "主角"
        char.identity = "主角"
        char.intro = "勇敢的少年"
        char.relation = "无"
        return char

    def _setup_execute_side_effects(
        self, mock_session, mock_outline, mock_volume, mock_chapters, mock_character
    ):
        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalars_first(mock_outline),
                _mock_scalars_all([mock_volume]),
                _mock_scalars_all(mock_chapters),
                _mock_scalars_all([mock_character]),
                _mock_scalars_all([]),
            ]
        )

    @pytest.mark.asyncio
    async def test_generate_script_success(
        self, mock_session, mock_project, mock_outline, mock_volume, mock_chapters, mock_character
    ):
        mock_session.get = AsyncMock(return_value=mock_project)
        self._setup_execute_side_effects(
            mock_session, mock_outline, mock_volume, mock_chapters, mock_character
        )

        long_scene = _make_long_text("场景描述：")
        long_dialogue = _make_long_text("角色对白：")

        with patch("src.services.script_service.get_gateway") as mock_gw, \
             patch("src.services.script_service.release_write_lock", new_callable=AsyncMock), \
             patch("src.services.script_service.get_config") as mock_cfg:
            mock_cfg.return_value.script_generate_timeout_seconds = 90
            mock_cfg.return_value.min_ai_content_length = 50
            mock_gw_instance = MagicMock()
            mock_gw_instance.call_and_parse = AsyncMock(
                return_value={
                    "parsed": {
                        "scene_description": long_scene,
                        "character_dialogue": long_dialogue,
                    }
                }
            )
            mock_gw.return_value = mock_gw_instance

            from src.services.script_service import ScriptService
            service = ScriptService(mock_session)
            events = []
            async for event in service.generate_script("test-project-id"):
                events.append(event)

        episode_done = [e for e in events if e.type == "episode_done"]
        assert len(episode_done) == 2
        assert episode_done[0].scene_description == long_scene
        assert episode_done[0].character_dialogue == long_dialogue
        assert episode_done[1].episode_no == 2
        assert events[-1].type == "completed"
        assert events[-1].progress == 100
        assert mock_gw_instance.call_and_parse.call_count == 2

    @pytest.mark.asyncio
    async def test_generate_script_outline_not_generated(self, mock_session, mock_project):
        mock_session.get = AsyncMock(return_value=mock_project)

        mock_outline = MagicMock()
        mock_outline.outline_id = "outline-1"
        mock_outline.gen_status = "未生成"
        mock_session.execute = AsyncMock(
            side_effect=[_mock_scalars_first(mock_outline)]
        )

        from src.services.script_service import ScriptService
        service = ScriptService(mock_session)
        events = []
        async for event in service.generate_script("test-project-id"):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert "大纲" in events[0].message

    @pytest.mark.asyncio
    async def test_generate_script_no_outline(self, mock_session, mock_project):
        mock_session.get = AsyncMock(return_value=mock_project)
        mock_session.execute = AsyncMock(
            side_effect=[_mock_scalars_first(None)]
        )

        from src.services.script_service import ScriptService
        service = ScriptService(mock_session)
        events = []
        async for event in service.generate_script("test-project-id"):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert "大纲" in events[0].message

    @pytest.mark.asyncio
    async def test_generate_script_project_not_found(self, mock_session):
        mock_session.get = AsyncMock(return_value=None)

        from src.services.script_service import ScriptService
        service = ScriptService(mock_session)
        events = []
        async for event in service.generate_script("nonexistent"):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert "项目不存在" in events[0].message

    @pytest.mark.asyncio
    async def test_generate_script_retry_on_short_content(
        self, mock_session, mock_project, mock_outline, mock_volume, mock_chapters, mock_character
    ):
        mock_session.get = AsyncMock(return_value=mock_project)
        self._setup_execute_side_effects(
            mock_session, mock_outline, mock_volume, mock_chapters, mock_character
        )

        short_scene = "短场景"
        short_dialogue = "短对白"
        long_scene = _make_long_text("场景描述：")
        long_dialogue = _make_long_text("角色对白：")

        with patch("src.services.script_service.get_gateway") as mock_gw, \
             patch("src.services.script_service.release_write_lock", new_callable=AsyncMock), \
             patch("src.services.script_service.get_config") as mock_cfg:
            mock_cfg.return_value.script_generate_timeout_seconds = 90
            mock_cfg.return_value.min_ai_content_length = 50
            mock_gw_instance = MagicMock()
            mock_gw_instance.call_and_parse = AsyncMock(
                side_effect=[
                    {"parsed": {"scene_description": short_scene, "character_dialogue": short_dialogue}},
                    {"parsed": {"scene_description": long_scene, "character_dialogue": long_dialogue}},
                    {"parsed": {"scene_description": long_scene, "character_dialogue": long_dialogue}},
                ]
            )
            mock_gw.return_value = mock_gw_instance

            from src.services.script_service import ScriptService
            service = ScriptService(mock_session)
            events = []
            async for event in service.generate_script("test-project-id"):
                events.append(event)

        episode_done = [e for e in events if e.type == "episode_done"]
        assert len(episode_done) == 2
        assert episode_done[0].scene_description == long_scene
        assert episode_done[0].character_dialogue == long_dialogue
        assert mock_gw_instance.call_and_parse.call_count == 3

    @pytest.mark.asyncio
    async def test_generate_script_ai_returns_empty(
        self, mock_session, mock_project, mock_outline, mock_volume, mock_chapters, mock_character
    ):
        mock_session.get = AsyncMock(return_value=mock_project)
        self._setup_execute_side_effects(
            mock_session, mock_outline, mock_volume, mock_chapters, mock_character
        )

        with patch("src.services.script_service.get_gateway") as mock_gw, \
             patch("src.services.script_service.release_write_lock", new_callable=AsyncMock), \
             patch("src.services.script_service.get_config") as mock_cfg:
            mock_cfg.return_value.script_generate_timeout_seconds = 90
            mock_cfg.return_value.min_ai_content_length = 50
            mock_gw_instance = MagicMock()
            mock_gw_instance.call_and_parse = AsyncMock(
                return_value={"parsed": {"scene_description": "", "character_dialogue": ""}}
            )
            mock_gw.return_value = mock_gw_instance

            from src.services.script_service import ScriptService
            service = ScriptService(mock_session)
            events = []
            async for event in service.generate_script("test-project-id"):
                events.append(event)

        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert "失败" in error_events[0].message

    @pytest.mark.asyncio
    async def test_list_episodes(self, mock_session):
        mock_script = MagicMock()
        mock_script.script_id = "s1"
        mock_script.project_id = "test-project-id"
        mock_script.episode_no = 1
        mock_script.scene_description = "场景"
        mock_script.character_dialogue = "对白"
        mock_script.created_at = datetime.now()

        mock_session.execute = AsyncMock(
            side_effect=[_mock_scalars_all([mock_script])]
        )

        from src.services.script_service import ScriptService
        service = ScriptService(mock_session)
        result = await service.list_episodes("test-project-id")

        assert len(result) == 1
        assert isinstance(result[0], ScriptEpisodeDto)
        assert result[0].episode_no == 1
        assert result[0].scene_description == "场景"

    @pytest.mark.asyncio
    async def test_list_episodes_empty(self, mock_session):
        mock_session.execute = AsyncMock(
            side_effect=[_mock_scalars_all([])]
        )

        from src.services.script_service import ScriptService
        service = ScriptService(mock_session)
        result = await service.list_episodes("test-project-id")

        assert result == []

    @pytest.mark.asyncio
    async def test_export_script_success(self, mock_session, mock_project):
        mock_session.get = AsyncMock(return_value=mock_project)

        mock_script = MagicMock()
        mock_script.script_id = "s1"
        mock_script.project_id = "test-project-id"
        mock_script.episode_no = 1
        mock_script.scene_description = "场景描述内容"
        mock_script.character_dialogue = "角色对白内容"
        mock_script.created_at = datetime.now()

        mock_session.execute = AsyncMock(
            side_effect=[_mock_scalars_all([mock_script])]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            from src.services.script_service import ScriptService
            service = ScriptService(mock_session)
            result = await service.export_script("test-project-id", tmpdir, "txt")

            assert result["episode_count"] == 1
            assert os.path.exists(result["file_path"])
            assert result["file_path"].endswith(".txt")
            with open(result["file_path"], "r", encoding="utf-8") as f:
                content = f.read()
            assert "测试小说" in content
            assert "第1集" in content
            assert "场景描述内容" in content
            assert "角色对白内容" in content
            assert "【场景描述】" in content
            assert "【角色对白】" in content

    @pytest.mark.asyncio
    async def test_export_script_no_episodes(self, mock_session, mock_project):
        mock_session.get = AsyncMock(return_value=mock_project)
        mock_session.execute = AsyncMock(
            side_effect=[_mock_scalars_all([])]
        )

        from src.services.script_service import ScriptService
        service = ScriptService(mock_session)
        with pytest.raises(ValueError, match="暂无剧本"):
            await service.export_script("test-project-id", "/tmp", "txt")

    @pytest.mark.asyncio
    async def test_export_script_project_not_found(self, mock_session):
        mock_session.get = AsyncMock(return_value=None)

        from src.services.script_service import ScriptService
        service = ScriptService(mock_session)
        with pytest.raises(ValueError, match="项目不存在"):
            await service.export_script("nonexistent", "/tmp", "txt")

    @pytest.mark.asyncio
    async def test_export_script_path_traversal(self, mock_session, mock_project):
        mock_session.get = AsyncMock(return_value=mock_project)

        mock_script = MagicMock()
        mock_script.script_id = "s1"
        mock_script.project_id = "test-project-id"
        mock_script.episode_no = 1
        mock_script.scene_description = "场景"
        mock_script.character_dialogue = "对白"
        mock_script.created_at = datetime.now()

        mock_session.execute = AsyncMock(
            side_effect=[_mock_scalars_all([mock_script])]
        )

        from src.services.script_service import ScriptService
        service = ScriptService(mock_session)
        with pytest.raises(ValueError, match="目录穿越"):
            await service.export_script("test-project-id", "../../../etc", "txt")

    @pytest.mark.asyncio
    async def test_generate_script_no_characters(
        self, mock_session, mock_project, mock_outline, mock_volume, mock_chapters
    ):
        mock_session.get = AsyncMock(return_value=mock_project)
        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalars_first(mock_outline),
                _mock_scalars_all([mock_volume]),
                _mock_scalars_all(mock_chapters),
                _mock_scalars_all([]),
            ]
        )

        from src.services.script_service import ScriptService
        service = ScriptService(mock_session)
        events = []
        async for event in service.generate_script("test-project-id"):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert "人物" in events[0].message

    @pytest.mark.asyncio
    async def test_generate_script_no_valid_chapters(
        self, mock_session, mock_project, mock_outline, mock_volume, mock_character
    ):
        mock_session.get = AsyncMock(return_value=mock_project)

        empty_ch = MagicMock()
        empty_ch.chapter_no = 1
        empty_ch.chapter_name = "第一章"
        empty_ch.synopsis_points = ""
        empty_ch.characters_appearing = ""
        empty_ch.story_unit_id = None

        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalars_first(mock_outline),
                _mock_scalars_all([mock_volume]),
                _mock_scalars_all([empty_ch]),
                _mock_scalars_all([mock_character]),
            ]
        )

        from src.services.script_service import ScriptService
        service = ScriptService(mock_session)
        events = []
        async for event in service.generate_script("test-project-id"):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert "大纲" in events[0].message

    @pytest.mark.asyncio
    async def test_generate_script_outline_units_match_outline_hierarchy(
        self, mock_session, mock_project, mock_outline, mock_character
    ):
        mock_session.get = AsyncMock(return_value=mock_project)

        vol1 = MagicMock()
        vol1.volume_outline_id = "vol-1"
        vol1.volume_no = 1
        vol1.volume_name = "第一卷"

        vol2 = MagicMock()
        vol2.volume_outline_id = "vol-2"
        vol2.volume_no = 2
        vol2.volume_name = "第二卷"

        ch1 = MagicMock()
        ch1.chapter_no = 1
        ch1.chapter_name = "第一章"
        ch1.synopsis_points = "第一卷第一章梗概"
        ch1.characters_appearing = "主角"
        ch1.story_unit_id = None

        ch2 = MagicMock()
        ch2.chapter_no = 1
        ch2.chapter_name = "第一章"
        ch2.synopsis_points = "第二卷第一章梗概"
        ch2.characters_appearing = "主角"
        ch2.story_unit_id = None

        long_scene = _make_long_text("场景描述：")
        long_dialogue = _make_long_text("角色对白：")

        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalars_first(mock_outline),
                _mock_scalars_all([vol1, vol2]),
                _mock_scalars_all([ch1]),
                _mock_scalars_all([ch2]),
                _mock_scalars_all([mock_character]),
                _mock_scalars_all([]),
            ]
        )

        with patch("src.services.script_service.get_gateway") as mock_gw, \
             patch("src.services.script_service.release_write_lock", new_callable=AsyncMock), \
             patch("src.services.script_service.get_config") as mock_cfg:
            mock_cfg.return_value.script_generate_timeout_seconds = 90
            mock_cfg.return_value.min_ai_content_length = 50
            mock_gw_instance = MagicMock()
            mock_gw_instance.call_and_parse = AsyncMock(
                return_value={
                    "parsed": {
                        "scene_description": long_scene,
                        "character_dialogue": long_dialogue,
                    }
                }
            )
            mock_gw.return_value = mock_gw_instance

            from src.services.script_service import ScriptService
            service = ScriptService(mock_session)
            events = []
            async for event in service.generate_script("test-project-id"):
                events.append(event)

        episode_done = [e for e in events if e.type == "episode_done"]
        assert len(episode_done) == 2
        assert episode_done[0].episode_no == 1
        assert episode_done[1].episode_no == 2
        assert events[-1].type == "completed"

    @pytest.mark.asyncio
    async def test_generate_script_ai_call_uses_correct_module_and_scene(
        self, mock_session, mock_project, mock_outline, mock_volume, mock_chapters, mock_character
    ):
        mock_session.get = AsyncMock(return_value=mock_project)
        self._setup_execute_side_effects(
            mock_session, mock_outline, mock_volume, mock_chapters, mock_character
        )

        long_scene = _make_long_text("场景描述：")
        long_dialogue = _make_long_text("角色对白：")

        with patch("src.services.script_service.get_gateway") as mock_gw, \
             patch("src.services.script_service.release_write_lock", new_callable=AsyncMock), \
             patch("src.services.script_service.get_config") as mock_cfg:
            mock_cfg.return_value.script_generate_timeout_seconds = 90
            mock_cfg.return_value.min_ai_content_length = 50
            mock_gw_instance = MagicMock()
            mock_gw_instance.call_and_parse = AsyncMock(
                return_value={
                    "parsed": {
                        "scene_description": long_scene,
                        "character_dialogue": long_dialogue,
                    }
                }
            )
            mock_gw.return_value = mock_gw_instance

            from src.services.script_service import ScriptService
            service = ScriptService(mock_session)
            async for _ in service.generate_script("test-project-id"):
                pass

            call_args = mock_gw_instance.call_and_parse.call_args_list[0]
            assert call_args.kwargs["module"] == "writing"
            assert call_args.kwargs["scene"] == "script"
            assert "outline_units" in call_args.kwargs["params"]
            assert "characters" in call_args.kwargs["params"]
            assert "episode_no" in call_args.kwargs["params"]