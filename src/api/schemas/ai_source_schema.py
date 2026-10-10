"""AI 源配置 Pydantic 模型."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AiSourceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    source_type: Literal["online_openai_compatible", "local_ollama"]
    api_endpoint: str
    model_name: str
    api_key: str | None = None
    timeout_seconds: int = 60
    max_retries: int = 3
    priority: int = 1
    weight: int = 1
    enabled: bool = True
    tags: list[str] = []
    task_tags: list[str] = Field(
        default_factory=list,
        description="适用任务标签，如 ['outline','writing']；空表示不限制（通用兜底源）",
    )


class AiSourceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    source_type: Literal["online_openai_compatible", "local_ollama"] | None = None
    api_endpoint: str | None = None
    model_name: str | None = None
    api_key: str | None = Field(default=None, description="留空(None)表示不修改原值；传非空字符串则替换为新Key；传空字符串则清空Key")
    timeout_seconds: int | None = None
    max_retries: int | None = None
    priority: int | None = None
    weight: int | None = None
    enabled: bool | None = None
    tags: list[str] | None = None
    task_tags: list[str] | None = Field(
        default=None,
        description="适用任务标签；None 表示不修改；空列表表示清空任务限制",
    )


class AiSourceDto(BaseModel):
    source_id: str
    name: str
    source_type: str
    api_endpoint: str
    model_name: str
    priority: int
    weight: int
    enabled: bool
    health_status: str
    last_check_at: datetime | None
    success_count: int
    fail_count: int
    tags: list[str] = Field(default_factory=list, description="展示标签（不含 task: 前缀）")
    task_tags: list[str] = Field(default_factory=list, description="适用任务标签（module 名），空表示不限制")


class RoutingPolicyRequest(BaseModel):
    strategy: Literal["manual", "failover", "load_balance", "cost_first"]
    manual_source_id: str | None = None
    health_check_interval_seconds: int = 30
    circuit_break_threshold: int = 3
    circuit_break_cool_seconds: int = 60
    failover_within_retry: bool = True


class RoutingPolicyDto(BaseModel):
    policy_id: str
    strategy: str
    manual_source_id: str | None
    health_check_interval_seconds: int
    circuit_break_threshold: int
    circuit_break_cool_seconds: int
    failover_within_retry: bool


class ModelProfileDto(BaseModel):
    """模型特点档案 - 测试连接时返回，辅助用户配置适用任务."""

    model_name: str
    family: str = Field(description="模型族，如 通义千问 / DeepSeek")
    scale: str = Field(description="参数量级，如 32B")
    speed: str = Field(description="速度评级，如 中等偏慢")
    quality: str = Field(description="质量评级，如 高")
    is_reasoning: bool = Field(default=False, description="是否推理型模型（慢而强）")
    is_lightweight: bool = Field(default=False, description="是否轻量快模型")
    is_flagship: bool = Field(default=False, description="是否大型旗舰模型")
    strengths: list[str] = Field(default_factory=list, description="中文特点列表")
    recommended_tasks: list[str] = Field(default_factory=list, description="推荐勾选的适用任务(module 名)")
    recommend_as_fallback: bool = Field(default=False, description="是否建议作为通用兜底源")
    summary: str = Field(default="", description="综合中文总述")
    advice: str = Field(default="", description="配置建议")
    positioning: str = Field(default="", description="模型定位（中文一句话）")
    matched_by: str = Field(default="heuristic", description="识别来源：known(已知模型) / heuristic(启发式推断)")


class AiSourceTestResponse(BaseModel):
    source_id: str
    success: bool
    message: str
    latency_ms: int | None = Field(default=None, description="测试连接实测耗时(毫秒)")
    model_profile: ModelProfileDto | None = Field(default=None, description="模型特点档案与任务推荐")

class OllamaModelsResponse(BaseModel):
    models: list[str] = []
    error: str | None = None

class ActiveAiSourceResponse(BaseModel):
    display_text: str
    strategy: str
    source_count: int = 0