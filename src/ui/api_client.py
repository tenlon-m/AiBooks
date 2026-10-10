"""API 客户端 - httpx 同步封装，供 UI 线程通过 Worker 调用."""
from __future__ import annotations

import httpx

from src.config.settings import get_config
from src.utils.logger import get_logger


class ApiClient:
    """后端 REST API 同步客户端."""

    def __init__(self) -> None:
        config = get_config()
        self._base_url = f"http://{config.api_host}:{config.api_port}"
        self._client = httpx.Client(base_url=self._base_url, timeout=120.0)
        self._logger = get_logger()

    def _request(self, method: str, path: str, **kwargs) -> dict | list:
        try:
            resp = self._client.request(method, path, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", "")
            except Exception:
                detail = e.response.text
            raise RuntimeError(f"API {e.response.status_code}: {detail}") from e
        except httpx.ConnectError as e:
            raise RuntimeError(f"无法连接后端服务 ({self._base_url})，请确认服务已启动") from e
        except Exception as e:
            raise RuntimeError(f"请求失败: {e}") from e

    def get(self, path: str, **kwargs) -> dict | list:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> dict | list:
        return self._request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> dict | list:
        return self._request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs) -> dict | list:
        return self._request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> dict | list:
        return self._request("DELETE", path, **kwargs)

    def close(self) -> None:
        self._client.close()


_client: ApiClient | None = None


def get_api_client() -> ApiClient:
    global _client
    if _client is None:
        _client = ApiClient()
    return _client