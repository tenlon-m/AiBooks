"""单元配角作用域功能测试 - 改进2."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.schemas.character_schema import CharacterDto, UpdateScopeRequest


def _make_character(
    char_id="c1",
    project_id="proj-1",
    name="林动",
    identity="主角",
    confirmed=True,
    scope_type=None,
    scope_unit_id=None,
    source="ai_extract",
):
    ch = MagicMock()
    ch.character_id = char_id
    ch.project_id = project_id
    ch.name = name
    ch.identity = identity
    ch.intro = "简介"
    ch.relation = None
    ch.source = source
    ch.confirmed = confirmed
    ch.appearance_records = None
    ch.supporting_type = None
    ch.auto_gen_context = None
    ch.future_reference = None
    ch.scope_type = scope_type
    ch.scope_unit_id = scope_unit_id
    return ch


def _make_story_unit(unit_id, project_id="proj-1", parent_id=None, level_type="middle"):
    unit = MagicMock()
    unit.story_unit_id = unit_id
    unit.project_id = project_id
    unit.parent_unit_id = parent_id
    unit.level_type = level_type
    return unit


def _mock_execute_result(items):
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=items)
    scalars_mock.first = MagicMock(return_value=items[0] if items else None)
    result.scalars = MagicMock(return_value=scalars_mock)
    return result


class TestCharacterScopeDefaults:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_old_character_defaults_to_fullbook_scope(self, mock_session):
        ch = _make_character(scope_type=None, scope_unit_id=None)
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            dto = service._to_dto(ch)
            assert dto.scope_type == "全书"
            assert dto.scope_unit_id is None

    @pytest.mark.asyncio
    async def test_create_sets_default_scope(self, mock_session):
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            with patch("src.services.character_service.uuid") as mock_uuid:
                mock_uuid.uuid4.return_value = "new-id"
                dto = await service.create("proj-1", "新角色", "配角", None, None, "manual_input")
            assert dto.scope_type == "全书"
            assert dto.scope_unit_id is None


class TestListByScope:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_fullbook_scope_returns_all_confirmed(self, mock_session):
        main_char = _make_character(char_id="c1", name="主角甲", identity="主角", scope_type="全书")
        sub_char = _make_character(char_id="c2", name="配角乙", identity="配角", scope_type="全书")
        mock_session.execute = AsyncMock(
            return_value=_mock_execute_result([main_char, sub_char])
        )
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            result = await service.list_by_scope("proj-1", "全书", None)
        assert len(result) == 2
        assert {c.character_id for c in result} == {"c1", "c2"}

    @pytest.mark.asyncio
    async def test_drill_down_merges_correctly(self, mock_session):
        main_char = _make_character(char_id="c1", name="主角", identity="主角", scope_type="全书")
        major_char = _make_character(
            char_id="c2", name="大篇配角", identity="配角",
            scope_type="某大篇", scope_unit_id="maj-1",
        )
        middle_char = _make_character(
            char_id="c3", name="中篇配角", identity="配角",
            scope_type="某中篇", scope_unit_id="mid-1",
        )
        other_char = _make_character(
            char_id="c4", name="其他中篇配角", identity="配角",
            scope_type="某中篇", scope_unit_id="mid-2",
        )
        middle_unit = _make_story_unit("mid-1", parent_id="maj-1", level_type="middle")
        major_unit = _make_story_unit("maj-1", parent_id="vol-1", level_type="major")
        vol_unit = _make_story_unit("vol-1", parent_id=None, level_type="volume")

        mock_session.get = AsyncMock(side_effect=[middle_unit, major_unit, vol_unit])
        mock_session.execute = AsyncMock(
            return_value=_mock_execute_result([main_char, major_char, middle_char, other_char])
        )
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            result = await service.list_by_scope("proj-1", "某中篇", "mid-1")
        ids = {c.character_id for c in result}
        assert "c1" in ids
        assert "c2" in ids
        assert "c3" in ids
        assert "c4" not in ids

    @pytest.mark.asyncio
    async def test_unit_scope_requires_unit_id(self, mock_session):
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            with pytest.raises(ValueError, match="必须指定作用域单元"):
                await service.list_by_scope("proj-1", "某中篇", None)

    @pytest.mark.asyncio
    async def test_unit_not_found_raises(self, mock_session):
        mock_session.get = AsyncMock(return_value=None)
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            with pytest.raises(ValueError, match="作用域单元不存在"):
                await service.list_by_scope("proj-1", "某中篇", "nonexistent")


class TestUpdateScope:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_update_to_fullbook_success(self, mock_session):
        ch = _make_character(char_id="c1", identity="配角", scope_type="某大篇", scope_unit_id="maj-1")
        mock_session.get = AsyncMock(return_value=ch)
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            result = await service.update_scope("c1", "全书", None)
        assert result.scope_type == "全书"
        assert ch.scope_type == "全书"
        assert ch.scope_unit_id is None

    @pytest.mark.asyncio
    async def test_update_to_unit_scope_success(self, mock_session):
        ch = _make_character(char_id="c1", identity="配角", scope_type="全书")
        unit = _make_story_unit("maj-1", level_type="major")
        mock_session.get = AsyncMock(side_effect=[ch, unit])
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            result = await service.update_scope("c1", "某大篇", "maj-1")
        assert result.scope_type == "某大篇"
        assert ch.scope_unit_id == "maj-1"

    @pytest.mark.asyncio
    async def test_main_character_reject_unit_scope(self, mock_session):
        ch = _make_character(char_id="c1", identity="主角", scope_type="全书")
        mock_session.get = AsyncMock(return_value=ch)
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            with pytest.raises(ValueError, match="主角必须全书可见"):
                await service.update_scope("c1", "某大篇", "maj-1")

    @pytest.mark.asyncio
    async def test_unit_scope_requires_unit_id(self, mock_session):
        ch = _make_character(char_id="c1", identity="配角", scope_type="全书")
        mock_session.get = AsyncMock(return_value=ch)
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            with pytest.raises(ValueError, match="必须指定作用域单元"):
                await service.update_scope("c1", "某大篇", None)

    @pytest.mark.asyncio
    async def test_unit_not_found_raises(self, mock_session):
        ch = _make_character(char_id="c1", identity="配角", scope_type="全书")
        mock_session.get = AsyncMock(side_effect=[ch, None])
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            with pytest.raises(ValueError, match="作用域单元不存在"):
                await service.update_scope("c1", "某大篇", "nonexistent")

    @pytest.mark.asyncio
    async def test_character_not_found_raises(self, mock_session):
        mock_session.get = AsyncMock(return_value=None)
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            with pytest.raises(ValueError, match="人物不存在"):
                await service.update_scope("nonexistent", "全书", None)


class TestCheckNameUnique:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_name_unique_when_no_conflict(self, mock_session):
        mock_session.execute = AsyncMock(return_value=_mock_execute_result([]))
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            result = await service.check_name_unique("proj-1", "新名字")
        assert result is True

    @pytest.mark.asyncio
    async def test_name_not_unique_when_conflict(self, mock_session):
        existing = _make_character(char_id="c1", name="林动")
        mock_session.execute = AsyncMock(return_value=_mock_execute_result([existing]))
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            result = await service.check_name_unique("proj-1", "林动")
        assert result is False


class TestBackwardCompatibility:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_old_character_without_scope_fields(self, mock_session):
        ch = _make_character(scope_type=None, scope_unit_id=None)
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            dto = service._to_dto(ch)
        assert dto.scope_type == "全书"
        assert dto.name == "林动"
        assert dto.identity == "主角"
        assert dto.confirmed is True

    @pytest.mark.asyncio
    async def test_list_confirmed_still_works(self, mock_session):
        chars = [
            _make_character(char_id="c1", name="甲", scope_type="全书"),
            _make_character(char_id="c2", name="乙", scope_type=None),
        ]
        mock_session.execute = AsyncMock(return_value=_mock_execute_result(chars))
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            result = await service.list_confirmed("proj-1")
        assert len(result) == 2
        assert result[0].scope_type == "全书"
        assert result[1].scope_type == "全书"

    @pytest.mark.asyncio
    async def test_list_by_project_still_works(self, mock_session):
        chars = [
            _make_character(char_id="c1", name="甲", scope_type="全书"),
            _make_character(char_id="c2", name="乙", scope_type=None),
        ]
        mock_session.execute = AsyncMock(return_value=_mock_execute_result(chars))
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            result = await service.list_by_project("proj-1")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_update_without_scope_still_works(self, mock_session):
        ch = _make_character(char_id="c1", name="旧名", identity="配角")
        mock_session.get = AsyncMock(return_value=ch)
        from src.api.schemas.character_schema import CharacterUpdateRequest
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            req = CharacterUpdateRequest(name="新名", identity="新身份")
            result = await service.update("c1", req)
        assert result.name == "新名"
        assert result.identity == "新身份"

    @pytest.mark.asyncio
    async def test_delete_still_works(self, mock_session):
        ch = _make_character(char_id="c1")
        mock_session.get = AsyncMock(return_value=ch)
        mock_session.delete = AsyncMock()
        mock_session.flush = AsyncMock()
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            result = await service.delete("c1")
        assert result is True

    @pytest.mark.asyncio
    async def test_confirm_still_works(self, mock_session):
        ch = _make_character(char_id="c1", confirmed=False)
        mock_session.get = AsyncMock(return_value=ch)
        mock_session.flush = AsyncMock()
        from src.services.character_service import CharacterService
        with patch("src.services.character_service.get_gateway"):
            service = CharacterService(mock_session)
            result = await service.confirm("c1")
        assert result.confirmed is True
        assert ch.confirmed is True


class TestSchemaUpdateScopeRequest:
    def test_update_scope_request_fullbook(self):
        req = UpdateScopeRequest(scope_type="全书", scope_unit_id=None)
        assert req.scope_type == "全书"
        assert req.scope_unit_id is None

    def test_update_scope_request_unit(self):
        req = UpdateScopeRequest(scope_type="某大篇", scope_unit_id="maj-1")
        assert req.scope_type == "某大篇"
        assert req.scope_unit_id == "maj-1"

    def test_character_dto_with_scope(self):
        dto = CharacterDto(
            name="林动",
            identity="主角",
            scope_type="某中篇",
            scope_unit_id="mid-1",
        )
        assert dto.scope_type == "某中篇"
        assert dto.scope_unit_id == "mid-1"

    def test_character_dto_scope_optional(self):
        dto = CharacterDto(name="林动", identity="主角")
        assert dto.scope_type is None
        assert dto.scope_unit_id is None