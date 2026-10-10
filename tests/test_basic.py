"""基础测试 - 配置与加密."""
import pytest


def test_app_config():
    from src.config.app_config import AppConfig
    config = AppConfig()
    assert config.app_name == "AiBooks"
    assert config.import_max_file_size_mb == 50
    assert config.writing_words_tolerance == 0.2


def test_creation_params_validation():
    from src.api.schemas.creation_schema import CreationParamsRequest
    from pydantic import ValidationError

    req = CreationParamsRequest(
        book_title="测试小说",
        volume_count=3,
        chapters_per_volume=10,
        words_per_chapter=3000,
    )
    assert req.book_title == "测试小说"

    with pytest.raises(ValidationError):
        CreationParamsRequest(book_title="", volume_count=3, chapters_per_volume=10, words_per_chapter=3000)

    with pytest.raises(ValidationError):
        CreationParamsRequest(book_title="测试", volume_count=0, chapters_per_volume=10, words_per_chapter=3000)

    with pytest.raises(ValidationError):
        CreationParamsRequest(book_title="测试", volume_count=3, chapters_per_volume=10, words_per_chapter=100)


def test_ai_source_schema():
    from src.api.schemas.ai_source_schema import AiSourceCreateRequest
    from pydantic import ValidationError

    req = AiSourceCreateRequest(
        name="测试源",
        source_type="local_ollama",
        api_endpoint="http://localhost:11434/v1",
        model_name="qwen2.5",
    )
    assert req.source_type == "local_ollama"

    with pytest.raises(ValidationError):
        AiSourceCreateRequest(
            name="",
            source_type="local_ollama",
            api_endpoint="http://localhost:11434/v1",
            model_name="qwen2.5",
        )


def test_hook_schema():
    from src.api.schemas.hook_schema import HookDto
    h = HookDto(
        volume_no=1,
        chapter_no=1,
        hook_content="测试钩子",
        recycle_volume_no=2,
        recycle_chapter_no=1,
    )
    assert h.recycle_status == "pending"


def test_style_feature_dimensions():
    from src.api.schemas.style_library_schema import StyleFeatureDto
    for dim in ["narrative_pov", "sentence_pattern", "word_usage", "rhythm", "paragraph_structure", "dialogue_style"]:
        f = StyleFeatureDto(dimension=dim, description="测试")
        assert f.dimension == dim


def test_json_extraction():
    from src.ai.gateway import AiGateway
    result = AiGateway._extract_json('{"key": "value"}')
    assert result == {"key": "value"}

    result = AiGateway._extract_json('```json\n{"key": "value"}\n```')
    assert result == {"key": "value"}

    result = AiGateway._extract_json('一些文字\n{"key": "value"}\n更多文字')
    assert result == {"key": "value"}

    result = AiGateway._extract_json("")
    assert result is None