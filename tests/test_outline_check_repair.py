"""大纲校验修复增强功能单元测试."""
from __future__ import annotations

import pytest

from src.api.schemas.outline_schema import (
    AdjustNote,
    FillAppearingRequest,
    FillAppearingResponse,
    FillAppearingResultItem,
    OutlineConsistencyIssue,
    OutlineRepairRequest,
    RepairStreamChunk,
)
from src.api.schemas.validation_schema import CharacterCountIntegrityItem


class TestSchemaBasics:
    """任务1.2: Schema 基础验证."""

    def test_fill_appearing_request_all_none(self):
        req = FillAppearingRequest()
        assert req.volume_no is None
        assert req.chapter_start is None
        assert req.chapter_count is None

    def test_fill_appearing_result_item_defaults(self):
        item = FillAppearingResultItem(chapter_no=1)
        assert item.matched == []
        assert item.pending == []
        assert item.skipped is False
        assert item.fail_reason is None

    def test_fill_appearing_response_defaults(self):
        resp = FillAppearingResponse()
        assert resp.results == []
        assert resp.summary == ""

    def test_adjust_note_required_fields(self):
        note = AdjustNote(position="第3章梗概", reason="人物出场矛盾")
        assert note.position == "第3章梗概"
        assert note.reason == "人物出场矛盾"
        assert note.original is None
        assert note.polished is None

    def test_outline_repair_request_defaults(self):
        req = OutlineRepairRequest(issues=[])
        assert req.repair_scope == "all"

    def test_outline_repair_request_with_scope(self):
        issue = OutlineConsistencyIssue(level="严重", chapter_no=1, type="偏离梗概", detail="x", suggestion="y")
        req = OutlineRepairRequest(issues=[issue], repair_scope="severe")
        assert req.repair_scope == "severe"
        assert len(req.issues) == 1

    def test_repair_stream_chunk_minimal(self):
        chunk = RepairStreamChunk(type="progress")
        assert chunk.type == "progress"
        assert chunk.chapter_no is None
        assert chunk.success is None

    def test_repair_stream_chunk_chapter_done(self):
        chunk = RepairStreamChunk(
            type="chapter_done",
            chapter_no=3,
            volume_no=1,
            synopsis_points_new="修复后的梗概",
            characters_appearing_new="张三、李四",
        )
        assert chunk.chapter_no == 3
        assert chunk.synopsis_points_new == "修复后的梗概"

    def test_character_count_integrity_item(self):
        item = CharacterCountIntegrityItem(
            check_type="character_count_integrity",
            result="pass",
            content_character_count=10,
            confirmed_character_count=8,
        )
        assert item.check_type == "character_count_integrity"
        assert item.content_character_count == 10
        assert item.confirmed_character_count == 8

    def test_character_count_integrity_item_backward_compat(self):
        item = CharacterCountIntegrityItem(
            check_type="character_count_integrity",
            result="fail",
            problem_desc="测试",
        )
        assert item.volume_no is None
        assert item.chapter_no is None
        assert item.content_character_count is None


class TestRuleCheckSceneConsistency:
    """任务3.4: _rule_check 场景角色未登记规则."""

    def test_scene_character_not_registered(self):
        from src.api.schemas.character_schema import CharacterDto
        from src.services.outline_service import OutlineService

        characters = [
            CharacterDto(name="张三", identity="主角", intro="", relation=""),
            CharacterDto(name="李四", identity="配角", intro="", relation=""),
        ]
        chapters = [
            {
                "chapter_no": 1,
                "chapter_name": "测试章",
                "synopsis_points": "张三出场",
                "characters_appearing": "张三",
                "scenes": [
                    {"goal": "目标", "characters": "张三、王五", "key_event": "事件"},
                ],
            }
        ]
        issues = OutlineService._rule_check(characters, chapters)
        scene_issues = [i for i in issues if i.type == "场景一致性"]
        assert len(scene_issues) == 1
        assert "王五" in scene_issues[0].detail
        assert scene_issues[0].level == "一般"

    def test_no_scenes_no_scene_issue(self):
        from src.api.schemas.character_schema import CharacterDto
        from src.services.outline_service import OutlineService

        characters = [CharacterDto(name="张三", identity="主角", intro="", relation="")]
        chapters = [
            {
                "chapter_no": 1,
                "chapter_name": "测试章",
                "synopsis_points": "张三出场",
                "characters_appearing": "张三",
                "scenes": [],
            }
        ]
        issues = OutlineService._rule_check(characters, chapters)
        scene_issues = [i for i in issues if i.type == "场景一致性"]
        assert len(scene_issues) == 0

    def test_scene_character_in_known_names_no_issue(self):
        from src.api.schemas.character_schema import CharacterDto
        from src.services.outline_service import OutlineService

        characters = [
            CharacterDto(name="张三", identity="主角", intro="", relation=""),
            CharacterDto(name="李四", identity="配角", intro="", relation=""),
        ]
        chapters = [
            {
                "chapter_no": 1,
                "chapter_name": "测试章",
                "synopsis_points": "张三和李四出场",
                "characters_appearing": "张三、李四",
                "scenes": [
                    {"goal": "目标", "characters": "张三、李四", "key_event": "事件"},
                ],
            }
        ]
        issues = OutlineService._rule_check(characters, chapters)
        scene_issues = [i for i in issues if i.type == "场景一致性"]
        assert len(scene_issues) == 0


class TestCharacterCoverageIssues:
    """任务3.5: _build_character_coverage_issues 人物未出场校验."""

    def test_unappeared_character_produces_issue(self):
        from src.ui.outline_check_controller import OutlineCheckController
        from PySide6.QtWidgets import QWidget

        controller = OutlineCheckController()
        controller._outline = {
            "volumes": [
                {
                    "volume_no": 1,
                    "chapters": [
                        {"chapter_no": 1, "characters_appearing": "张三"},
                    ],
                }
            ]
        }
        controller._characters = [
            {"name": "张三", "identity": "主角", "confirmed": True},
            {"name": "李四", "identity": "配角", "confirmed": True},
        ]
        issues = controller._build_character_coverage_issues()
        assert len(issues) == 1
        assert issues[0]["type"] == "人物未出场"
        assert issues[0]["level"] == "一般"
        assert "李四" in issues[0]["detail"]

    def test_appeared_character_no_issue(self):
        from src.ui.outline_check_controller import OutlineCheckController

        controller = OutlineCheckController()
        controller._outline = {
            "volumes": [
                {
                    "volume_no": 1,
                    "chapters": [
                        {"chapter_no": 1, "characters_appearing": "张三、李四"},
                    ],
                }
            ]
        }
        controller._characters = [
            {"name": "张三", "identity": "主角", "confirmed": True},
            {"name": "李四", "identity": "配角", "confirmed": True},
        ]
        issues = controller._build_character_coverage_issues()
        assert len(issues) == 0

    def test_cross_volume_no_false_positive(self):
        from src.ui.outline_check_controller import OutlineCheckController

        controller = OutlineCheckController()
        controller._outline = {
            "volumes": [
                {
                    "volume_no": 1,
                    "chapters": [
                        {"chapter_no": 1, "characters_appearing": "张三"},
                    ],
                },
                {
                    "volume_no": 2,
                    "chapters": [
                        {"chapter_no": 1, "characters_appearing": "李四"},
                    ],
                },
            ]
        }
        controller._characters = [
            {"name": "张三", "identity": "主角", "confirmed": True},
            {"name": "李四", "identity": "配角", "confirmed": True},
        ]
        issues = controller._build_character_coverage_issues()
        assert len(issues) == 0

    def test_empty_characters_no_issue(self):
        from src.ui.outline_check_controller import OutlineCheckController

        controller = OutlineCheckController()
        controller._outline = {"volumes": []}
        controller._characters = []
        issues = controller._build_character_coverage_issues()
        assert len(issues) == 0


class TestOutlineRepairSseWorker:
    """任务5.4: OutlineRepairSseWorker."""

    def test_worker_constructs_with_correct_url(self):
        from src.ui.sse_worker import OutlineRepairSseWorker

        worker = OutlineRepairSseWorker(
            "proj-123",
            [{"level": "严重", "chapter_no": 1, "type": "偏离梗概", "detail": "x", "suggestion": "y"}],
            repair_scope="severe",
        )
        assert "/api/outlines/proj-123/repair/stream" in worker._url
        assert worker._payload["repair_scope"] == "severe"
        assert len(worker._payload["issues"]) == 1

    def test_worker_default_scope(self):
        from src.ui.sse_worker import OutlineRepairSseWorker

        worker = OutlineRepairSseWorker("proj-456", [])
        assert worker._payload["repair_scope"] == "all"
        assert worker._payload["issues"] == []


class TestCheckConsistencyPrompt:
    """任务3.1: check-consistency.j2 模板增加场景一致性维度."""

    def test_prompt_has_scene_consistency_dimension(self):
        from pathlib import Path

        prompt_path = Path("src/prompts/outline/check-consistency.j2")
        content = prompt_path.read_text(encoding="utf-8")
        assert "场景一致性" in content
        assert "场景列表" in content

    def test_prompt_has_scene_list_per_chapter(self):
        from pathlib import Path

        prompt_path = Path("src/prompts/outline/check-consistency.j2")
        content = prompt_path.read_text(encoding="utf-8")
        assert "ch.scenes" in content
        assert "未细化场景" in content

    def test_prompt_type_includes_scene_consistency(self):
        from pathlib import Path

        prompt_path = Path("src/prompts/outline/check-consistency.j2")
        content = prompt_path.read_text(encoding="utf-8")
        assert "场景一致性" in content
        assert "人物未出场" in content


class TestFillAppearingPrompt:
    """任务1.3: fill-appearing.j2 提示词模板."""

    def test_template_exists(self):
        from pathlib import Path

        assert Path("src/prompts/outline/fill-appearing.j2").exists()

    def test_template_no_hardcoded_names(self):
        from pathlib import Path

        content = Path("src/prompts/outline/fill-appearing.j2").read_text(encoding="utf-8")
        assert "不得硬编码" in content or "不硬编码" in content


class TestRepairOutlinePrompt:
    """任务1.3: repair-outline.j2 提示词模板."""

    def test_template_exists(self):
        from pathlib import Path

        assert Path("src/prompts/outline/repair-outline.j2").exists()

    def test_template_has_min_length_constraint(self):
        from pathlib import Path

        content = Path("src/prompts/outline/repair-outline.j2").read_text(encoding="utf-8")
        assert "50" in content


class TestCharacterCountIntegrityPrompt:
    """任务1.3: character-count-integrity.j2 提示词模板."""

    def test_template_exists(self):
        from pathlib import Path

        assert Path("src/prompts/validation/character-count-integrity.j2").exists()

    def test_template_no_hardcoded_names(self):
        from pathlib import Path

        content = Path("src/prompts/validation/character-count-integrity.j2").read_text(encoding="utf-8")
        assert "不得硬编码" in content or "不硬编码" in content


class TestManifestRegistration:
    """任务1.3: manifest.yaml 注册新模板."""

    def test_fill_appearing_registered(self):
        from pathlib import Path
        import yaml

        manifest = yaml.safe_load(Path("src/prompts/manifest.yaml").read_text(encoding="utf-8"))
        scenes = [
            t for t in manifest.get("templates", [])
            if t.get("module") == "outline" and t.get("scene") == "fill-appearing"
        ]
        assert len(scenes) == 1
        assert scenes[0].get("enabled") is True

    def test_repair_outline_registered(self):
        from pathlib import Path
        import yaml

        manifest = yaml.safe_load(Path("src/prompts/manifest.yaml").read_text(encoding="utf-8"))
        scenes = [
            t for t in manifest.get("templates", [])
            if t.get("module") == "outline" and t.get("scene") == "repair-outline"
        ]
        assert len(scenes) == 1
        assert scenes[0].get("enabled") is True

    def test_character_count_integrity_registered(self):
        from pathlib import Path
        import yaml

        manifest = yaml.safe_load(Path("src/prompts/manifest.yaml").read_text(encoding="utf-8"))
        scenes = [
            t for t in manifest.get("templates", [])
            if t.get("module") == "validation" and t.get("scene") == "character-count-integrity"
        ]
        assert len(scenes) == 1
        assert scenes[0].get("enabled") is True


class TestConfigTimeouts:
    """任务1.1: 场景化超时配置项."""

    def test_fill_appearing_timeout(self):
        from src.config.settings import get_config

        assert get_config().outline_fill_appearing_timeout_seconds == 90

    def test_repair_timeout(self):
        from src.config.settings import get_config

        assert get_config().outline_repair_timeout_seconds == 120

    def test_character_count_timeout(self):
        from src.config.settings import get_config

        assert get_config().validation_character_count_timeout_seconds == 120