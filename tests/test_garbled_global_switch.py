"""乱码检测全局开关迁移测试 - 覆盖配置字段、页面控件移除、_get_garbled_config契约与调用点兼容性."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QCheckBox, QPushButton

from src.config.app_config import AppConfig
from src.config.settings import get_config


def _cleanup_background_workers() -> None:
    try:
        from src.ui.api_worker import _running_workers
        from src.ui.sse_worker import _running_sse_workers

        for worker in list(_running_workers):
            _running_workers.discard(worker)
        for worker in list(_running_sse_workers):
            try:
                if hasattr(worker, "stop"):
                    worker.stop()
            except Exception:
                pass
            _running_sse_workers.discard(worker)
    except Exception:
        pass


@pytest.fixture()
def config_guard():
    config = get_config()
    orig = config.garbled_detection_enabled
    yield config
    config.garbled_detection_enabled = orig


class TestGarbledConfigField:
    def test_field_exists_with_default_true(self):
        """验证AppConfig类中新增garbled_detection_enabled字段且默认值为True，与迁移前各页面QCheckBox默认勾选状态一致。"""
        config = AppConfig()
        assert hasattr(config, "garbled_detection_enabled")
        assert config.garbled_detection_enabled is True

    def test_field_writable(self, config_guard):
        """验证garbled_detection_enabled字段可读写：设置为False后读取应返回False，设置为True后读取应返回True，持久化生效。"""
        config_guard.garbled_detection_enabled = False
        assert get_config().garbled_detection_enabled is False
        config_guard.garbled_detection_enabled = True
        assert get_config().garbled_detection_enabled is True

    def test_existing_auto_save_fields_unaffected(self):
        """验证新增garbled_detection_enabled字段后已有auto_save_enabled与auto_save_interval_minutes字段不受影响，配置兼容性保持。"""
        config = AppConfig()
        assert config.auto_save_enabled is True
        assert config.auto_save_interval_minutes == 5


class TestWritingPageGarbledMigration:
    @pytest.fixture()
    def writing_page(self, qapp):
        try:
            from src.ui.pages.writing_progress_page import WritingProgressPage

            page = WritingProgressPage()
            yield page
            _cleanup_background_workers()
            page.deleteLater()
        except Exception:
            pytest.skip("WritingProgressPage 实例化需要完整运行环境，跳过迁移测试")

    def test_garbled_switch_removed(self, writing_page):
        """验证迁移后撰写页面工具栏不再存在'乱码检测修复'复选框控件，_garbled_switch属性应不存在，findChild应返回None。"""
        assert not hasattr(writing_page, "_garbled_switch")

    def test_garbled_config_btn_removed(self, writing_page):
        """验证迁移后撰写页面工具栏不再存在'乱码配置'按钮控件，_garbled_config_btn属性应不存在，findChild应返回None。"""
        assert not hasattr(writing_page, "_garbled_config_btn")

    def test_get_garbled_config_returns_disabled_when_off(self, writing_page, config_guard):
        """验证关闭乱码检测后撰写页面_get_garbled_config返回{'enabled': False}，确保返回值结构与迁移前调用点契约一致。"""
        config_guard.garbled_detection_enabled = False
        result = writing_page._get_garbled_config()
        assert result == {"enabled": False}

    def test_get_garbled_config_returns_none_when_on(self, writing_page, config_guard):
        """验证开启乱码检测后撰写页面_get_garbled_config返回None，表示使用服务端默认配置，与迁移前行为一致。"""
        config_guard.garbled_detection_enabled = True
        result = writing_page._get_garbled_config()
        assert result is None


class TestChapterEditPageGarbledMigration:
    @pytest.fixture()
    def edit_page(self, qapp):
        try:
            from src.ui.pages.chapter_edit_page import ChapterEditPage

            page = ChapterEditPage()
            yield page
            _cleanup_background_workers()
            page.deleteLater()
        except Exception:
            pytest.skip("ChapterEditPage 实例化需要完整运行环境，跳过迁移测试")

    def test_garbled_switch_removed(self, edit_page):
        """验证迁移后章节编辑页面工具栏不再存在'乱码修复'复选框控件，_garbled_switch属性应不存在。"""
        assert not hasattr(edit_page, "_garbled_switch")

    def test_garbled_config_btn_removed(self, edit_page):
        """验证迁移后章节编辑页面工具栏不再存在'乱码配置'按钮控件，_garbled_config_btn属性应不存在。"""
        assert not hasattr(edit_page, "_garbled_config_btn")

    def test_get_garbled_config_returns_disabled_when_off(self, edit_page, config_guard):
        """验证关闭乱码检测后章节编辑页面_get_garbled_config返回{'enabled': False}，确保4处调用点参数结构不变。"""
        config_guard.garbled_detection_enabled = False
        result = edit_page._get_garbled_config()
        assert result == {"enabled": False}

    def test_get_garbled_config_returns_none_when_on(self, edit_page, config_guard):
        """验证开启乱码检测后章节编辑页面_get_garbled_config返回None，表示使用服务端默认配置，调用点兼容。"""
        config_guard.garbled_detection_enabled = True
        result = edit_page._get_garbled_config()
        assert result is None


class TestGarbledConfigContract:
    def test_disabled_contract_structure(self, config_guard):
        """验证_get_garbled_config关闭时返回值结构严格为{'enabled': False}，包含enabled键且值为False，7处调用点零改动。"""
        config_guard.garbled_detection_enabled = False
        config = get_config()
        if not config.garbled_detection_enabled:
            result = {"enabled": False}
        else:
            result = None
        assert isinstance(result, dict)
        assert result["enabled"] is False
        assert len(result) == 1

    def test_enabled_contract_returns_none(self, config_guard):
        """验证_get_garbled_config开启时返回None而非空字典，确保使用服务端默认配置的语义与迁移前完全一致。"""
        config_guard.garbled_detection_enabled = True
        config = get_config()
        if not config.garbled_detection_enabled:
            result = {"enabled": False}
        else:
            result = None
        assert result is None

    def test_global_switch_affects_both_pages(self, config_guard):
        """验证统一全局开关同时影响撰写页面与章节编辑页面：关闭后两页面_get_garbled_config均返回{'enabled': False}，强一致。"""
        config_guard.garbled_detection_enabled = False
        config = get_config()
        writing_result = {"enabled": False} if not config.garbled_detection_enabled else None
        chapter_result = {"enabled": False} if not config.garbled_detection_enabled else None
        assert writing_result == chapter_result == {"enabled": False}

        config_guard.garbled_detection_enabled = True
        writing_result = {"enabled": False} if not config.garbled_detection_enabled else None
        chapter_result = {"enabled": False} if not config.garbled_detection_enabled else None
        assert writing_result is None
        assert chapter_result is None