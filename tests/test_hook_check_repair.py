"""爽点钩子校验修复增强功能单元测试."""
from __future__ import annotations

import pytest

from src.api.schemas.hook_schema import (
    AiDesignHooksResponse,
    CoolPointDto,
    HookConsistencyIssue,
    HookDto,
    HookRepairRequest,
    HookRepairStreamChunk,
)
from src.services.hook_service import HookService


class TestSchemaBasics:
    """组1.2: Schema 基础验证."""

    def test_hook_repair_request_defaults(self):
        req = HookRepairRequest(issues=[])
        assert req.repair_scope == "all"

    def test_hook_repair_request_with_scope(self):
        issue = HookConsistencyIssue(level="严重", volume_no=1, chapter_no=1, type="回收顺序错误", detail="x", suggestion="y")
        req = HookRepairRequest(issues=[issue], repair_scope="severe")
        assert req.repair_scope == "severe"
        assert len(req.issues) == 1

    def test_hook_repair_stream_chunk_minimal(self):
        chunk = HookRepairStreamChunk(type="progress")
        assert chunk.type == "progress"
        assert chunk.volume_no is None
        assert chunk.success is None

    def test_hook_repair_stream_chunk_chapter_done(self):
        chunk = HookRepairStreamChunk(
            type="chapter_done",
            volume_no=1,
            chapter_no=3,
            cool_points_new=[{"type": "爽点", "content": "测试"}],
            hooks_new=[{"content": "钩子", "recycle_volume_no": 1, "recycle_chapter_no": 5}],
            auto_fixed=True,
        )
        assert chunk.volume_no == 1
        assert chunk.auto_fixed is True

    def test_ai_design_response_backfill_fields(self):
        resp = AiDesignHooksResponse(cool_points=[], hooks=[])
        assert resp.missing_chapters == []
        assert resp.failed_chapters == []

    def test_ai_design_response_with_backfill(self):
        resp = AiDesignHooksResponse(
            cool_points=[], hooks=[],
            missing_chapters=[[1, 3], [2, 1]],
            failed_chapters=[[1, 5]],
        )
        assert len(resp.missing_chapters) == 2
        assert len(resp.failed_chapters) == 1


class TestFixRecycleOrder:
    """组2.1: _fix_recycle_order 回收顺序修正."""

    def test_correct_order_no_fix(self):
        hook = HookDto(volume_no=1, chapter_no=3, hook_content="x", recycle_volume_no=1, recycle_chapter_no=5)
        fixed, was_fixed = HookService._fix_recycle_order(hook, 3, 10)
        assert not was_fixed
        assert fixed.recycle_volume_no == 1
        assert fixed.recycle_chapter_no == 5

    def test_reverse_same_volume_fix_to_end(self):
        hook = HookDto(volume_no=1, chapter_no=5, hook_content="x", recycle_volume_no=1, recycle_chapter_no=3)
        fixed, was_fixed = HookService._fix_recycle_order(hook, 3, 10)
        assert was_fixed
        assert (fixed.recycle_volume_no, fixed.recycle_chapter_no) > (1, 5)

    def test_reverse_cross_volume_fix_to_next_vol(self):
        hook = HookDto(volume_no=1, chapter_no=10, hook_content="x", recycle_volume_no=1, recycle_chapter_no=5)
        fixed, was_fixed = HookService._fix_recycle_order(hook, 3, 10)
        assert was_fixed
        assert (fixed.recycle_volume_no, fixed.recycle_chapter_no) > (1, 10)

    def test_equal_order_treated_as_reverse(self):
        hook = HookDto(volume_no=1, chapter_no=5, hook_content="x", recycle_volume_no=1, recycle_chapter_no=5)
        fixed, was_fixed = HookService._fix_recycle_order(hook, 3, 10)
        assert was_fixed
        assert (fixed.recycle_volume_no, fixed.recycle_chapter_no) > (1, 5)

    def test_last_chapter_no_successor_marked_unrecycled(self):
        hook = HookDto(volume_no=3, chapter_no=10, hook_content="x", recycle_volume_no=1, recycle_chapter_no=5)
        fixed, was_fixed = HookService._fix_recycle_order(hook, 3, 10)
        assert was_fixed
        assert fixed.recycle_status == "unrecycled"


class TestRuleCheckRecycleOrder:
    """组4.1: _rule_check_hooks 回收顺序规则."""

    def test_recycle_before_hook_produces_issue(self):
        from src.api.schemas.character_schema import CharacterDto
        from src.services.hook_service import HookService

        characters = [CharacterDto(name="张三", identity="主角", intro="", relation="")]
        hooks = [HookDto(volume_no=1, chapter_no=5, hook_content="x", recycle_volume_no=1, recycle_chapter_no=3)]
        issues = HookService._rule_check_hooks(characters, [], hooks)
        order_issues = [i for i in issues if i.type == "回收顺序错误"]
        assert len(order_issues) == 1
        assert order_issues[0].level == "严重"

    def test_recycle_equal_hook_produces_issue(self):
        from src.api.schemas.character_schema import CharacterDto
        from src.services.hook_service import HookService

        characters = [CharacterDto(name="张三", identity="主角", intro="", relation="")]
        hooks = [HookDto(volume_no=1, chapter_no=5, hook_content="x", recycle_volume_no=1, recycle_chapter_no=5)]
        issues = HookService._rule_check_hooks(characters, [], hooks)
        order_issues = [i for i in issues if i.type == "回收顺序错误"]
        assert len(order_issues) == 1

    def test_recycle_after_hook_no_issue(self):
        from src.api.schemas.character_schema import CharacterDto
        from src.services.hook_service import HookService

        characters = [CharacterDto(name="张三", identity="主角", intro="", relation="")]
        hooks = [HookDto(volume_no=1, chapter_no=3, hook_content="x", recycle_volume_no=1, recycle_chapter_no=5)]
        issues = HookService._rule_check_hooks(characters, [], hooks)
        order_issues = [i for i in issues if i.type == "回收顺序错误"]
        assert len(order_issues) == 0

    def test_existing_rules_unaffected(self):
        from src.api.schemas.character_schema import CharacterDto
        from src.services.hook_service import HookService

        characters = [CharacterDto(name="张三", identity="主角", intro="", relation="")]
        hooks = [HookDto(volume_no=1, chapter_no=1, hook_content="x", recycle_volume_no=5, recycle_chapter_no=1)]
        issues = HookService._rule_check_hooks(characters, [], hooks)
        distance_issues = [i for i in issues if i.type == "回收距离超限"]
        assert len(distance_issues) == 1


class TestHookRepairSseWorker:
    """组6.4: HookRepairSseWorker."""

    def test_worker_constructs_with_correct_url(self):
        from src.ui.sse_worker import HookRepairSseWorker

        worker = HookRepairSseWorker(
            "proj-123",
            [{"level": "严重", "volume_no": 1, "chapter_no": 1, "type": "回收顺序错误", "detail": "x", "suggestion": "y"}],
            repair_scope="severe",
        )
        assert "/api/hooks/proj-123/repair/stream" in worker._url
        assert worker._payload["repair_scope"] == "severe"

    def test_worker_default_scope(self):
        from src.ui.sse_worker import HookRepairSseWorker

        worker = HookRepairSseWorker("proj-456", [])
        assert worker._payload["repair_scope"] == "all"


class TestPromptExtensions:
    """组1.5: 提示词模板扩展."""

    def test_design_hooks_has_recycle_order_constraint(self):
        from pathlib import Path
        content = Path("src/prompts/hook/design-hooks.j2").read_text(encoding="utf-8")
        assert "严格晚于" in content
        assert "字典序" in content

    def test_generate_chapter_has_recycle_order_constraint(self):
        from pathlib import Path
        content = Path("src/prompts/hook/generate-chapter.j2").read_text(encoding="utf-8")
        assert "严格晚于" in content

    def test_check_consistency_has_recycle_order_dimension(self):
        from pathlib import Path
        content = Path("src/prompts/hook/check-consistency.j2").read_text(encoding="utf-8")
        assert "回收顺序" in content
        assert "回收顺序错误" in content


class TestRepairHookPrompt:
    """组1.4: repair-hook.j2 提示词模板."""

    def test_template_exists(self):
        from pathlib import Path
        assert Path("src/prompts/hook/repair-hook.j2").exists()

    def test_template_has_min_length(self):
        from pathlib import Path
        content = Path("src/prompts/hook/repair-hook.j2").read_text(encoding="utf-8")
        assert "50" in content

    def test_template_no_hardcode(self):
        from pathlib import Path
        content = Path("src/prompts/hook/repair-hook.j2").read_text(encoding="utf-8")
        assert "禁止硬编码" in content


class TestManifestRegistration:
    """组1.4: manifest.yaml 注册."""

    def test_repair_hook_registered(self):
        from pathlib import Path
        import yaml

        manifest = yaml.safe_load(Path("src/prompts/manifest.yaml").read_text(encoding="utf-8"))
        scenes = [
            t for t in manifest.get("templates", [])
            if t.get("module") == "hook" and t.get("scene") == "repair-hook"
        ]
        assert len(scenes) == 1
        assert scenes[0].get("enabled") is True


class TestConfigTimeout:
    """组1.1: 场景化超时配置."""

    def test_hook_repair_timeout(self):
        from src.config.settings import get_config
        assert get_config().hook_repair_timeout_seconds == 120