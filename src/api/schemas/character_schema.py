"""人物管理 Pydantic 模型."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CharacterDto(BaseModel):
    character_id: str | None = None
    project_id: str | None = None
    name: str = Field(min_length=1, max_length=20)
    identity: str
    intro: str | None = None
    relation: str | None = None
    source: Literal["ai_extract", "ai_generate", "manual_input", "file_import", "auto_generated", "naming_import"] = "manual_input"
    confirmed: bool = False
    appearance_records: str | None = None
    supporting_type: str | None = None
    auto_gen_context: str | None = None
    future_reference: bool | None = None
    scope_type: str | None = None
    scope_unit_id: str | None = None


class CharacterCreateRequest(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=20)
    identity: str
    intro: str | None = None
    relation: str | None = None
    source: Literal["ai_extract", "ai_generate", "manual_input", "file_import", "auto_generated", "naming_import"] = "manual_input"


class CharacterUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=20)
    identity: str | None = None
    intro: str | None = None
    relation: str | None = None
    confirmed: bool | None = None


class UpdateScopeRequest(BaseModel):
    scope_type: str
    scope_unit_id: str | None = None


class AiExtractCharactersRequest(BaseModel):
    project_id: str
    synopsis: str
    worldview: str


class AiExtractCharactersResponse(BaseModel):
    characters: list[CharacterDto]


class AiGenerateSupportingRequest(BaseModel):
    project_id: str
    synopsis: str
    worldview: str
    existing_characters: list[CharacterDto]
    count: int = 3

class AiImportCharactersRequest(BaseModel):
    project_id: str
    file_path: str

class MergeResultResponse(BaseModel):
    """增量去重合并写入结果响应."""
    added: list[CharacterDto] = []
    skipped: list[CharacterDto] = []
    added_count: int = 0
    skipped_count: int = 0


class BatchDeleteRequest(BaseModel):
    """批量删除人物请求."""
    character_ids: list[str] = Field(min_length=1)


class BatchConfirmRequest(BaseModel):
    """批量确认人物请求."""
    character_ids: list[str] = Field(min_length=1)

class SupportingDraft(BaseModel):
    """AI 自动生成配角草稿值对象."""
    name: str = Field(min_length=1)
    identity: str = "配角"
    intro: str = ""
    relation: str = ""
    future_reference: bool = True


class EnsureResult(BaseModel):
    """自动配角检测结果响应."""
    added: list[CharacterDto] = []
    temporary: list[SupportingDraft] = []
    skipped: int = 0
    warnings: list[str] = []
    limitation_notice: str = ""


class PersistDecision(BaseModel):
    """配角持久化判定结果."""
    character: CharacterDto
    should_persist: bool
    reason: str