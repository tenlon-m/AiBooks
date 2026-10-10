"""模型特点识别 - 单元测试.

覆盖：已知模型精确识别、未知模型启发式推断、实测延迟叠加、任务推荐、schema 兼容。
"""
from __future__ import annotations

from src.ai.model_profiler import (
    TASK_LABELS,
    WRITING_TASKS,
    build_model_profile,
)


# ---------- 已知模型精确识别 ----------


def test_known_qwen_32b_recommends_outline():
    p = build_model_profile("Qwen/Qwen2.5-32B-Instruct")
    assert p.matched_by == "known"
    assert p.family == "通义千问"
    assert p.scale == "32B"
    assert p.recommended_tasks == ["outline"]
    assert p.recommend_as_fallback is False
    assert p.summary and "通义千问" in p.summary
    assert "大纲生成/校验" in p.advice


def test_known_qwen_14b_recommends_writing_tasks():
    p = build_model_profile("Qwen/Qwen2.5-14B-Instruct")
    assert p.matched_by == "known"
    assert p.recommended_tasks == WRITING_TASKS
    assert p.recommend_as_fallback is False


def test_known_qwen_7b_is_fallback():
    p = build_model_profile("Qwen/Qwen2.5-7B-Instruct")
    assert p.matched_by == "known"
    assert p.recommended_tasks == []
    assert p.recommend_as_fallback is True
    assert "通用兜底" in p.advice


def test_known_glm_flash_is_fallback():
    p = build_model_profile("glm-4-flash")
    assert p.matched_by == "known"
    assert p.family == "智谱GLM"
    assert p.is_lightweight is True
    assert p.recommended_tasks == []


def test_known_deepseek_chat_covers_outline_and_writing():
    p = build_model_profile("deepseek-chat")
    assert p.matched_by == "known"
    assert set(p.recommended_tasks) == {"outline", "writing"}


def test_known_deepseek_reasoner_is_reasoning():
    p = build_model_profile("deepseek-reasoner")
    assert p.is_reasoning is True
    assert p.recommended_tasks == ["outline"]


def test_known_moonshot_long_context():
    p = build_model_profile("moonshot-v1-128k")
    assert "长上下文" in p.scale
    assert p.recommended_tasks == ["outline"]


# ---------- 未知模型启发式推断 ----------


def test_unknown_flagship_by_size():
    p = build_model_profile("my-company-llm-72b")
    assert p.matched_by == "heuristic"
    assert p.family == "未知/自定义"
    assert p.scale == "72B"
    assert p.recommended_tasks == ["outline"]
    assert "参数量大" in p.summary


def test_unknown_mid_size_by_size():
    p = build_model_profile("some-model-20b-instruct")
    assert p.matched_by == "heuristic"
    assert p.recommended_tasks == WRITING_TASKS


def test_unknown_small_is_fallback():
    p = build_model_profile("tiny-llm-3b")
    assert p.matched_by == "heuristic"
    assert p.is_lightweight is True
    assert p.recommended_tasks == []
    assert p.recommend_as_fallback is True


def test_unknown_lightweight_keyword():
    p = build_model_profile("vendor-super-flash")
    assert p.is_lightweight is True
    assert p.recommended_tasks == []


def test_unknown_reasoning_keyword():
    p = build_model_profile("vendor-thinking-14b")
    assert p.is_reasoning is True
    assert p.recommended_tasks == ["outline"]
    assert "推理" in p.quality


def test_unknown_flagship_keyword():
    p = build_model_profile("vendor-ultra-model")
    assert p.recommended_tasks == ["outline"]


def test_size_ignores_context_length_tokens():
    """'128k' 不应被识别为参数量级。"""
    p = build_model_profile("my-model-128k")
    # 无 B 后缀 → 无参数量级
    assert p.scale == "未知"


def test_ollama_style_name_with_colon():
    p = build_model_profile("qwen2.5:14b")
    assert p.family == "通义千问"
    assert p.scale == "14B"


def test_14b_not_matched_as_4b_lightweight():
    """词边界回归：'14b' 不应命中轻量关键词 '4b'。"""
    p = build_model_profile("some-vendor-14b-instruct")
    assert p.is_lightweight is False
    assert p.recommended_tasks == WRITING_TASKS


def test_24b_not_matched_as_4b_lightweight():
    p = build_model_profile("vendor-24b-chat")
    assert p.is_lightweight is False


def test_minimax_not_matched_as_mini():
    """词边界回归：'minimax' 不应命中轻量关键词 'mini'。"""
    p = build_model_profile("MiniMax-Text-01")
    assert p.family == "MiniMax"
    assert p.is_lightweight is False


def test_minimax_not_matched_as_max_flagship():
    """词边界回归：'minimax' 不应命中旗舰关键词 'max'。"""
    p = build_model_profile("minimax-abab6.5")
    assert p.family == "MiniMax"
    assert p.is_flagship is False
    assert p.is_lightweight is False


def test_reasoner_still_matches_loose_reasoning_keyword():
    """宽松项回归：'reasoner' 应能命中推理关键词 'reason'。"""
    p = build_model_profile("vendor-reasoner-32b")
    assert p.is_reasoning is True


def test_thinking_still_matches_loose_reasoning_keyword():
    p = build_model_profile("vendor-thinking-pro")
    assert p.is_reasoning is True


def test_positioning_text_by_type():
    assert "推理型" in build_model_profile("deepseek-reasoner").positioning
    assert "轻量快模型" in build_model_profile("glm-4-flash").positioning
    assert "大型旗舰" in build_model_profile("unknown-72b").positioning
    assert "均衡型" in build_model_profile("unknown-20b").positioning


def test_moonshot_not_matched_as_openai():
    """词边界回归：'moonshot' 不应把 'o1' 误判为 OpenAI。"""
    p = build_model_profile("moonshot-v1-8k")
    assert p.family == "月之暗面Kimi"


def test_qwen_2_5_14b_scale_is_14():
    """'2.5' 中的 5 不应被当作参数量级。"""
    p = build_model_profile("Qwen/Qwen2.5-14B-Instruct")
    assert p.scale == "14B"


# ---------- 实测延迟叠加 ----------


def test_latency_overlay_fast():
    p = build_model_profile("qwen2.5-7b", latency_ms=800)
    assert "实测响应极快" in p.speed


def test_latency_overlay_slow():
    p = build_model_profile("qwen2.5-7b", latency_ms=9000)
    assert "实测响应偏慢" in p.speed


def test_no_latency_no_overlay():
    p = build_model_profile("qwen2.5-7b")
    assert "实测" not in p.speed


# ---------- 输出结构 / schema 兼容 ----------


def test_to_dict_contains_all_fields():
    p = build_model_profile("Qwen/Qwen2.5-32B-Instruct")
    d = p.to_dict()
    for key in (
        "model_name",
        "family",
        "scale",
        "speed",
        "quality",
        "is_reasoning",
        "is_lightweight",
        "strengths",
        "recommended_tasks",
        "recommend_as_fallback",
        "summary",
        "advice",
        "matched_by",
    ):
        assert key in d, f"缺少字段 {key}"


def test_to_dict_accepts_by_schema():
    """to_dict 结果应能被 API 的 ModelProfileDto 直接校验通过。"""
    from src.api.schemas.ai_source_schema import ModelProfileDto

    for name in ("Qwen/Qwen2.5-32B-Instruct", "unknown-72b", "glm-4-flash"):
        dto = ModelProfileDto(**build_model_profile(name).to_dict())
        assert dto.model_name == name


def test_recommended_task_labels_translated():
    p = build_model_profile("Qwen/Qwen2.5-32B-Instruct")
    assert p.recommended_task_labels == [TASK_LABELS["outline"]]


def test_test_response_schema_accepts_profile():
    from src.api.schemas.ai_source_schema import AiSourceTestResponse

    resp = AiSourceTestResponse(
        source_id="sid",
        success=True,
        message="连通正常",
        latency_ms=1234,
        model_profile=build_model_profile("deepseek-chat", latency_ms=1234).to_dict(),
    )
    assert resp.model_profile is not None
    assert resp.model_profile.family == "DeepSeek"
    assert resp.latency_ms == 1234


def test_test_response_schema_backward_compatible():
    """旧客户端不传新字段也应可解析（字段可选）。"""
    from src.api.schemas.ai_source_schema import AiSourceTestResponse

    resp = AiSourceTestResponse(source_id="sid", success=False, message="boom")
    assert resp.latency_ms is None
    assert resp.model_profile is None
