"""角色关系图谱 Pydantic 模型."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RelationType = Literal[
    "family",
    "master_apprentice",
    "friend",
    "hostile",
    "servant_master",
    "lover",
    "custom",
]


class CharacterRelationshipDto(BaseModel):
    relationship_id: str | None = None
    project_id: str | None = None
    source_character_id: str
    target_character_id: str
    relation_type: RelationType
    description: str | None = None


class RelationshipCreateRequest(BaseModel):
    project_id: str
    source_character_id: str
    target_character_id: str
    relation_type: RelationType
    description: str | None = None


class RelationshipUpdateRequest(BaseModel):
    relation_type: RelationType | None = None
    description: str | None = None


class RelationshipBatchSaveRequest(BaseModel):
    relations: list[CharacterRelationshipDto] = Field(
        default_factory=list, description="全量关系列表（按 relationship_id 增删改）"
    )


class RelationshipGraphDto(BaseModel):
    project_id: str
    nodes: list[dict] = Field(default_factory=list, description="角色节点")
    edges: list[CharacterRelationshipDto] = Field(default_factory=list)


class AutoExtractResult(BaseModel):
    extracted: list[CharacterRelationshipDto]
    skipped: int = 0