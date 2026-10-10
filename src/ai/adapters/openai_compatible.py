"""OpenAI 兼容适配器 - 适配所有 OpenAI 兼容端点."""
from __future__ import annotations

import time
from typing import Any

import httpx

from src.config.crypto import decrypt_secret
from src.utils.logger import get_logger


class OpenAiCompatibleAdapter:
    """适配 OpenAI 兼容协议的 AI 源.

    统一请求/响应模型，屏蔽 model、messages、temperature、max_tokens 参数差异。
    """

    def __init__(
        self,
        source_id: str,
        name: str,
        endpoint: str,
        model_name: str,
        api_key_enc: bytes | None = None,
        timeout: int = 60,
    ) -> None:
        self.source_id = source_id
        self.name = name
        self.endpoint = endpoint.rstrip("/")
        self.model_name = model_name
        self.api_key_enc = api_key_enc
        self.timeout = timeout
        self.logger = get_logger()

    def _get_api_key(self) -> str | None:
        if self.api_key_enc is None:
            return None
        try:
            return decrypt_secret(self.api_key_enc)
        except Exception as e:
            self.logger.warning(
                f"API Key 解密失败（密钥文件与数据库可能不匹配）: {e}"
            )
            raise RuntimeError(
                "API Key 解密失败：密钥文件(.secret_key)与数据库不匹配，请重新填写 API Key"
            ) from e

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self._get_api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def chat_completion(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.8,
        max_tokens: int = 4096,
        **extra: Any,
    ) -> dict[str, Any]:
        """调用 chat completions 接口.

        extra 中的 timeout_seconds 按场景覆盖默认超时（秒），不会混入请求体。

        Returns:
            包含 content、usage、raw 的字典
        Raises:
            httpx 异常或 RuntimeError
        """
        # 业务侧按场景传入的超时（如 outline/writing），需从请求参数中取出后生效
        timeout_seconds = extra.pop("timeout_seconds", None)
        request_timeout = int(timeout_seconds) if timeout_seconds else self.timeout

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **extra,
        }

        url = f"{self.endpoint}/chat/completions"
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=request_timeout) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            if resp.status_code == 401:
                raise RuntimeError("API Key 无效或已过期（HTTP 401），请重新填写 API Key")
            if resp.status_code >= 400:
                detail = ""
                try:
                    err_body = resp.json()
                    detail = (
                        err_body.get("error", {}).get("message", "")
                        or err_body.get("message", "")
                        or err_body.get("detail", "")
                        or str(err_body)
                    )
                except Exception:
                    detail = resp.text[:500]
                raise RuntimeError(
                    f"AI 接口返回 HTTP {resp.status_code}: {detail}"
                )
            data = resp.json()

        duration_ms = int((time.monotonic() - start) * 1000)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})

        return {
            "content": content,
            "usage": usage,
            "duration_ms": duration_ms,
            "raw": data,
        }

    async def health_check(self) -> bool:
        """轻量探测（1 token 补全），失败时抛出异常携带原因."""
        url = f"{self.endpoint}/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            if resp.status_code == 200:
                return True
            if resp.status_code == 401:
                raise RuntimeError("API Key 无效或已过期（HTTP 401），请重新填写 API Key")
            detail = ""
            try:
                err_body = resp.json()
                detail = (
                    err_body.get("error", {}).get("message", "")
                    or err_body.get("message", "")
                    or err_body.get("detail", "")
                    or str(err_body)
                )
            except Exception:
                detail = resp.text[:300]
            raise RuntimeError(f"HTTP {resp.status_code}: {detail}")