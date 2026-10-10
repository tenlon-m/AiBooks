"""创作参数AI润色服务单元测试与端点集成测试."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.api.schemas.creation_schema import CreationPolishRequest, CreationPolishResponse


class TestCreationPolishSchema:
    def test_valid_synopsis_request(self):
        req = CreationPolishRequest(
            target="synopsis",
            raw_ideas="主角是一个普通人，意外获得神功，开始修炼之路",
            book_title="测试小说",
            volume_count=3,
            chapters_per_volume=10,
            words_per_chapter=3000,
        )
        assert req.target == "synopsis"
        assert req.raw_ideas == "主角是一个普通人，意外获得神功，开始修炼之路"

    def test_valid_worldview_request(self):
        req = CreationPolishRequest(
            target="worldview",
            raw_ideas="修仙世界，有灵气，有境界划分，有各大门派",
            book_title="测试小说",
            volume_count=3,
            chapters_per_volume=10,
            words_per_chapter=3000,
            synopsis="已有梗概内容",
        )
        assert req.target == "worldview"
        assert req.synopsis == "已有梗概内容"

    def test_raw_ideas_too_short(self):
        with pytest.raises(ValidationError):
            CreationPolishRequest(
                target="synopsis",
                raw_ideas="太短",
                volume_count=1,
                chapters_per_volume=1,
                words_per_chapter=500,
            )

    def test_invalid_target(self):
        with pytest.raises(ValidationError):
            CreationPolishRequest(
                target="invalid",
                raw_ideas="这是一个足够长的思路描述用于测试",
                volume_count=1,
                chapters_per_volume=1,
                words_per_chapter=500,
            )

    def test_response(self):
        resp = CreationPolishResponse(
            target="synopsis",
            polished_content="这是一个完善后的故事梗概，内容足够长，超过五十字，可以正常通过保存校验规则。",
        )
        assert resp.source == "ai_polish"
        assert resp.target == "synopsis"


class TestCreationPolishService:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        return session

    @pytest.fixture
    def mock_project(self):
        project = MagicMock()
        project.project_id = "test-project-id"
        project.book_title = "测试小说"
        return project

    @pytest.fixture
    def valid_synopsis_req(self):
        return CreationPolishRequest(
            target="synopsis",
            raw_ideas="主角是一个普通人，意外获得神功，开始修炼之路",
            book_title="测试小说",
            volume_count=3,
            chapters_per_volume=10,
            words_per_chapter=3000,
        )

    @pytest.fixture
    def valid_worldview_req(self):
        return CreationPolishRequest(
            target="worldview",
            raw_ideas="修仙世界，有灵气，有境界划分，有各大门派",
            book_title="测试小说",
            volume_count=3,
            chapters_per_volume=10,
            words_per_chapter=3000,
            synopsis="主角获得神功开始修炼",
        )

    @pytest.mark.asyncio
    async def test_project_not_found(self, mock_session, valid_synopsis_req):
        mock_session.get = AsyncMock(return_value=None)
        from src.services.creation_polish_service import CreationPolishService
        service = CreationPolishService(mock_session)
        with pytest.raises(ValueError, match="项目不存在"):
            await service.polish_creation("nonexistent", valid_synopsis_req)

    @pytest.mark.asyncio
    async def test_synopsis_polish_success(self, mock_session, mock_project, valid_synopsis_req):
        mock_session.get = AsyncMock(return_value=mock_project)
        long_content = "这是一个完善后的故事梗概，主角原本是一个普通人，在一次意外中获得了上古神功传承，从此踏上了修炼之路，经历了无数艰难险阻，最终成为一代宗师。"
        with patch("src.services.creation_polish_service.get_gateway") as mock_gw, \
             patch("src.services.creation_polish_service.release_write_lock", new_callable=AsyncMock):
            mock_gw_instance = MagicMock()
            mock_gw_instance.call_and_parse = AsyncMock(return_value={
                "parsed": {"polished_content": long_content},
                "content": long_content,
            })
            mock_gw.return_value = mock_gw_instance
            from src.services.creation_polish_service import CreationPolishService
            service = CreationPolishService(mock_session)
            result = await service.polish_creation("test-project-id", valid_synopsis_req)
            assert result.target == "synopsis"
            assert result.polished_content == long_content
            assert result.source == "ai_polish"
            call_args = mock_gw_instance.call_and_parse.call_args
            assert call_args.kwargs["module"] == "creation"
            assert call_args.kwargs["scene"] == "polish-synopsis"

    @pytest.mark.asyncio
    async def test_worldview_polish_success(self, mock_session, mock_project, valid_worldview_req):
        mock_session.get = AsyncMock(return_value=mock_project)
        long_content = "这是一个完善后的世界观设定，世界分为凡人界和修仙界，修仙者按境界划分为练气、筑基、金丹、元婴、化神五个大境界，各大门派林立。"
        with patch("src.services.creation_polish_service.get_gateway") as mock_gw, \
             patch("src.services.creation_polish_service.release_write_lock", new_callable=AsyncMock):
            mock_gw_instance = MagicMock()
            mock_gw_instance.call_and_parse = AsyncMock(return_value={
                "parsed": {"polished_content": long_content},
                "content": long_content,
            })
            mock_gw.return_value = mock_gw_instance
            from src.services.creation_polish_service import CreationPolishService
            service = CreationPolishService(mock_session)
            result = await service.polish_creation("test-project-id", valid_worldview_req)
            assert result.target == "worldview"
            call_args = mock_gw_instance.call_and_parse.call_args
            assert call_args.kwargs["scene"] == "polish-worldview"
            assert call_args.kwargs["params"]["synopsis"] == "主角获得神功开始修炼"

    @pytest.mark.asyncio
    async def test_ai_returns_empty(self, mock_session, mock_project, valid_synopsis_req):
        mock_session.get = AsyncMock(return_value=mock_project)
        with patch("src.services.creation_polish_service.get_gateway") as mock_gw, \
             patch("src.services.creation_polish_service.release_write_lock", new_callable=AsyncMock):
            mock_gw_instance = MagicMock()
            mock_gw_instance.call_and_parse = AsyncMock(return_value={
                "parsed": {"polished_content": ""},
                "content": "",
            })
            mock_gw.return_value = mock_gw_instance
            from src.services.creation_polish_service import CreationPolishService
            service = CreationPolishService(mock_session)
            with pytest.raises(ValueError, match="AI 未返回有效内容"):
                await service.polish_creation("test-project-id", valid_synopsis_req)

    @pytest.mark.asyncio
    async def test_ai_returns_too_short(self, mock_session, mock_project, valid_synopsis_req):
        mock_session.get = AsyncMock(return_value=mock_project)
        with patch("src.services.creation_polish_service.get_gateway") as mock_gw, \
             patch("src.services.creation_polish_service.release_write_lock", new_callable=AsyncMock):
            mock_gw_instance = MagicMock()
            mock_gw_instance.call_and_parse = AsyncMock(return_value={
                "parsed": {"polished_content": "太短了"},
                "content": "太短了",
            })
            mock_gw.return_value = mock_gw_instance
            from src.services.creation_polish_service import CreationPolishService
            service = CreationPolishService(mock_session)
            with pytest.raises(ValueError, match="润色结果过短"):
                await service.polish_creation("test-project-id", valid_synopsis_req)