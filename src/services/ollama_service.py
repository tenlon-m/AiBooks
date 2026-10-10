"""Ollama 模型动态发现服务 - 查询 Ollama 服务获取实际已安装模型列表."""
from __future__ import annotations

import httpx

from src.utils.logger import get_logger


class OllamaService:
    """Ollama 模型列表查询服务，无状态无缓存，每次实时查询."""

    def __init__(self) -> None:
        self.logger = get_logger()

    @staticmethod
    def _derive_base_url(endpoint: str) -> str:
        """将 OpenAI 兼容端点推导为 Ollama 原生 base URL（去掉 /v1 后缀）."""
        url = endpoint.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        return url

    async def list_models(self, endpoint: str) -> dict[str, list[str] | str | None]:
        """查询指定 Ollama 服务上已安装的模型列表.

        Returns:
            {"models": [...], "error": None|str}
        """
        base_url = self._derive_base_url(endpoint)
        tags_url = f"{base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(tags_url)
                if resp.status_code != 200:
                    return {"models": [], "error": f"Ollama服务返回HTTP {resp.status_code}"}
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
                if not models:
                    return {"models": [], "error": "Ollama服务上未安装任何模型，请先拉取模型后再选择"}
                return {"models": models, "error": None}
        except httpx.ConnectError:
            return {"models": [], "error": "无法连接Ollama服务，请确认Ollama已启动"}
        except httpx.TimeoutException:
            return {"models": [], "error": "连接Ollama服务超时（5秒），请确认服务正常"}
        except Exception as e:
            self.logger.error(f"查询Ollama模型列表异常: {e}")
            return {"models": [], "error": f"查询失败: {e}"}