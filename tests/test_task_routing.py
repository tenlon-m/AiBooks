"""按任务分模型 - 单元测试.

覆盖：
- _split_tags / _join_tags 双向解析
- _parse_task_tags / _source_matches_task 任务匹配
- _select_candidates 按 scene_key 过滤
- 缺匹配源时回退全集
"""
from __future__ import annotations

from types import SimpleNamespace

from src.ai.policy_snapshot import RoutingPolicySnapshot
from src.ai.model_router import ModelRouter
from src.services.ai_source_service import AiSourceService


def _make_source(
    source_id: str,
    name: str,
    priority: int = 1,
    enabled: bool = True,
    tags: str = "",
    health_status: str = "healthy",
) -> SimpleNamespace:
    """构造一个最小可用的 AiSource 替身（dataclass-like）."""
    return SimpleNamespace(
        source_id=source_id,
        name=name,
        source_type="online_openai_compatible",
        api_endpoint="https://api.example.com/v1",
        model_name="x",
        api_key_enc=None,
        timeout_seconds=60,
        max_retries=3,
        priority=priority,
        weight=1,
        enabled=enabled,
        tags=tags,
        health_status=health_status,
        last_check_at=None,
        success_count=0,
        fail_count=0,
        circuit_broken_until=None,
    )


def _make_router(strategy: str = "failover") -> ModelRouter:
    """构造一个不依赖数据库的 ModelRouter（用 None 占位 HealthChecker）。"""
    policy = RoutingPolicySnapshot(strategy=strategy)
    return ModelRouter(policy, health_checker=SimpleNamespace(
        is_available=lambda s: s.health_status in ("healthy", "degraded", "unknown")
        and getattr(s, "enabled", True)
        and not getattr(s, "_circuit", False),
        get_weight=lambda s: s.weight,
    ))


# ---------- AiSourceService._split_tags / _join_tags ----------


def test_split_tags_no_task_tags():
    display, task = AiSourceService._split_tags("免费,中文,通义千问")
    assert display == ["免费", "中文", "通义千问"]
    assert task == []


def test_split_tags_with_task_tags():
    display, task = AiSourceService._split_tags("免费,中文,task:outline,task:writing")
    assert display == ["免费", "中文"]
    assert sorted(task) == ["outline", "writing"]


def test_split_tags_empty():
    display, task = AiSourceService._split_tags("")
    assert display == []
    assert task == []


def test_split_tags_dedup():
    display, task = AiSourceService._split_tags(
        "免费,免费,中文,task:outline,task:outline"
    )
    assert display == ["免费", "中文"]
    assert task == ["outline"]


def test_join_tags_roundtrip():
    raw = AiSourceService._join_tags(["免费", "中文"], ["outline", "writing"])
    # 顺序稳定：display 在前，task 在后
    assert raw == "免费,中文,task:outline,task:writing"
    display, task = AiSourceService._split_tags(raw)
    assert display == ["免费", "中文"]
    assert sorted(task) == ["outline", "writing"]


def test_join_tags_strips_nested_prefix():
    # 防御：传入 "task:outline" 也应归一化为 "outline"
    raw = AiSourceService._join_tags([], ["task:outline", "writing"])
    assert raw == "task:outline,task:writing"


# ---------- ModelRouter._parse_task_tags / _source_matches_task ----------


def test_source_matches_task_universal():
    """无 task:* 标签 = 通用兜底，匹配任意任务."""
    s = _make_source("a", "通用", tags="免费,中文")
    assert ModelRouter._source_matches_task(s, "outline") is True
    assert ModelRouter._source_matches_task(s, "writing") is True
    assert ModelRouter._source_matches_task(s, None) is True


def test_source_matches_task_specific():
    """有 task:outline 的源应只匹配 outline，不匹配 writing."""
    s = _make_source("a", "大纲专用", tags="免费,task:outline")
    assert ModelRouter._source_matches_task(s, "outline") is True
    assert ModelRouter._source_matches_task(s, "writing") is False
    assert ModelRouter._source_matches_task(s, None) is True


def test_source_matches_task_multi():
    """task:outline,task:writing 匹配两者，不匹配 character."""
    s = _make_source("a", "双任务", tags="task:outline,task:writing")
    assert ModelRouter._source_matches_task(s, "outline") is True
    assert ModelRouter._source_matches_task(s, "writing") is True
    assert ModelRouter._source_matches_task(s, "character") is False


# ---------- ModelRouter._select_candidates 端到端 ----------


def test_select_candidates_filters_by_scene_key():
    """failover + scene_key=outline 时只挑选含 task:outline 的源 + 通用源."""
    src_outline_only = _make_source("o1", "32B-outline", priority=1, tags="task:outline")
    src_writing_only = _make_source("w1", "14B-writing", priority=2, tags="task:writing")
    src_universal = _make_source("u1", "7B-通用", priority=3, tags="免费")  # 无 task:*
    src_character_only = _make_source("c1", "GLM-character", priority=99, tags="task:character")
    sources = [src_outline_only, src_writing_only, src_universal, src_character_only]

    router = _make_router(strategy="failover")
    candidates = router._select_candidates(sources, scene_key="outline.generate-outline-batch")

    ids = [c.source_id for c in candidates]
    # 应包含：32B-outline（专属）+ 7B-通用（兜底）
    # 应排除：14B-writing（仅 writing）、GLM-character（仅 character）
    assert "o1" in ids
    assert "u1" in ids
    assert "w1" not in ids
    assert "c1" not in ids


def test_select_candidates_fallback_when_no_match():
    """scene_key 对应任务无任何专属源时，回退到全集（避免无可用源）."""
    src_a = _make_source("a", "A", priority=1, tags="task:character")
    src_b = _make_source("b", "B", priority=2, tags="task:writing")
    sources = [src_a, src_b]

    router = _make_router(strategy="failover")
    candidates = router._select_candidates(sources, scene_key="outline.generate-outline-batch")

    # 回退后两者都在
    ids = [c.source_id for c in candidates]
    assert sorted(ids) == ["a", "b"]


def test_select_candidates_no_scene_key_legacy_behavior():
    """向后兼容：不传 scene_key 时行为不变（全部健康源都参与策略）."""
    src_a = _make_source("a", "A", priority=2, tags="task:outline")
    src_b = _make_source("b", "B", priority=1, tags="task:writing")
    sources = [src_a, src_b]

    router = _make_router(strategy="failover")
    candidates = router._select_candidates(sources)  # 无 scene_key
    # failover 按 priority 排序
    assert [c.source_id for c in candidates] == ["b", "a"]


def test_select_candidates_excludes_disabled():
    """disabled 源不应出现在候选中（健康检查层就排除）."""
    src_a = _make_source("a", "A", priority=1, enabled=False, tags="task:outline")
    src_b = _make_source("b", "B", priority=2, tags="免费")
    sources = [src_a, src_b]

    router = _make_router(strategy="failover")
    candidates = router._select_candidates(sources, scene_key="outline.generate-outline")
    ids = [c.source_id for c in candidates]
    assert "a" not in ids
    assert "b" in ids