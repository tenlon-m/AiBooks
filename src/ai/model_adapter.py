"""模型统一适配层 - 按 source_type 分派到对应 adapter."""
from __future__ import annotations

from typing import Any

from src.ai.adapters.ollama import OllamaAdapter
from src.ai.adapters.openai_compatible import OpenAiCompatibleAdapter
from src.db.models import AiSource
from src.utils.logger import get_logger


class ModelAdapter:
    """统一适配入口，按 AiSource.source_type 分派."""

    def __init__(self) -> None:
        self.logger = get_logger()

    def create_adapter(self, source: AiSource) -> OpenAiCompatibleAdapter:
        """根据 AiSource 创建对应适配器实例."""
        if source.source_type == "local_ollama":
            return OllamaAdapter(
                source_id=source.source_id,
                name=source.name,
                model_name=source.model_name,
                endpoint=source.api_endpoint,
                timeout=source.timeout_seconds,
            )
        elif source.source_type == "online_openai_compatible":
            return OpenAiCompatibleAdapter(
                source_id=source.source_id,
                name=source.name,
                endpoint=source.api_endpoint,
                model_name=source.model_name,
                api_key_enc=source.api_key_enc,
                timeout=source.timeout_seconds,
            )
        else:
            raise ValueError(f"不支持的 source_type: {source.source_type}")

    async def call(
        self,
        source: AiSource,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.8,
        max_tokens: int = 4096,
        **extra: Any,
    ) -> dict[str, Any]:
        """统一调用接口."""
        adapter = self.create_adapter(source)
        return await adapter.chat_completion(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra,
        )

    async def health_check(self, source: AiSource) -> bool:
        """健康探测，失败时抛出异常携带原因."""
        adapter = self.create_adapter(source)
        return await adapter.health_check()


_adapter: ModelAdapter | None = None


def get_model_adapter() -> ModelAdapter:
    global _adapter
    if _adapter is None:
        _adapter = ModelAdapter()
    return _adapter