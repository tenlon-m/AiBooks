"""风格库 Pydantic 模型."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class StyleFeatureDto(BaseModel):
    feature_id: str | None = None
    dimension: Literal[
        "narrative_pov", "sentence_pattern", "word_usage",
        "rhythm", "paragraph_structure", "dialogue_style", "other"
    ]
    description: str
    source: Literal["ai_extract", "user_edit", "user_supplement", "builtin"] = "ai_extract"


class CorpusInfoDto(BaseModel):
    file_name: str
    char_count: int


class StyleLibraryDto(BaseModel):
    style_library_id: str | None = None
    name: str = Field(min_length=1, max_length=100)
    naming_source: Literal["custom", "author", "import", "builtin"] = "custom"
    features: list[StyleFeatureDto] = []
    corpus_info: list[CorpusInfoDto] = []
    built_at: datetime | None = None
    build_method: Literal["feed", "manual", "import", "builtin"] = "feed"
    confirmed: bool = True


class FeedStyleRequest(BaseModel):
    file_paths: list[str]
    naming: Literal["custom", "author"]
    name: str = Field(min_length=1, max_length=100)
    user_ideas: str = ""


class BatchDeleteStyleLibrariesRequest(BaseModel):
    style_library_ids: list[str]


class StyleLibraryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    features: list[StyleFeatureDto] | None = None
    confirmed: bool | None = None


class StyleLibraryExportRequest(BaseModel):
    style_library_id: str
    target_path: str


class StyleLibraryImportRequest(BaseModel):
    file_path: str
    conflict_strategy: Literal["overwrite", "rename", "cancel"] = "rename"