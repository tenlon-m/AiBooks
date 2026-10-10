"""快捷键 Pydantic 模型."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ShortcutDto(BaseModel):
    shortcut_id: str
    action_name: str
    action_label: str
    key_sequence: str
    enabled: bool
    is_builtin: bool = True


class ShortcutUpdateRequest(BaseModel):
    key_sequence: str | None = Field(
        default=None, description="新快捷键序列，None 表示不修改"
    )
    enabled: bool | None = Field(
        default=None, description="启用状态，None 表示不修改"
    )


class ShortcutResetResponse(BaseModel):
    reset_count: int
    shortcuts: list[ShortcutDto]