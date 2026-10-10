"""一键拆书服务单元测试."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import Project, Synopsis, Worldview
from src.services.book_teardown_service import BookTeardownService


def _run(coro):
    return asyncio.run(coro)


class TestBookTeardownService:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.get = AsyncMock()
        return session

    @pytest.fixture
    def mock_gateway(self):
        gateway = AsyncMock()
        gateway.call_and_parse = AsyncMock()
        return gateway

    @pytest.fixture
    def service(self, mock_session, mock_gateway):
        with patch(
            "src.services.book_teardown_service.get_gateway", return_value=mock_gateway
        ):
            return BookTeardownService(mock_session)

    def test_parse_txt(self, service, mock_session, tmp_path):
        content = (
            "主角名叫张三，他在一个修仙世界中开始了自己的修炼之旅，"
            "途中遇到了各种奇遇与挑战，逐渐成长为一代宗师的故事。"
        )
        file_path = tmp_path / "novel.txt"
        file_path.write_text(content, encoding="utf-8")
        result = _run(service.upload_and_parse(str(file_path)))
        assert result.file_format == "txt"
        assert result.char_count == len(content)
        assert result.content == content

    def test_unsupported_format(self, service, tmp_path):
        file_path = tmp_path / "data.xlsx"
        file_path.write_bytes(b"fake content for unsupported format test")
        with pytest.raises(ValueError, match="不支持的文件格式"):
            _run(service.upload_and_parse(str(file_path)))

    def test_teardown_outline(self, service, mock_session, mock_gateway):
        record = MagicMock()
        record.multi_level_outline = (
            "这是一段足够长的书籍内容用于测试多级大纲拆解功能，"
            "主角在修仙世界冒险成长，历经磨难终成大道。"
        )
        mock_session.get = AsyncMock(return_value=record)
        mock_gateway.call_and_parse = AsyncMock(
            return_value={
                "parsed": {
                    "multi_level_outline": (
                        "第一卷 初入江湖\n"
                        "　第一章 觉醒\n"
                        "　　场景一 灵根测试\n"
                        "　　场景二 拜入宗门\n"
                        "　第二章 修炼\n"
                        "　　场景一 吐纳天地"
                    )
                }
            }
        )
        with patch(
            "src.services.book_teardown_service.release_write_lock", new=AsyncMock()
        ):
            result = _run(service.teardown_outline("test-teardown-id"))
        assert result.teardown_id == "test-teardown-id"
        assert "第一卷" in result.multi_level_outline
        assert "场景一" in result.multi_level_outline
        assert "　" in result.multi_level_outline

    def test_extract_elements(self, service, mock_session, mock_gateway):
        record = MagicMock()
        record.multi_level_outline = "多级大纲内容，主角张三在修仙世界冒险成长的故事。"
        mock_session.get = AsyncMock(return_value=record)
        mock_gateway.call_and_parse = AsyncMock(
            return_value={
                "parsed": {
                    "characters": "张三：主角，修仙者，性格坚韧不拔，天赋异禀",
                    "time_places": "修仙界，青云宗，历时百年，跨越多个秘境",
                    "worldview": "修仙世界，有灵气与境界划分，共九大境界",
                    "special_items": "天灵剑、储物戒、聚灵丹、传讯玉简",
                    "events": "灵根觉醒、拜入宗门、首次历练、突破境界",
                }
            }
        )
        with patch(
            "src.services.book_teardown_service.release_write_lock", new=AsyncMock()
        ):
            result = _run(service.extract_elements("test-teardown-id"))
        assert result.characters is not None
        assert "张三" in result.characters
        assert result.time_places is not None
        assert result.worldview is not None
        assert result.special_items is not None
        assert result.events is not None

    def test_create_project_prefill(self, service, mock_session):
        record = MagicMock()
        record.multi_level_outline = (
            "多级大纲内容，主角张三在修仙世界冒险成长的故事梗概，内容详尽。"
        )
        record.worldview_setting = "修仙世界观设定内容，有灵气境界划分。"
        record.teardown_status = "已提取要素"
        mock_session.get = AsyncMock(return_value=record)
        added: list = []
        mock_session.add = MagicMock(side_effect=lambda x: added.append(x))
        result = _run(
            service.create_project_from_teardown("test-teardown-id", "测试二创小说")
        )
        assert result["book_title"] == "测试二创小说"
        assert result["project_id"]
        assert result["teardown_id"] == "test-teardown-id"
        assert any(isinstance(item, Project) for item in added)
        assert any(isinstance(item, Synopsis) for item in added)
        assert any(isinstance(item, Worldview) for item in added)
        synopsis_item = next(item for item in added if isinstance(item, Synopsis))
        assert "张三" in synopsis_item.content
        worldview_item = next(item for item in added if isinstance(item, Worldview))
        assert "修仙" in worldview_item.content

    def test_large_file_batch(self, service, mock_session, tmp_path):
        content = "测试内容段落，主角冒险成长。" * 20000
        file_path = tmp_path / "large_novel.txt"
        file_path.write_text(content, encoding="utf-8")
        result = _run(service.upload_and_parse(str(file_path)))
        assert result.char_count == len(content)
        assert result.char_count > 100000
        assert service._batch_count == 1

    def test_file_not_found(self, service):
        with pytest.raises(FileNotFoundError):
            _run(service.upload_and_parse("/nonexistent/path/to/file.txt"))