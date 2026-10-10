"""降AI率改写服务单元测试."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.schemas.anti_ai_schema import AntiAiRewriteDto
from src.api.schemas.writing_schema import ChapterDto


_LONG_CONTENT = (
    "林远站在山崖边缘，寒风猎猎作响，吹得他衣袍翻飞。"
    "他望着远处云海翻涌，心中百感交集。三年苦修，今日终于突破筑基，"
    "踏入金丹大道。身后传来轻盈的脚步声，是师妹苏瑶来了。"
    "她手里端着一碗热汤，脸上带着浅浅的笑意。"
)

_SHORT_CONTENT = "改写太短了"

_REWRITTEN_CONTENT = (
    "林远立在悬崖边上，风很大，呼呼地刮着，把他衣服吹得哗啦啦响。"
    "他看着远处的云海翻来翻去，心里头五味杂陈。苦练了整整三年，"
    "今天总算突破了筑基期，迈进了金丹的门槛。后面响起一阵轻巧的脚步声，"
    "是师妹苏瑶走过来了。她手上端着一碗热乎乎的汤，脸上挂着淡淡的笑。"
)


def _make_chapter(content: str = _LONG_CONTENT) -> MagicMock:
    chapter = MagicMock()
    chapter.chapter_id = "ch-001"
    chapter.project_id = "proj-001"
    chapter.volume_no = 1
    chapter.chapter_no = 1
    chapter.title = "第一章 突破"
    chapter.content = content
    chapter.word_count = len(content)
    chapter.gen_status = "completed"
    chapter.modify_status = "none"
    chapter.last_modified_at = datetime.now(timezone.utc)
    return chapter


def _make_record(
    rewrite_id: str = "rw-001",
    chapter_id: str = "ch-001",
    rewritten_content: str = _REWRITTEN_CONTENT,
    strategy: str = "全部",
    adopt_status: str = "待采纳",
    original_version_id: str = "ver-001",
) -> MagicMock:
    record = MagicMock()
    record.rewrite_id = rewrite_id
    record.chapter_id = chapter_id
    record.original_version_id = original_version_id
    record.rewritten_content = rewritten_content
    record.strategy = strategy
    record.adopt_status = adopt_status
    record.created_at = datetime.now(timezone.utc)
    return record


def _make_version(
    version_id: str = "ver-001",
    content: str = _LONG_CONTENT,
) -> MagicMock:
    version = MagicMock()
    version.version_id = version_id
    version.chapter_id = "ch-001"
    version.version_type = "auto"
    version.name = None
    version.content = content
    version.word_count = len(content)
    version.created_at = datetime.now(timezone.utc)
    return version


class TestAntiAiRewrite:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_rewrite_differs_from_original(self, mock_session):
        chapter = _make_chapter()
        mock_session.get = AsyncMock(return_value=chapter)

        with patch("src.services.anti_ai_service.get_gateway") as mock_gw, \
             patch("src.services.anti_ai_service.release_write_lock", new_callable=AsyncMock), \
             patch("src.services._chapter_guard.create_auto_version_snapshot", new_callable=AsyncMock, return_value=_make_version()):
            mock_gw_instance = MagicMock()
            mock_gw_instance.call = AsyncMock(
                return_value={"content": _REWRITTEN_CONTENT}
            )
            mock_gw.return_value = mock_gw_instance

            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            result = await service.rewrite_chapter("ch-001", "全部")

            assert isinstance(result, AntiAiRewriteDto)
            assert result.chapter_id == "ch-001"
            assert result.strategy == "全部"
            assert result.adopt_status == "待采纳"
            assert result.rewritten_content == _REWRITTEN_CONTENT
            assert result.rewritten_content != _LONG_CONTENT
            assert len(result.rewritten_content) >= 50

            call_args = mock_gw_instance.call.call_args
            assert call_args.kwargs["module"] == "rewrite"
            assert call_args.kwargs["scene"] == "anti-ai"
            assert call_args.kwargs["params"]["original_content"] == _LONG_CONTENT
            assert call_args.kwargs["params"]["strategy"] == "全部"
            assert "detector_features" in call_args.kwargs["params"]

    @pytest.mark.asyncio
    async def test_rewrite_retry_when_too_short(self, mock_session):
        chapter = _make_chapter()
        mock_session.get = AsyncMock(return_value=chapter)

        call_count = 0

        async def mock_call(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"content": _SHORT_CONTENT}
            return {"content": _REWRITTEN_CONTENT}

        with patch("src.services.anti_ai_service.get_gateway") as mock_gw, \
             patch("src.services.anti_ai_service.release_write_lock", new_callable=AsyncMock), \
             patch("src.services._chapter_guard.create_auto_version_snapshot", new_callable=AsyncMock, return_value=_make_version()):
            mock_gw_instance = MagicMock()
            mock_gw_instance.call = AsyncMock(side_effect=mock_call)
            mock_gw.return_value = mock_gw_instance

            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            result = await service.rewrite_chapter("ch-001", "句式变换")

            assert call_count == 2
            assert result.rewritten_content == _REWRITTEN_CONTENT
            assert len(result.rewritten_content) >= 50

    @pytest.mark.asyncio
    async def test_rewrite_still_too_short_after_retry_raises(self, mock_session):
        chapter = _make_chapter()
        mock_session.get = AsyncMock(return_value=chapter)

        with patch("src.services.anti_ai_service.get_gateway") as mock_gw, \
             patch("src.services.anti_ai_service.release_write_lock", new_callable=AsyncMock), \
             patch("src.services._chapter_guard.create_auto_version_snapshot", new_callable=AsyncMock, return_value=_make_version()):
            mock_gw_instance = MagicMock()
            mock_gw_instance.call = AsyncMock(return_value={"content": _SHORT_CONTENT})
            mock_gw.return_value = mock_gw_instance

            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            with pytest.raises(ValueError, match="改写结果过短"):
                await service.rewrite_chapter("ch-001", "全部")

    @pytest.mark.asyncio
    async def test_chapter_not_found(self, mock_session):
        mock_session.get = AsyncMock(return_value=None)

        with patch("src.services.anti_ai_service.get_gateway"):
            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            with pytest.raises(ValueError, match="章节不存在"):
                await service.rewrite_chapter("nonexistent", "全部")

    @pytest.mark.asyncio
    async def test_empty_chapter_content(self, mock_session):
        chapter = _make_chapter(content="")
        mock_session.get = AsyncMock(return_value=chapter)

        with patch("src.services.anti_ai_service.get_gateway"):
            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            with pytest.raises(ValueError, match="章节内容为空"):
                await service.rewrite_chapter("ch-001", "全部")

    @pytest.mark.asyncio
    async def test_invalid_strategy(self, mock_session):
        chapter = _make_chapter()
        mock_session.get = AsyncMock(return_value=chapter)

        with patch("src.services.anti_ai_service.get_gateway"):
            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            with pytest.raises(ValueError, match="不支持的策略"):
                await service.rewrite_chapter("ch-001", "无效策略")


class TestAdoptRewrite:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_adopt_updates_chapter_content(self, mock_session):
        chapter = _make_chapter()
        record = _make_record(adopt_status="待采纳")

        async def mock_get(model, oid):
            if model.__name__ == "AntiAiRewriteRecord":
                return record
            if model.__name__ == "Chapter":
                return chapter
            return None

        mock_session.get = AsyncMock(side_effect=mock_get)

        with patch("src.services.anti_ai_service.get_gateway"), \
             patch("src.services._chapter_guard.create_auto_version_snapshot", new_callable=AsyncMock, return_value=None):
            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            result = await service.adopt_rewrite("rw-001")

            assert isinstance(result, ChapterDto)
            assert result.chapter_id == "ch-001"
            assert result.content == _REWRITTEN_CONTENT
            assert chapter.content == _REWRITTEN_CONTENT
            assert chapter.word_count == len(_REWRITTEN_CONTENT)
            assert chapter.modify_status == "modified"
            assert record.adopt_status == "已采纳"

    @pytest.mark.asyncio
    async def test_adopt_already_adopted_raises(self, mock_session):
        record = _make_record(adopt_status="已采纳")
        mock_session.get = AsyncMock(return_value=record)

        with patch("src.services.anti_ai_service.get_gateway"):
            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            with pytest.raises(ValueError, match="已采纳"):
                await service.adopt_rewrite("rw-001")

    @pytest.mark.asyncio
    async def test_adopt_record_not_found(self, mock_session):
        mock_session.get = AsyncMock(return_value=None)

        with patch("src.services.anti_ai_service.get_gateway"):
            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            with pytest.raises(ValueError, match="改写记录不存在"):
                await service.adopt_rewrite("nonexistent")


class TestRollbackRewrite:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_rollback_restores_original(self, mock_session):
        chapter = _make_chapter(content=_REWRITTEN_CONTENT)
        record = _make_record(adopt_status="已采纳")
        original_version = _make_version(content=_LONG_CONTENT)

        async def mock_get(model, oid):
            if model.__name__ == "AntiAiRewriteRecord":
                return record
            if model.__name__ == "ChapterVersion":
                return original_version
            if model.__name__ == "Chapter":
                return chapter
            return None

        mock_session.get = AsyncMock(side_effect=mock_get)

        with patch("src.services.anti_ai_service.get_gateway"), \
             patch("src.services._chapter_guard.create_auto_version_snapshot", new_callable=AsyncMock, return_value=None):
            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            await service.rollback_rewrite("rw-001")

            assert chapter.content == _LONG_CONTENT
            assert chapter.word_count == len(_LONG_CONTENT)
            assert chapter.modify_status == "rolled_back"
            assert record.adopt_status == "已回退"

    @pytest.mark.asyncio
    async def test_rollback_not_adopted_raises(self, mock_session):
        record = _make_record(adopt_status="待采纳")
        mock_session.get = AsyncMock(return_value=record)

        with patch("src.services.anti_ai_service.get_gateway"):
            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            with pytest.raises(ValueError, match="仅已采纳"):
                await service.rollback_rewrite("rw-001")

    @pytest.mark.asyncio
    async def test_rollback_record_not_found(self, mock_session):
        mock_session.get = AsyncMock(return_value=None)

        with patch("src.services.anti_ai_service.get_gateway"):
            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            with pytest.raises(ValueError, match="改写记录不存在"):
                await service.rollback_rewrite("nonexistent")


class TestListRewrites:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_list_rewrites_returns_dtos(self, mock_session):
        record1 = _make_record(rewrite_id="rw-001")
        record2 = _make_record(rewrite_id="rw-002")

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [record1, record2]
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        mock_session.execute = AsyncMock(return_value=result_mock)

        with patch("src.services.anti_ai_service.get_gateway"):
            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            results = await service.list_rewrites("ch-001")

            assert len(results) == 2
            assert all(isinstance(r, AntiAiRewriteDto) for r in results)
            assert results[0].rewrite_id == "rw-001"
            assert results[1].rewrite_id == "rw-002"

    @pytest.mark.asyncio
    async def test_list_rewrites_empty(self, mock_session):
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        mock_session.execute = AsyncMock(return_value=result_mock)

        with patch("src.services.anti_ai_service.get_gateway"):
            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            results = await service.list_rewrites("ch-001")

            assert results == []


class TestRegressionNoAntiAi:
    """回归测试：未使用降AI率改写时，章节内容与状态不受影响."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_chapter_unchanged_without_rewrite(self, mock_session):
        chapter = _make_chapter()
        original_content = chapter.content
        original_word_count = chapter.word_count
        original_modify_status = chapter.modify_status

        mock_session.get = AsyncMock(return_value=chapter)

        with patch("src.services.anti_ai_service.get_gateway") as mock_gw, \
             patch("src.services.anti_ai_service.release_write_lock", new_callable=AsyncMock), \
             patch("src.services._chapter_guard.create_auto_version_snapshot", new_callable=AsyncMock, return_value=_make_version()):
            mock_gw_instance = MagicMock()
            mock_gw_instance.call = AsyncMock(
                return_value={"content": _REWRITTEN_CONTENT}
            )
            mock_gw.return_value = mock_gw_instance

            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)
            await service.rewrite_chapter("ch-001", "全部")

            assert chapter.content == original_content
            assert chapter.word_count == original_word_count
            assert chapter.modify_status == original_modify_status

    @pytest.mark.asyncio
    async def test_adopt_then_rollback_restores_original(self, mock_session):
        chapter = _make_chapter(content=_LONG_CONTENT)
        record = _make_record(adopt_status="待采纳")
        original_version = _make_version(content=_LONG_CONTENT)

        get_call_count = 0

        async def mock_get(model, oid):
            nonlocal get_call_count
            if model.__name__ == "AntiAiRewriteRecord":
                return record
            if model.__name__ == "ChapterVersion":
                return original_version
            if model.__name__ == "Chapter":
                return chapter
            return None

        mock_session.get = AsyncMock(side_effect=mock_get)

        with patch("src.services.anti_ai_service.get_gateway"), \
             patch("src.services._chapter_guard.create_auto_version_snapshot", new_callable=AsyncMock, return_value=None):
            from src.services.anti_ai_service import AntiAiService
            service = AntiAiService(mock_session)

            await service.adopt_rewrite("rw-001")
            assert chapter.content == _REWRITTEN_CONTENT

            record.adopt_status = "已采纳"
            await service.rollback_rewrite("rw-001")
            assert chapter.content == _LONG_CONTENT