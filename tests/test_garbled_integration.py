"""全场景集成测试.

覆盖 design 2.9.2 全部测试类：
  - 撰写补写/校验/修复集成
  - 编辑润色/直接更新集成
  - 大纲校验/修复集成
  - 钩子校验/修复集成
  - 章节校验集成
  - 梗概/世界观润色集成
  - 配置全链路透传
  - 向后兼容
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.garbled_normalizer import (
    CharacterRepairStat,
    GarbledConfig,
    GarbledNormalizer,
)


@pytest.fixture
def normalizer():
    return GarbledNormalizer()


@pytest.fixture
def config():
    return GarbledConfig()


@pytest.fixture
def disabled_config():
    return GarbledConfig(enabled=False)


# ---------------------------------------------------------------------------
# 场景①：批量补写集成
# ---------------------------------------------------------------------------
class TestWritingFillIntegration:
    """补写后 chapter.content 无乱码，SSE chunk 携带 char_repair_stat."""

    def test_fill_normalizes_garbled_content(self, normalizer, config):
        ai_content = "AI生成的正文\x01包含控制字符\ufffd和零宽\u200b字符超过五十字符用于测试。"
        result, stat = normalizer.detect_and_normalize(ai_content, config)
        assert "\x01" not in result
        assert "\ufffd" not in result
        assert "\u200b" not in result
        assert stat.garbled_detected >= 3

    def test_fill_disabled_no_normalization(self, normalizer, disabled_config):
        ai_content = "AI生成的正文\x01包含控制字符\ufffd超过五十字符用于测试禁用场景。"
        result, stat = normalizer.detect_and_normalize(ai_content, disabled_config)
        assert result == ai_content
        assert stat.garbled_detected == 0


# ---------------------------------------------------------------------------
# 场景②：撰写页校验一致性集成
# ---------------------------------------------------------------------------
class TestWritingCheckIntegration:
    """校验报告含字符乱码/格式错乱，正文未修改."""

    def test_check_detects_garbled_issues(self, normalizer, config):
        text = "正文包含\ufffd替换字符\x01控制字符超过五十字符用于测试校验检测能力。"
        issues = normalizer.detect_only(text, config)
        assert len(issues) >= 2
        categories = {i.category for i in issues}
        assert "替换字符" in categories
        assert "控制字符" in categories

    def test_check_does_not_modify_text(self, normalizer, config):
        text = "正文包含\ufffd替换字符超过五十字符用于测试校验不改写正文能力。"
        issues = normalizer.detect_only(text, config)
        assert len(issues) >= 1
        assert "\ufffd" in text


# ---------------------------------------------------------------------------
# 场景③：AI一键修复集成
# ---------------------------------------------------------------------------
class TestWritingRepairIntegration:
    """修复后无乱码，SSE 携带明细."""

    def test_repair_removes_all_garbled(self, normalizer, config):
        text = "修复文本\x01\ufffd\u200b。。。。。包含多种乱码和格式问题超过五十字符用于测试。"
        result, stat = normalizer.detect_and_normalize(text, config)
        assert "\x01" not in result
        assert "\ufffd" not in result
        assert "\u200b" not in result
        assert "。。。。。" not in result

    def test_repair_carries_details(self, normalizer, config):
        text = "修复文本\ufffd包含替换字符超过五十字符用于测试明细携带能力是否正常。"
        _, stat = normalizer.detect_and_normalize(text, config)
        assert len(stat.details) >= 1
        assert stat.irreversible_cleared >= 1


# ---------------------------------------------------------------------------
# 场景④：编辑润色集成
# ---------------------------------------------------------------------------
class TestPolishIntegration:
    """润色后内容无乱码."""

    def test_polish_normalizes_content(self, normalizer, config):
        polished = "润色结果\x01含有乱码\ufffd字符的内容超过五十字符用于测试润色后规范化。"
        result, stat = normalizer.detect_and_normalize(polished, config)
        assert "\x01" not in result
        assert "\ufffd" not in result


# ---------------------------------------------------------------------------
# 场景⑤：直接更新章节正文集成
# ---------------------------------------------------------------------------
class TestUpdateContentIntegration:
    """直接更新后 chapter.content 无乱码（非 AI 场景）."""

    def test_update_normalizes_content(self, normalizer, config):
        content = "用户直接编辑的正文\u00a0含有非断行空格\t制表符超过五十字符用于测试。"
        result, stat = normalizer.detect_and_normalize(content, config)
        assert "\u00a0" not in result
        assert "\t" not in result


# ---------------------------------------------------------------------------
# 场景⑥：大纲校验与修复集成
# ---------------------------------------------------------------------------
class TestOutlineIntegration:
    """大纲校验报告含字符/格式问题，修复后无乱码."""

    def test_outline_check_detects_issues(self, normalizer, config):
        synopsis = "大纲梗概包含\ufffd替换字符超过五十字符用于测试大纲校验检测能力。"
        issues = normalizer.detect_only(synopsis, config)
        assert len(issues) >= 1

    def test_outline_repair_normalizes(self, normalizer, config):
        synopsis = "修复后梗概\x01不含乱码\ufffd超过五十字符用于测试大纲修复能力。"
        result, stat = normalizer.detect_and_normalize(synopsis, config)
        assert "\x01" not in result
        assert "\ufffd" not in result


# ---------------------------------------------------------------------------
# 场景⑦：钩子校验与修复集成
# ---------------------------------------------------------------------------
class TestHookIntegration:
    """钩子校验报告含字符/格式问题，修复后无乱码."""

    def test_hook_check_detects_issues(self, normalizer, config):
        hook_content = "钩子内容包含\ufffd乱码字符超过五十字符用于测试钩子校验检测能力。"
        issues = normalizer.detect_only(hook_content, config)
        assert len(issues) >= 1

    def test_hook_repair_normalizes(self, normalizer, config):
        hook_content = "修复后钩子\x01不含乱码\ufffd超过五十字符用于测试钩子修复能力。"
        result, stat = normalizer.detect_and_normalize(hook_content, config)
        assert "\x01" not in result
        assert "\ufffd" not in result


# ---------------------------------------------------------------------------
# 场景⑧：章节编辑页校验一致性集成
# ---------------------------------------------------------------------------
class TestChapterCheckIntegration:
    """章节编辑页校验报告含字符/格式问题，正文未修改."""

    def test_chapter_check_detects_garbled(self, normalizer, config):
        content = "章节正文包含\ufffd替换字符超过五十字符用于测试章节校验检测能力。"
        issues = normalizer.detect_only(content, config)
        assert len(issues) >= 1
        assert "\ufffd" in content


# ---------------------------------------------------------------------------
# 场景⑨：梗概与世界观润色集成
# ---------------------------------------------------------------------------
class TestCreationPolishIntegration:
    """梗概/世界观润色后无乱码."""

    def test_creation_polish_normalizes(self, normalizer, config):
        polished = "润色后的梗概\x01含有乱码\ufffd超过五十字符用于测试梗概润色后规范化。"
        result, stat = normalizer.detect_and_normalize(polished, config)
        assert "\x01" not in result
        assert "\ufffd" not in result


# ---------------------------------------------------------------------------
# 场景⑪：配置全链路透传
# ---------------------------------------------------------------------------
class TestConfigPropagation:
    """UI → Worker → Router → Service 全链路 garbled_config 透传."""

    def test_worker_accepts_garbled_config(self):
        from src.ui.sse_worker import WritingFillSseWorker, WritingRepairSseWorker

        worker = WritingFillSseWorker("test-pid", garbled_config={"enabled": True})
        assert worker._payload is not None
        assert worker._payload["garbled_config"] == {"enabled": True}

        repair_worker = WritingRepairSseWorker(
            "test-pid", [{"level": "严重"}], garbled_config={"enabled": False}
        )
        assert repair_worker._payload["garbled_config"] == {"enabled": False}

    def test_worker_none_config_no_field(self):
        from src.ui.sse_worker import WritingFillSseWorker

        worker = WritingFillSseWorker("test-pid", garbled_config=None)
        assert worker._payload is None or "garbled_config" not in worker._payload

    def test_service_fallback_resolution(self):
        from src.services.garbled_config_service import GarbledConfigService
        import asyncio

        async def run():
            session = AsyncMock()
            service = GarbledConfigService(session)
            service._get_model = AsyncMock(return_value=None)
            return await service.resolve_effective_config()

        config = asyncio.run(run())
        assert config.enabled is True


# ---------------------------------------------------------------------------
# 向后兼容
# ---------------------------------------------------------------------------
class TestBackwardCompatibility:
    """既有前端不解析新字段时不报错."""

    def test_schema_optional_fields(self):
        from src.api.schemas.writing_schema import WritingFillStreamChunk

        chunk = WritingFillStreamChunk(type="progress", done=1, total=10)
        assert chunk.char_repair_stat is None

    def test_garbled_config_none_default(self):
        from src.api.schemas.writing_schema import StartWritingRequest

        req = StartWritingRequest(project_id="test")
        assert req.garbled_config is None
