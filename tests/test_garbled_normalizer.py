"""统一字符规范化机制单元测试.

覆盖 design 2.9.1 全部用例：
  - 字符乱码检测（控制字符/U+FFFD/零宽/私用区/乱码序列）
  - 格式错乱检测（连续空行/重复标点/全角缩进/连续空格/制表符/非断行空格）
  - 配置行为（enabled=False/阈值边界/不可逆标注）
  - 边界情况（空字符串/纯ASCII/超长文本/合法标点豁免）
  - detect_and_normalize 与 detect_only 判定类别一致性
"""
from __future__ import annotations

import time

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
def default_config():
    return GarbledConfig()


# ---------------------------------------------------------------------------
# 1. 字符乱码检测
# ---------------------------------------------------------------------------
class TestGarbledNormalizerDetect:
    """字符乱码检测与修复."""

    def test_control_char_removed(self, normalizer, default_config):
        text = "这是正常文本\x01带有控制字符\x02的段落内容超过五十字符以上用于测试。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "\x01" not in result
        assert "\x02" not in result
        assert stat.garbled_detected >= 2

    def test_replacement_char_cleared_no_fabrication(self, normalizer, default_config):
        text = "这段文本包含替换字符\ufffd只做清除处理不添加任何新内容超过五十字符用于测试。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "\ufffd" not in result
        assert stat.irreversible_cleared >= 1
        assert len(result) < len(text)

    def test_zero_width_char_removed(self, normalizer, default_config):
        text = "这是带有零宽字符\u200b\u200c\u200d的文本内容用于测试检测能力超过五十字。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "\u200b" not in result
        assert "\u200c" not in result
        assert "\u200d" not in result
        assert stat.garbled_detected >= 3

    def test_bom_removed(self, normalizer, default_config):
        text = "\ufeff这是带有BOM标记的文本内容用于测试检测能力超过五十字符以上。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "\ufeff" not in result
        assert stat.garbled_detected >= 1

    def test_pua_char_removed(self, normalizer, default_config):
        pua_char = chr(0xE000)
        text = f"这是带有私用区字符{pua_char}的文本内容用于测试检测能力超过五十字符以上。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert pua_char not in result
        assert stat.garbled_detected >= 1

    def test_legal_newline_preserved(self, normalizer, default_config):
        text = "第一段内容足够长超过五十字符用于测试换行保留能力。\n第二段内容也足够长超过五十字符用于测试。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "\n" in result

    def test_garbled_sequence_cleared(self, normalizer, default_config):
        seq = "\u0e01\u0e02\u0e03\u0e04"
        text = f"正常中文内容{seq}后续正常内容超过五十字符用于测试乱码序列检测。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert seq not in result


# ---------------------------------------------------------------------------
# 2. 格式错乱检测
# ---------------------------------------------------------------------------
class TestGarbledNormalizerFormat:
    """格式错乱检测与修复."""

    def test_consecutive_blank_lines_compressed(self, normalizer, default_config):
        text = "第一段内容足够长。\n\n\n\n\n第二段内容也足够长用于测试空行压缩超过五十字符。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "\n\n\n\n\n" not in result
        assert stat.format_detected >= 1

    def test_punct_repeat_compressed(self, normalizer, default_config):
        text = "这是测试文本。。。。。。。标点重复超过五十字符用于测试压缩能力是否正常工作。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "。。。。。。。" not in result

    def test_ellipsis_exempt(self, normalizer, default_config):
        text = "这是测试文本……省略号不应该被压缩……内容超过五十字符用于测试豁免能力。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "……" in result

    def test_dash_exempt(self, normalizer, default_config):
        text = "这是测试文本——破折号不应该被压缩——内容超过五十字符用于测试豁免能力。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "——" in result

    def test_fullwidth_indent_preserved(self, normalizer, default_config):
        text = "\u3000\u3000这是段首两个全角空格缩进的段落内容超过五十字符用于测试保留能力。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert result.startswith("\u3000\u3000")

    def test_consecutive_spaces_compressed(self, normalizer, default_config):
        text = "这是测试文本    含有连续空格    的内容超过五十字符用于测试压缩能力。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "    " not in result

    def test_tab_removed(self, normalizer, default_config):
        text = "这是\t带有制表符\t的文本内容用于测试检测能力超过五十字符以上确保正常。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "\t" not in result
        assert stat.garbled_detected + stat.format_detected >= 1

    def test_nbsp_replaced(self, normalizer, default_config):
        text = "这是带有\u00a0非断行空格\u00a0的文本内容用于测试替换能力超过五十字符以上。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "\u00a0" not in result


# ---------------------------------------------------------------------------
# 3. 配置行为
# ---------------------------------------------------------------------------
class TestGarbledNormalizerConfig:
    """配置开关与阈值边界."""

    def test_disabled_returns_original(self, normalizer):
        config = GarbledConfig(enabled=False)
        text = "这段文本\x01包含\ufffd乱码但配置关闭应原样返回超过五十字符用于测试。"
        result, stat = normalizer.detect_and_normalize(text, config)
        assert result == text
        assert stat.garbled_detected == 0

    def test_disabled_detect_only_returns_empty(self, normalizer):
        config = GarbledConfig(enabled=False)
        text = "这段文本\x01包含\ufffd乱码但配置关闭应返回空列表超过五十字符用于测试。"
        issues = normalizer.detect_only(text, config)
        assert issues == []

    def test_max_blank_lines_boundary(self, normalizer):
        config = GarbledConfig(max_blank_lines=3)
        text = "第一段。\n\n\n\n\n\n\n第二段内容也足够长用于测试空行边界超过五十字符以上。"
        result, stat = normalizer.detect_and_normalize(text, config)
        assert result.count("\n\n\n\n\n\n\n") == 0

    def test_max_punct_repeat_boundary(self, normalizer):
        config = GarbledConfig(max_punct_repeat=5)
        text = "测试文本。。。。。。六个句号超过五十字符用于测试边界判定能力是否正常工作。"
        result, stat = normalizer.detect_and_normalize(text, config)
        assert "。。。。。。" not in result

    def test_irreversible_flag_set(self, normalizer, default_config):
        text = "文本包含\ufffd替换字符应标注不可逆超过五十字符用于测试不可逆标注能力。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert stat.irreversible_cleared >= 1
        irreversible_details = [d for d in stat.details if d.irreversible]
        assert len(irreversible_details) >= 1

    def test_irreversible_clear_disabled(self, normalizer):
        config = GarbledConfig(enable_irreversible_clear=False)
        text = "文本包含\ufffd替换字符但清除关闭应保留超过五十字符用于测试配置能力。"
        result, stat = normalizer.detect_and_normalize(text, config)
        assert "\ufffd" in result


# ---------------------------------------------------------------------------
# 4. 边界情况
# ---------------------------------------------------------------------------
class TestGarbledNormalizerEdgeCase:
    """边界情况与合法内容不误报."""

    def test_empty_string(self, normalizer, default_config):
        result, stat = normalizer.detect_and_normalize("", default_config)
        assert result == ""
        assert stat.garbled_detected == 0

    def test_pure_ascii(self, normalizer, default_config):
        text = "This is pure ASCII text with no garbled characters at all for testing."
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert stat.garbled_detected == 0

    def test_long_text_performance(self, normalizer, default_config):
        text = "这是正常中文文本内容用于性能测试。" * 5000
        start = time.perf_counter()
        result, stat = normalizer.detect_and_normalize(text, default_config)
        elapsed = (time.perf_counter() - start) * 1000
        assert elapsed < 100, f"10万字规范化耗时{elapsed:.1f}ms应<100ms"
        assert stat.garbled_detected == 0

    def test_no_garbled_returns_original(self, normalizer, default_config):
        text = "这是一段完全正常的中文文本内容，没有任何乱码或格式问题，超过五十字符。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert result == text
        assert stat.garbled_detected == 0
        assert stat.format_detected == 0

    def test_legal_cn_punct_not_flagged(self, normalizer, default_config):
        text = "中文标点测试：句号。逗号，顿号、分号；冒号：问号？叹号！引号「」书名号《》"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert stat.garbled_detected == 0

    def test_legal_ellipsis_not_flagged(self, normalizer, default_config):
        text = "省略号测试……这是合法的省略号不应该被压缩或标记为问题超过五十字符。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert "……" in result

    def test_fullwidth_indent_two_preserved(self, normalizer, default_config):
        text = "\u3000\u3000段首两个全角空格缩进是标准格式应予保留超过五十字符用于测试。"
        result, stat = normalizer.detect_and_normalize(text, default_config)
        assert result.startswith("\u3000\u3000")

    def test_detect_and_detect_only_consistent(self, normalizer, default_config):
        text = "文本\x01包含\ufffd乱码。。。。。格式问题超过五十字符用于测试一致性。"
        _, stat = normalizer.detect_and_normalize(text, default_config)
        issues = normalizer.detect_only(text, default_config)
        normalize_categories = set(stat.hit_categories)
        detect_categories = {i.category for i in issues}
        assert normalize_categories == detect_categories

    def test_non_string_input_returns_original(self, normalizer, default_config):
        result, stat = normalizer.detect_and_normalize(None, default_config)
        assert result is None
        assert stat.garbled_detected == 0