"""命名生成器 Pydantic 模型."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class NamingGenerateRequest(BaseModel):
    project_id: str = Field(..., description="项目ID")
    name_type: str = Field(..., description="命名类型：character/place/skill/item/sect等")
    count: int = Field(10, description="候选数量")
    context: str = Field("", description="上下文信息")
    user_ideas: str = Field("", description="作者补充说明")


class NamingCandidate(BaseModel):
    value: str
    reason: str = ""


class NamingGenerateResponse(BaseModel):
    names: list[NamingCandidate] = []


class NamingFavoriteRequest(BaseModel):
    project_id: str
    name_type: str
    value: str


class NamingFavoriteItem(BaseModel):
    name_type: str
    value: str
    meaning: str | None = None


class NamingFavoriteBatchRequest(BaseModel):
    favorites: list[NamingFavoriteItem]


class NamingFavoriteDto(BaseModel):
    favorite_id: str
    project_id: str
    name_type: str
    value: str
    meaning: str | None = None
    created_at: str


class NamingStreamChunk(BaseModel):
    type: Literal["chunk", "done", "progress"] = "chunk"
    content: str = ""
    message: str = ""
    # 供 UI 逐条渲染的结构化字段
    name: str = ""
    naming_type: str = ""
    meaning: str = ""
    progress: int | None = None
    count: int = 0
    total: int = 0