"""AI对话式写作辅助 Pydantic 模型."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessageDto(BaseModel):
    role: Literal["user", "assistant"] = "user"
    content: str


class WritingChatRequest(BaseModel):
    project_id: str = Field(..., description="项目ID")
    chapter_id: str = Field(..., description="章节ID")
    message: str = Field(..., description="用户消息")
    context_mode: Literal["selected", "full"] = Field("selected", description="上下文模式")
    user_ideas: str = Field("", description="作者补充说明")


class WritingChatResponse(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str = Field(..., description="回复内容")
    suggestion: str = Field("", description="下一步建议")


class WritingChatHistoryItem(BaseModel):
    chat_id: str
    chapter_id: str
    role: str
    content: str
    context_mode: str
    created_at: str


class WritingChatStreamChunk(BaseModel):
    type: Literal["chunk", "done", "progress"] = "chunk"
    content: str = ""
    suggestion: str = ""
    message: str = ""