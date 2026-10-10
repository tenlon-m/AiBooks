"""场景显示增强功能单元测试."""
from __future__ import annotations

import pytest

from src.api.schemas.outline_schema import ChapterOutlineDto
from src.ui.pages.ai_call_log_page import SCENE_LABELS


class TestSceneLabels:
    def test_label_count(self):
        assert len(SCENE_LABELS) == 26

    def test_known_mappings(self):
        assert SCENE_LABELS["scene-split"] == "场景细化"
        assert SCENE_LABELS["extract-main"] == "提取主角"
        assert SCENE_LABELS["write-chapter"] == "撰写章节"
        assert SCENE_LABELS["check-consistency"] == "一致性校验"
        assert SCENE_LABELS["polish-synopsis"] == "润色梗概"
        assert SCENE_LABELS["auto-generate-supporting"] == "自动生成配角"

    def test_unknown_label_passthrough(self):
        scene_raw = "future-unknown-scene"
        assert SCENE_LABELS.get(scene_raw, scene_raw) == scene_raw

    def test_empty_label(self):
        scene_raw = ""
        assert SCENE_LABELS.get(scene_raw, scene_raw) == ""

    def test_all_values_are_chinese(self):
        for v in SCENE_LABELS.values():
            assert len(v) > 0
            assert "\n" not in v


class TestChapterOutlineDtoSceneCount:
    def test_default_scene_count(self):
        dto = ChapterOutlineDto(chapter_no=1, chapter_name="第一章", synopsis_points="梗概")
        assert dto.scene_count == 0

    def test_with_scene_count(self):
        dto = ChapterOutlineDto(chapter_no=1, chapter_name="第一章", synopsis_points="梗概", scene_count=5)
        assert dto.scene_count == 5

    def test_backward_compat(self):
        data = {"chapter_no": 1, "chapter_name": "第一章", "synopsis_points": "梗概"}
        dto = ChapterOutlineDto(**data)
        assert dto.scene_count == 0


class TestOutlineEditDialog:
    def test_chapter_id_param_default_none(self, qapp):
        from src.ui.pages.outline_edit_dialog import OutlineEditDialog
        dialog = OutlineEditDialog(edit_type="volume", volume_name="第一卷")
        assert dialog._chapter_id is None

    def test_get_data_volume_no_scenes_changes(self, qapp):
        from src.ui.pages.outline_edit_dialog import OutlineEditDialog
        dialog = OutlineEditDialog(edit_type="volume", volume_name="第一卷")
        data = dialog.get_data()
        assert "scenes_changes" not in data
        assert data["volume_name"] == "第一卷"

    def test_get_data_chapter_has_scenes_changes(self, qapp):
        from src.ui.pages.outline_edit_dialog import OutlineEditDialog
        dialog = OutlineEditDialog(
            edit_type="chapter",
            chapter_name="第一章",
            synopsis="梗概内容",
            characters_appearing="张三",
        )
        data = dialog.get_data()
        assert "scenes_changes" in data
        assert data["scenes_changes"] == {"modified": [], "deleted": []}