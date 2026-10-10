"""Ollama 适配器 - 继承 OpenAI 兼容适配器."""
from __future__ import annotations

from src.ai.adapters.openai_compatible import OpenAiCompatibleAdapter


class OllamaAdapter(OpenAiCompatibleAdapter):
    """Ollama 本地大模型适配器.

    Ollama 提供 OpenAI 兼容端点（默认 http://localhost:11434/v1），
    api_key 可空。
    """

    DEFAULT_ENDPOINT = "http://localhost:11434/v1"

    def __init__(
        self,
        source_id: str,
        name: str,
        model_name: str,
        endpoint: str | None = None,
        timeout: int = 120,
        **kwargs,
    ) -> None:
        super().__init__(
            source_id=source_id,
            name=name,
            endpoint=endpoint or self.DEFAULT_ENDPOINT,
            model_name=model_name,
            api_key_enc=None,
            timeout=timeout,
        )