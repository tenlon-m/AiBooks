"""批量细化场景功能单元测试."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.api.schemas.scene_outline_schema import (
    BatchSceneSplitRequest,
    SceneDto,
    SceneStreamChunk,
)


class TestBatchSceneSchema:
    def test_batch_request_defaults(self):
        req = BatchSceneSplitRequest(project_id="p1")
        assert req.target_words == 3000
        assert req.user_ideas == ""

    def test_batch_request_missing_project_id(self):
        with pytest.raises(ValidationError):
            BatchSceneSplitRequest()

    def test_stream_chunk_backward_compat(self):
        chunk = SceneStreamChunk(type="chunk", content="x")
        assert chunk.scene is None
        assert chunk.chapter_id is None
        assert chunk.content == "x"

    def test_stream_chunk_with_scene(self):
        scene = SceneDto(scene_order=1, goal="g", key_event="k" * 50)
        chunk = SceneStreamChunk(
            type="chunk",
            content="场景1: g",
            scene=scene,
            chapter_id="c1",
            total=10,
            current=1,
        )
        assert chunk.scene is not None
        assert chunk.scene.goal == "g"
        assert chunk.chapter_id == "c1"
        assert chunk.total == 10

    def test_stream_chunk_failed_type(self):
        chunk = SceneStreamChunk(type="failed", message="AI超时")
        assert chunk.type == "failed"

    def test_stream_chunk_done_with_summary(self):
        chunk = SceneStreamChunk(
            type="done",
            message="完成",
            success_count=8,
            failed_count=2,
            failed_chapters=[{"chapter_id": "c1", "title": "ch1", "reason": "超时"}],
        )
        assert chunk.success_count == 8
        assert chunk.failed_count == 2
        assert len(chunk.failed_chapters) == 1

    def test_stream_chunk_json_serialization(self):
        scene = SceneDto(scene_order=1, goal="g", key_event="k" * 50)
        chunk = SceneStreamChunk(type="chunk", scene=scene, chapter_id="c1")
        js = chunk.model_dump_json()
        assert '"scene"' in js
        assert '"chapter_id":"c1"' in js


class TestBatchStreamSplit:
    """测试 batch_stream_split 编排逻辑（mock split 方法）."""

    @pytest.fixture
    def mock_chapters(self):
        ch1 = MagicMock()
        ch1.chapter_id = "c1"
        ch1.title = "第一章"
        ch1.volume_no = 1
        ch1.chapter_no = 1
        ch2 = MagicMock()
        ch2.chapter_id = "c2"
        ch2.title = "第二章"
        ch2.volume_no = 1
        ch2.chapter_no = 2
        return [ch1, ch2]

    @pytest.mark.asyncio
    async def test_no_unrefined_chapters(self):
        from src.services.scene_outline_service import SceneOutlineService

        session = AsyncMock()
        service = SceneOutlineService(session)

        with patch.object(service, "_find_unrefined_chapters", return_value=[]):
            project_mock = MagicMock()
            with patch.object(session, "get", return_value=project_mock):
                chunks = []
                async for chunk in service.batch_stream_split("p1"):
                    chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].type == "done"
        assert "无需批量处理" in chunks[0].message

    @pytest.mark.asyncio
    async def test_project_not_found(self):
        from src.services.scene_outline_service import SceneOutlineService

        session = AsyncMock()
        service = SceneOutlineService(session)

        with patch.object(session, "get", return_value=None):
            chunks = []
            async for chunk in service.batch_stream_split("p1"):
                chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].type == "done"
        assert "项目不存在" in chunks[0].message

    @pytest.mark.asyncio
    async def test_success_path(self, mock_chapters):
        from src.services.scene_outline_service import SceneOutlineService
        from src.api.schemas.scene_outline_schema import SceneSplitResponse

        session = AsyncMock()
        service = SceneOutlineService(session)

        scenes = [SceneDto(scene_order=1, goal="g1", key_event="k" * 50)]
        mock_response = SceneSplitResponse(scenes=scenes)

        with patch.object(service, "_find_unrefined_chapters", return_value=mock_chapters):
            with patch.object(session, "get", return_value=MagicMock()):
                with patch.object(service, "split", return_value=mock_response):
                    with patch("src.services.scene_outline_service.release_write_lock", return_value=None):
                        chunks = []
                        async for chunk in service.batch_stream_split("p1"):
                            chunks.append(chunk)

        types = [c.type for c in chunks]
        assert types[0] == "progress"
        assert "chunk" in types
        assert types[-1] == "done"
        assert chunks[-1].success_count == 2
        assert chunks[-1].failed_count == 0

    @pytest.mark.asyncio
    async def test_single_chapter_failure_isolation(self, mock_chapters):
        from src.services.scene_outline_service import SceneOutlineService
        from src.api.schemas.scene_outline_schema import SceneSplitResponse

        session = AsyncMock()
        service = SceneOutlineService(session)

        scenes = [SceneDto(scene_order=1, goal="g1", key_event="k" * 50)]
        mock_response = SceneSplitResponse(scenes=scenes)

        async def mock_split(project_id, chapter_id, target_words=3000, user_ideas=""):
            if chapter_id == "c1":
                raise ValueError("关键事件不足50字")
            return mock_response

        with patch.object(service, "_find_unrefined_chapters", return_value=mock_chapters):
            with patch.object(session, "get", return_value=MagicMock()):
                with patch.object(service, "split", side_effect=mock_split):
                    with patch("src.services.scene_outline_service.release_write_lock", return_value=None):
                        chunks = []
                        async for chunk in service.batch_stream_split("p1"):
                            chunks.append(chunk)

        types = [c.type for c in chunks]
        assert "failed" in types
        assert types[-1] == "done"
        assert chunks[-1].success_count == 1
        assert chunks[-1].failed_count == 1
        assert len(chunks[-1].failed_chapters) == 1

    @pytest.mark.asyncio
    async def test_timeout_isolation(self, mock_chapters):
        from src.services.scene_outline_service import SceneOutlineService
        from src.api.schemas.scene_outline_schema import SceneSplitResponse

        session = AsyncMock()
        service = SceneOutlineService(session)

        scenes = [SceneDto(scene_order=1, goal="g1", key_event="k" * 50)]
        mock_response = SceneSplitResponse(scenes=scenes)

        async def mock_split(project_id, chapter_id, target_words=3000, user_ideas=""):
            if chapter_id == "c1":
                raise TimeoutError("AI超时")
            return mock_response

        with patch.object(service, "_find_unrefined_chapters", return_value=mock_chapters):
            with patch.object(session, "get", return_value=MagicMock()):
                with patch.object(service, "split", side_effect=mock_split):
                    with patch("src.services.scene_outline_service.release_write_lock", return_value=None):
                        chunks = []
                        async for chunk in service.batch_stream_split("p1"):
                            chunks.append(chunk)

        types = [c.type for c in chunks]
        assert "failed" in types
        assert chunks[-1].failed_count == 1
        assert chunks[-1].success_count == 1


class TestStreamSplitContract:
    """测试 stream_split 契约修复（scene 字段非空）."""

    @pytest.mark.asyncio
    async def test_stream_split_yields_scene_field(self):
        from src.services.scene_outline_service import SceneOutlineService
        from src.api.schemas.scene_outline_schema import SceneSplitResponse

        session = AsyncMock()
        service = SceneOutlineService(session)

        scenes = [
            SceneDto(scene_order=1, goal="g1", key_event="k" * 50),
            SceneDto(scene_order=2, goal="g2", key_event="k" * 50),
        ]
        mock_response = SceneSplitResponse(scenes=scenes)

        with patch.object(service, "split", return_value=mock_response):
            chunks = []
            async for chunk in service.stream_split("p1", "c1"):
                chunks.append(chunk)

        chunk_events = [c for c in chunks if c.type == "chunk"]
        assert len(chunk_events) == 2
        for ce in chunk_events:
            assert ce.scene is not None
            assert ce.chapter_id == "c1"