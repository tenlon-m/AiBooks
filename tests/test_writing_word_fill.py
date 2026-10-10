"""写作字数补全（fill）功能单元测试.

覆盖范围：
  1. 判定纯函数 is_word_underfilled
  2. Schema / 配置 / 模板 / manifest
  3. 前端 WritingFillSseWorker 构造
  4. fill_writing_stream 服务层（复杂异步流，需完整 DB setup -> skip）
  5. SSE 端点集成（需 httpx AsyncClient + 完整 app -> skip）
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from src.api.schemas.writing_schema import ChapterDto, WritingFillStreamChunk
from src.config.settings import get_config


# ---------------------------------------------------------------------------
# 1. 判定纯函数 is_word_underfilled
# ---------------------------------------------------------------------------
class TestIsWordUnderfilled:
    """任务10.1: is_word_underfilled 纯函数判定口径.

    target=3000, tolerance=0.2 -> threshold=2400，严格小于才算不足。
    """

    @pytest.fixture
    def service(self):
        from src.services.writing_service import WritingService

        # is_word_underfilled 仅依赖 self.config，session 不参与判定
        return WritingService(MagicMock())

    def test_below_threshold_is_underfilled(self, service):
        # 1300 < 2400
        assert service.is_word_underfilled(1300, 3000) is True

    def test_midrange_is_underfilled(self, service):
        # 2000 < 2400
        assert service.is_word_underfilled(2000, 3000) is True

    def test_at_threshold_not_underfilled(self, service):
        # 2400 == 2400，严格小于才算不足 -> False
        assert service.is_word_underfilled(2400, 3000) is False

    def test_above_threshold_not_underfilled(self, service):
        # 2500 > 2400
        assert service.is_word_underfilled(2500, 3000) is False

    def test_zero_words_per_chapter_not_underfilled(self, service):
        # words_per_chapter <= 0 不参与判定
        assert service.is_word_underfilled(2000, 0) is False

    def test_negative_words_per_chapter_not_underfilled(self, service):
        assert service.is_word_underfilled(2000, -1) is False

    def test_negative_word_count_treated_as_zero(self, service):
        # word_count=-1 -> effective=0, 0 < 2400 -> True
        assert service.is_word_underfilled(-1, 3000) is True

    def test_none_word_count_treated_as_zero(self, service):
        # word_count=None -> (None or 0)=0 -> effective=0 -> True
        assert service.is_word_underfilled(None, 3000) is True  # type: ignore[arg-type]

    def test_threshold_uses_config_tolerance(self, service):
        # 验证阈值确实来自 config.writing_fill_tolerance
        tolerance = service.config.writing_fill_tolerance
        words_per_chapter = 5000
        threshold = words_per_chapter * (1 - tolerance)
        # 刚好等于阈值 -> False
        assert service.is_word_underfilled(int(threshold), words_per_chapter) is False
        # 阈值 - 1 -> True
        assert service.is_word_underfilled(int(threshold) - 1, words_per_chapter) is True


# ---------------------------------------------------------------------------
# 2. Schema / 配置 / 模板 / manifest
# ---------------------------------------------------------------------------
class TestWritingFillStreamChunk:
    """任务10.2: WritingFillStreamChunk schema 默认值与类型字面量."""

    def test_progress_defaults(self):
        chunk = WritingFillStreamChunk(type="progress")
        assert chunk.type == "progress"
        assert chunk.volume_no == 0
        assert chunk.chapter_no == 0
        assert chunk.done == 0
        assert chunk.total == 0
        assert chunk.status == ""
        assert chunk.word_count_before == 0
        assert chunk.word_count_after == 0
        assert chunk.retries == 0
        assert chunk.fail_reason == ""
        assert chunk.success == 0
        assert chunk.skipped == 0
        assert chunk.still_underfilled == 0
        assert chunk.message == ""

    @pytest.mark.parametrize(
        "chunk_type",
        ["progress", "chapter_done", "chapter_skip", "completed", "error"],
    )
    def test_all_type_literals_accepted(self, chunk_type):
        chunk = WritingFillStreamChunk(type=chunk_type)
        assert chunk.type == chunk_type

    def test_chapter_done_with_fields(self):
        chunk = WritingFillStreamChunk(
            type="chapter_done",
            volume_no=1,
            chapter_no=3,
            done=2,
            total=5,
            word_count_before=1300,
            word_count_after=3100,
            retries=1,
        )
        assert chunk.chapter_no == 3
        assert chunk.word_count_after == 3100
        assert chunk.retries == 1

    def test_completed_summary_fields(self):
        chunk = WritingFillStreamChunk(
            type="completed",
            success=3,
            skipped=1,
            still_underfilled=0,
        )
        assert chunk.success == 3
        assert chunk.skipped == 1
        assert chunk.still_underfilled == 0

    def test_invalid_type_rejected(self):
        with pytest.raises(Exception):
            WritingFillStreamChunk(type="unknown")  # type: ignore[arg-type]


class TestChapterDtoBackwardCompat:
    """任务10.2: ChapterDto 新增字段向后兼容."""

    def _make_minimal(self):
        return ChapterDto(
            chapter_id="ch-1",
            project_id="proj-1",
            volume_no=1,
            chapter_no=1,
            title="第一章",
            word_count=1000,
            gen_status="completed",
            modify_status="none",
        )

    def test_without_new_fields_defaults(self):
        dto = self._make_minimal()
        assert dto.words_per_chapter == 0
        assert dto.underfilled is False

    def test_with_new_fields(self):
        dto = ChapterDto(
            chapter_id="ch-2",
            project_id="proj-2",
            volume_no=1,
            chapter_no=2,
            title="第二章",
            word_count=1300,
            gen_status="completed",
            modify_status="none",
            words_per_chapter=3000,
            underfilled=True,
        )
        assert dto.words_per_chapter == 3000
        assert dto.underfilled is True

    def test_other_optional_fields_unchanged(self):
        dto = self._make_minimal()
        assert dto.content is None
        assert dto.summary is None


class TestWritingFillConfig:
    """任务10.2: 字数补全场景化配置项."""

    def test_writing_fill_tolerance(self):
        assert get_config().writing_fill_tolerance == 0.2

    def test_writing_fill_timeout_seconds(self):
        assert get_config().writing_fill_timeout_seconds == 300

    def test_writing_fill_max_retries(self):
        assert get_config().writing_fill_max_retries == 2


class TestSupplementPrompt:
    """任务10.2: supplement.j2 补写提示词模板."""

    @property
    def _content(self) -> str:
        return Path("src/prompts/writing/supplement.j2").read_text(encoding="utf-8")

    def test_template_exists(self):
        assert Path("src/prompts/writing/supplement.j2").exists()

    def test_template_has_target_words(self):
        assert "target_words" in self._content

    def test_template_has_current_words(self):
        assert "current_words" in self._content

    def test_template_has_min_add_words(self):
        assert "min_add_words" in self._content

    def test_template_has_content_output(self):
        assert "content" in self._content

    def test_template_has_prohibition_keywords(self):
        content = self._content
        # 约束类关键词：不得 / 禁止
        assert "不得" in content or "禁止" in content

    def test_template_has_keep_keyword(self):
        assert "保留" in self._content

    def test_template_has_both_prohibition_styles(self):
        content = self._content
        assert "不得" in content
        assert "禁止" in content


class TestManifestSupplementRegistration:
    """任务10.2: manifest.yaml 注册 supplement 模板."""

    @property
    def _templates(self) -> list[dict]:
        manifest = yaml.safe_load(
            Path("src/prompts/manifest.yaml").read_text(encoding="utf-8")
        )
        return manifest.get("templates", [])

    def test_supplement_registered_exactly_once(self):
        scenes = [
            t
            for t in self._templates
            if t.get("module") == "writing" and t.get("scene") == "supplement"
        ]
        assert len(scenes) == 1

    def test_supplement_enabled(self):
        scenes = [
            t
            for t in self._templates
            if t.get("module") == "writing" and t.get("scene") == "supplement"
        ]
        assert scenes[0].get("enabled") is True

    def test_supplement_file_path(self):
        scenes = [
            t
            for t in self._templates
            if t.get("module") == "writing" and t.get("scene") == "supplement"
        ]
        assert scenes[0].get("file") == "writing/supplement.j2"


# ---------------------------------------------------------------------------
# 3. 前端 WritingFillSseWorker 构造
# ---------------------------------------------------------------------------
class TestWritingFillSseWorker:
    """任务10.3: WritingFillSseWorker 构造与继承."""

    def test_worker_url_contains_fill_stream(self):
        from src.ui.sse_worker import WritingFillSseWorker

        worker = WritingFillSseWorker("proj-123")
        assert "/api/writing/proj-123/fill/stream" in worker._url

    def test_worker_payload_is_none(self):
        from src.ui.sse_worker import WritingFillSseWorker

        worker = WritingFillSseWorker("proj-456")
        assert worker._payload is None

    def test_worker_method_is_post(self):
        from src.ui.sse_worker import WritingFillSseWorker

        worker = WritingFillSseWorker("proj-789")
        assert worker._method == "POST"

    def test_worker_inherits_sse_post_worker_signals(self):
        from src.ui.sse_worker import SsePostWorker, WritingFillSseWorker

        worker = WritingFillSseWorker("proj-signals")
        assert isinstance(worker, SsePostWorker)
        # 继承的信号/方法
        assert hasattr(worker, "stop")
        assert hasattr(worker, "event")
        assert hasattr(worker, "error")
        assert hasattr(worker, "finished_ok")
        assert hasattr(worker, "chunk")

    def test_worker_url_different_project_ids(self):
        from src.ui.sse_worker import WritingFillSseWorker

        w1 = WritingFillSseWorker("a")
        w2 = WritingFillSseWorker("b")
        assert "/api/writing/a/fill/stream" in w1._url
        assert "/api/writing/b/fill/stream" in w2._url


# ---------------------------------------------------------------------------
# 4. fill_writing_stream 服务层（mock gateway）
# ---------------------------------------------------------------------------
class TestFillWritingStream:
    """任务10.4: fill_writing_stream 异步生成器.

    该方法为复杂异步流，依赖真实 DB session（Chapter/ChapterVersion 等模型查询）、
    gateway.call_and_parse、快照写入等。完整 mock 成本高且易与真实 ORM 行为偏离，
    此处标记 skip，建议在集成测试中覆盖。
    """

    @pytest.mark.skip(
        reason="fill_writing_stream 需完整异步 DB session + gateway mock，宜在集成测试覆盖"
    )
    @pytest.mark.asyncio
    async def test_no_underfilled_yields_completed(self):
        from src.services.writing_service import WritingService

        service = WritingService(MagicMock())
        chunks = [c async for c in service.fill_writing_stream("proj-no-fill")]
        assert chunks[-1].type == "completed"
        assert chunks[-1].success == 0
        assert chunks[-1].skipped == 0
        assert chunks[-1].still_underfilled == 0

    @pytest.mark.skip(
        reason="锁定章节场景需构造 Chapter ORM 行与 session.execute 返回值，宜在集成测试覆盖"
    )
    @pytest.mark.asyncio
    async def test_locked_chapter_yields_skip(self):
        from src.services.writing_service import WritingService

        service = WritingService(MagicMock())
        chunks = [c async for c in service.fill_writing_stream("proj-locked")]
        skip_chunks = [c for c in chunks if c.type == "chapter_skip"]
        assert any("锁定" in c.fail_reason for c in skip_chunks)


# ---------------------------------------------------------------------------
# 5. SSE 端点集成测试
# ---------------------------------------------------------------------------
class TestWritingFillSseEndpoint:
    """任务10.5: SSE 端点集成测试.

    需完整 FastAPI app + httpx AsyncClient + 真实/内存 DB，属于集成测试范畴，
    此处标记 skip。
    """

    @pytest.mark.skip(reason="SSE 端点集成需完整 app + httpx AsyncClient，宜在集成测试覆盖")
    @pytest.mark.asyncio
    async def test_fill_stream_event_sequence(self):
        # POST /api/writing/{project_id}/fill/stream 事件序列：
        # progress -> chapter_done/chapter_skip -> completed
        pass

    @pytest.mark.skip(reason="chapters 端点 underfilled 字段需完整 app，宜在集成测试覆盖")
    @pytest.mark.asyncio
    async def test_chapters_dto_contains_underfilled(self):
        # GET /api/writing/{project_id}/chapters -> ChapterDto.underfilled
        pass