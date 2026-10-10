"""乱码修复配置服务单元测试.

覆盖 design 2.9.1：
  - 三层优先级解析（默认 < 全局 < 项目级）
  - 逐字段覆盖非整条替换
  - CRUD 操作
  - 非法配置回退默认
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.garbled_config_service import GarbledConfigService
from src.services.garbled_normalizer import GarbledConfig


def _make_model(**kwargs):
    """创建模拟的 GarbledConfigModel."""
    model = MagicMock()
    model.config_id = kwargs.get("config_id", str(uuid.uuid4()))
    model.scope = kwargs.get("scope", "global")
    model.project_id = kwargs.get("project_id", None)
    model.enabled = kwargs.get("enabled", None)
    model.max_blank_lines = kwargs.get("max_blank_lines", None)
    model.max_punct_repeat = kwargs.get("max_punct_repeat", None)
    model.max_consecutive_spaces = kwargs.get("max_consecutive_spaces", None)
    model.enable_fullwidth_indent = kwargs.get("enable_fullwidth_indent", None)
    model.enable_punct_repeat_fix = kwargs.get("enable_punct_repeat_fix", None)
    model.enable_whitespace_cleanup = kwargs.get("enable_whitespace_cleanup", None)
    model.enable_irreversible_clear = kwargs.get("enable_irreversible_clear", None)
    return model


class TestConfigResolution:
    """三层优先级解析."""

    @pytest.fixture
    def service(self):
        session = AsyncMock()
        return GarbledConfigService(session)

    @pytest.mark.asyncio
    async def test_default_only(self, service):
        service._get_model = AsyncMock(return_value=None)
        config = await service.resolve_effective_config()
        assert config.enabled is True
        assert config.max_blank_lines == 1
        assert config.max_punct_repeat == 2

    @pytest.mark.asyncio
    async def test_global_overrides_default(self, service):
        global_model = _make_model(scope="global", enabled=True, max_blank_lines=3)
        service._get_model = AsyncMock(return_value=global_model)
        config = await service.resolve_effective_config()
        assert config.max_blank_lines == 3

    @pytest.mark.asyncio
    async def test_project_overrides_global(self, service):
        call_count = [0]

        async def mock_get_model(scope, project_id):
            call_count[0] += 1
            if scope == "global":
                return _make_model(scope="global", max_blank_lines=3)
            if scope == "project":
                return _make_model(scope="project", max_blank_lines=5)
            return None

        service._get_model = mock_get_model
        config = await service.resolve_effective_config("test-pid")
        assert config.max_blank_lines == 5

    @pytest.mark.asyncio
    async def test_field_by_field_override(self, service):
        global_model = _make_model(scope="global", enabled=False, max_blank_lines=3)
        service._get_model = AsyncMock(return_value=global_model)
        config = await service.resolve_effective_config()
        assert config.enabled is False
        assert config.max_blank_lines == 3
        assert config.max_punct_repeat == 2

    @pytest.mark.asyncio
    async def test_project_partial_null_inherits_global(self, service):
        async def mock_get_model(scope, project_id):
            if scope == "global":
                return _make_model(scope="global", max_blank_lines=3, max_punct_repeat=5)
            if scope == "project":
                return _make_model(scope="project", max_blank_lines=7)
            return None

        service._get_model = mock_get_model
        config = await service.resolve_effective_config("test-pid")
        assert config.max_blank_lines == 7
        assert config.max_punct_repeat == 5

    @pytest.mark.asyncio
    async def test_exception_returns_default(self, service):
        service._get_model = AsyncMock(side_effect=Exception("DB error"))
        config = await service.resolve_effective_config()
        assert config.enabled is True
        assert config.max_blank_lines == 1


class TestConfigCrud:
    """CRUD 操作."""

    @pytest.fixture
    def service(self):
        session = AsyncMock()
        return GarbledConfigService(session)

    @pytest.mark.asyncio
    async def test_save_new_config(self, service):
        service._get_model = AsyncMock(return_value=None)
        config = GarbledConfig(enabled=False, max_blank_lines=5)
        await service.save_config("global", None, config)
        service.session.add.assert_called_once()
        service.session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_existing_config_upsert(self, service):
        existing = _make_model(scope="global", enabled=True, max_blank_lines=1)
        service._get_model = AsyncMock(return_value=existing)
        config = GarbledConfig(enabled=False, max_blank_lines=5)
        await service.save_config("global", None, config)
        assert existing.enabled is False
        assert existing.max_blank_lines == 5
        service.session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_config(self, service):
        existing = _make_model(scope="global")
        service._get_model = AsyncMock(return_value=existing)
        await service.delete_config("global", None)
        service.session.delete.assert_called_once_with(existing)
        service.session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_noop(self, service):
        service._get_model = AsyncMock(return_value=None)
        await service.delete_config("global", None)
        service.session.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_config(self, service):
        model = _make_model(scope="global", enabled=False)
        service._get_model = AsyncMock(return_value=model)
        result = await service.get_config("global", None)
        assert result is model