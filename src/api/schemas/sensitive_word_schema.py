"""敏感词检测 Pydantic 模型."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SensitiveWordDto(BaseModel):
    word_id: str | None = None
    project_id: str | None = None
    word: str
    category: str
    suggestion: str | None = None
    is_builtin: bool = False


class SensitiveWordListResponse(BaseModel):
    words: list[SensitiveWordDto] = Field(default_factory=list)
    total: int = 0


class SensitiveWordAddRequest(BaseModel):
    project_id: str | None = None
    word: str
    category: str = "custom"
    suggestion: str | None = None


class SensitiveWordUpdateRequest(BaseModel):
    word: str | None = None
    category: str | None = None
    suggestion: str | None = None


class SensitiveWordScanRequest(BaseModel):
    project_id: str
    chapter_ids: list[str] | None = Field(
        None, description="待扫描章节ID列表，为空则扫描全书"
    )


# --------------------------------------------------------------------------- #
# UI 兼容请求模型（sensitive_word_page 的调用契约）
#
# 前端自「打开项目」起就会调用 /api/sensitive/words 系列端点，字段名与
# 上面的模型不同（replace_suggestion 而非 suggestion），且保存/删除是批量
# 语义。历史上服务端从未实现这些路径，前端全部拿到 405/404，其中
# GET /api/sensitive/words 的 405 会在打开项目时直接弹出
# 「API 405: Method Not Allowed」。
# --------------------------------------------------------------------------- #


class SensitiveWordUiAddRequest(BaseModel):
    """POST /api/sensitive/words 的请求体."""

    word: str
    category: str = "custom"
    replace_suggestion: str | None = None
    project_id: str | None = None


class SensitiveWordUiUpsertItem(BaseModel):
    """PUT /api/sensitive/words 请求体中的单个词条.

    ``word_id`` 为空视为新增；有 word_id 则更新（内置词不可改，会被跳过）。
    """

    word_id: str | None = None
    word: str
    category: str = "custom"
    replace_suggestion: str | None = None


class SensitiveWordUiSaveRequest(BaseModel):
    """PUT /api/sensitive/words 的请求体."""

    words: list[SensitiveWordUiUpsertItem] = Field(default_factory=list)


class SensitiveWordUiDeleteRequest(BaseModel):
    """DELETE /api/sensitive/words 的请求体."""

    word_ids: list[str] = Field(default_factory=list)


class SensitiveScanUiRequest(BaseModel):
    """POST /api/sensitive/scan/{project_id} 的请求体."""

    user_ideas: str = ""


class SensitiveHitDto(BaseModel):
    word: str
    category: str
    suggestion: str | None = None
    chapter_id: str
    chapter_no: int
    count: int


class SensitiveScanResult(BaseModel):
    project_id: str
    total_hits: int
    hits: list[SensitiveHitDto] = Field(default_factory=list)