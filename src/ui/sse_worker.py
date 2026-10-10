"""SSE 流式工作线程 - 读取撰写进度流并发射事件."""
from __future__ import annotations

import json

import httpx
from PySide6.QtCore import QThread, Signal

from src.config.settings import get_config
from src.utils.logger import get_logger

_running_sse_workers: set[QThread] = set()


class SseWritingWorker(QThread):
    """连接 /api/writing/{project_id}/progress 的 SSE 流，解析进度事件."""

    event = Signal(dict)
    error = Signal(str)
    finished_ok = Signal()

    def __init__(self, project_id: str, style_library_id: str | None = None, user_ideas: str = "") -> None:
        super().__init__()
        config = get_config()
        self._url = f"http://{config.api_host}:{config.api_port}/api/writing/{project_id}/progress"
        from urllib.parse import quote
        params: list[str] = []
        if style_library_id:
            params.append(f"style_library_id={style_library_id}")
        if user_ideas:
            params.append(f"user_ideas={quote(user_ideas)}")
        if params:
            self._url += "?" + "&".join(params)
        self._logger = get_logger()
        self._stop = False
        self._client: httpx.Client | None = None
        self.finished.connect(self._release)

    def start(self, *args: object, **kwargs: object) -> None:
        _running_sse_workers.add(self)
        super().start(*args, **kwargs)

    def _release(self) -> None:
        _running_sse_workers.discard(self)
        self.deleteLater()

    def stop(self) -> None:
        self._stop = True
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass


    def run(self) -> None:
        try:
            self._client = httpx.Client(timeout=None)
            with self._client as client:
                with client.stream("GET", self._url) as resp:
                    if resp.status_code != 200:
                        self.error.emit(f"SSE连接失败: HTTP {resp.status_code}")
                        return
                    for line in resp.iter_lines():
                        if self._stop:
                            break
                        if not line or not line.startswith("data: "):
                            continue
                        raw = line[6:]
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        status = data.get("status", "")
                        self.event.emit(data)
                        if status in ("completed", "failed", "paused"):
                            self.finished_ok.emit()
                            return
        except Exception as e:
            if not self._stop:
                self.error.emit(f"SSE读取异常: {e}")


class SsePostWorker(QThread):
    """通用 POST/GET SSE 工作线程，用于流式接收 AI 生成 chunk.

    支持的 SSE 事件字段（兼容多种后端格式）：
      - chunk / text / delta / content : 文本增量，通过 chunk 信号发射
      - status : completed/failed/done/error 时结束
      - 任意结构 : 通过 event 信号原样发射

    注意：多数后端的流式响应并不带 status 字段（例如 EmotionStreamChunk 用
    type 字段表示 progress/chunk/done），这种情况下不会提前结束，
    而是在流正常读完后由 finished_ok 结束，调用方应按后端实际字段解析 event。

    用法:
        worker = SsePostWorker("/api/text-transform/continue/stream", payload={"...": ...})
        worker.chunk.connect(on_chunk)
        worker.event.connect(on_event)
        worker.finished_ok.connect(on_done)
        worker.error.connect(on_error)
        worker.start()
    """

    chunk = Signal(str)
    event = Signal(dict)
    error = Signal(str)
    finished_ok = Signal()

    def __init__(
        self,
        path: str,
        payload: dict | None = None,
        method: str = "POST",
    ) -> None:
        super().__init__()
        config = get_config()
        self._url = f"http://{config.api_host}:{config.api_port}{path}"
        self._payload = payload
        self._method = method.upper()
        self._logger = get_logger()
        self._stop = False
        self._client: httpx.Client | None = None
        self.finished.connect(self._release)

    def start(self, *args: object, **kwargs: object) -> None:
        _running_sse_workers.add(self)
        super().start(*args, **kwargs)

    def _release(self) -> None:
        _running_sse_workers.discard(self)
        self.deleteLater()

    def stop(self) -> None:
        self._stop = True
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass


    def run(self) -> None:
        try:
            self._client = httpx.Client(timeout=None)
            with self._client as client:
                kwargs: dict = {}
                if self._payload is not None and self._method in ("POST", "PUT"):
                    kwargs["json"] = self._payload
                with client.stream(self._method, self._url, **kwargs) as resp:
                    if resp.status_code != 200:
                        body = resp.read().decode(errors="replace")[:500]
                        self.error.emit(
                            f"SSE连接失败: HTTP {resp.status_code} {body}"
                        )
                        return
                    for line in resp.iter_lines():
                        if self._stop:
                            break
                        if not line:
                            continue
                        if line.startswith("data: "):
                            raw = line[6:]
                        elif line.startswith("event:"):
                            continue
                        else:
                            continue
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        chunk_text = (
                            data.get("chunk")
                            or data.get("text")
                            or data.get("delta")
                            or data.get("content")
                            or ""
                        )
                        status = data.get("status", "") or data.get("type", "")
                        is_complete = status in ("completed", "failed", "done", "error")
                        if isinstance(chunk_text, str) and chunk_text and not is_complete:
                            self.chunk.emit(chunk_text)
                        self.event.emit(data)
                        if is_complete:
                            self.finished_ok.emit()
                            return
                    if not self._stop:
                        self.finished_ok.emit()
        except httpx.ConnectError as e:
            if not self._stop:
                self.error.emit(f"SSE连接异常: 无法连接后端服务 ({e})")
        except Exception as e:
            if not self._stop:
                self.error.emit(f"SSE读取异常: {e}")

class OutlineRepairSseWorker(SsePostWorker):
    """大纲 AI 一键修复 SSE worker - 复用 SsePostWorker 流式读取."""

    def __init__(
        self,
        project_id: str,
        issues: list[dict],
        repair_scope: str = "all",
        garbled_config: dict | None = None,
    ) -> None:
        payload: dict = {"issues": issues, "repair_scope": repair_scope}
        if garbled_config is not None:
            payload["garbled_config"] = garbled_config
        super().__init__(
            f"/api/outlines/{project_id}/repair/stream",
            payload=payload,
        )

class HookRepairSseWorker(SsePostWorker):
    """爽点钩子 AI 一键修复 SSE worker - 复用 SsePostWorker 流式读取."""

    def __init__(
        self,
        project_id: str,
        issues: list[dict],
        repair_scope: str = "all",
        garbled_config: dict | None = None,
    ) -> None:
        payload: dict = {"issues": issues, "repair_scope": repair_scope}
        if garbled_config is not None:
            payload["garbled_config"] = garbled_config
        super().__init__(
            f"/api/hooks/{project_id}/repair/stream",
            payload=payload,
        )

class WritingRepairSseWorker(SsePostWorker):
    """撰写 AI 一键修复 SSE worker - 复用 SsePostWorker 流式读取."""

    def __init__(
        self,
        project_id: str,
        issues: list[dict],
        repair_scope: str = "all",
        garbled_config: dict | None = None,
    ) -> None:
        payload: dict = {"issues": issues, "repair_scope": repair_scope}
        if garbled_config is not None:
            payload["garbled_config"] = garbled_config
        super().__init__(
            f"/api/writing/{project_id}/repair/stream",
            payload=payload,
        )

class WritingFillSseWorker(SsePostWorker):
    """批量补写字数不足章节 SSE worker - 复用 SsePostWorker 流式读取."""

    def __init__(self, project_id: str, garbled_config: dict | None = None) -> None:
        payload: dict | None = None
        if garbled_config is not None:
            payload = {"garbled_config": garbled_config}
        super().__init__(
            f"/api/writing/{project_id}/fill/stream",
            payload=payload,
            method="POST",
        )