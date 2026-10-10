"""大纲分批生成控制器 - 按批调度生成、暂停/续写、增量结果推送."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from src.config.settings import get_config
from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker


class OutlineBatchController(QObject):
    """大纲分批生成的循环控制器.

    将全书章节按每批 N 章切分后逐批调用后端生成，每批返回后立即把最新大纲
    推送回界面展示，再继续下一批；批次之间可暂停/续写。
    已生成章节会被跳过，因此"续写"只补齐缺失批次。
    """

    batch_done = Signal(dict)
    progress = Signal(int, int)
    all_done = Signal(bool)
    error = Signal(str)
    paused = Signal(int)
    resumed_from_progress = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        config = get_config()
        self._batch_size: int = max(1, config.outline_batch_chapters)
        # 单批可能经历多次重试 + 跨源 failover：服务端单批 AI 最坏 ≈
        # outline_batch_timeout_seconds × (max_retries+1) × N源
        # 例：90s × 4 × 2 源 ≈ 720s，UI 侧 HTTP 超时需大于该最坏值。
        # 原 240s（=90×2+60）远不够，导致用户看到“请求失败: timed out”
        # 而服务端其实还在跑——批次是“成功的”，只是被客户端无谓掐断。
        # 调至 900s（15 分钟）覆盖最坏跨源重试链，并留充足缓冲。
        self._http_timeout: float = 900.0
        self._project_id: str = ""
        self._volume_count: int = 1
        self._chapters_per_volume: int = 1
        self._reset: bool = False
        self._reset_pending: bool = False
        self._total_chapters: int = 0
        self._batches: list[dict] = []
        self._pending: list[dict] = []
        self._current_index: int = 0
        self._is_paused: bool = False
        self._filled: set[tuple[int, int]] = set()
        self._workers: list[ApiWorker] = []
        self._user_ideas: str = ""

    def _add_worker(self, worker) -> None:
        """注册 ApiWorker 并在完成后自动清理."""
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))

    def _cleanup_worker(self, worker) -> None:
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()


    def start(
        self,
        project_id: str,
        volume_count: int,
        chapters_per_volume: int,
        reset: bool,
        batch_size: int | None = None,
        user_ideas: str = "",
    ) -> None:
        """启动分批生成：先读取已有大纲，跳过已完成批次（实现续写）."""
        self._project_id = project_id
        self._volume_count = max(1, int(volume_count or 1))
        self._chapters_per_volume = max(1, int(chapters_per_volume or 1))
        self._reset = reset
        self._reset_pending = reset
        self._user_ideas = user_ideas or ""
        if batch_size:
            self._batch_size = max(1, int(batch_size))
        self._batch_size = min(self._batch_size, self._chapters_per_volume)
        self._total_chapters = self._volume_count * self._chapters_per_volume
        self._is_paused = False
        self._current_index = 0
        self._filled = set()

        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/outlines/{project_id}")
        worker.result.connect(self._on_existing_loaded)
        worker.error.connect(lambda _: self._on_existing_loaded(None))
        self._add_worker(worker)
        worker.start()

    def pause(self) -> None:
        """暂停（当前批完成后停止）."""
        self._is_paused = True
        self.paused.emit(self.completed_count)

    def resume(self) -> None:
        """续写（从下一个未完成批次继续）."""
        self._is_paused = False
        self._generate_next_batch()

    @property
    def completed_count(self) -> int:
        return len(self._filled)

    @property
    def total_count(self) -> int:
        return self._total_chapters

    def _on_existing_loaded(self, data: dict | None) -> None:
        """载入已有大纲后重建批次计划，跳过已完成批次."""
        self._filled = set() if self._reset else self._extract_filled(data)
        self._batches = self._build_batches()
        self._pending = [b for b in self._batches if not self._is_batch_filled(b)]
        self._current_index = 0

        skipped = len(self._batches) - len(self._pending)
        if skipped > 0:
            self.resumed_from_progress.emit(skipped)
        self.progress.emit(self.completed_count, self._total_chapters)

        if not self._pending:
            self.all_done.emit(True)
            return
        self._generate_next_batch()

    def _generate_next_batch(self) -> None:
        """调度下一批生成."""
        if self._is_paused:
            return
        if self._current_index >= len(self._pending):
            self.all_done.emit(self._is_complete())
            return

        batch = self._pending[self._current_index]
        payload = {
            "volume_no": batch["volume_no"],
            "chapter_start": batch["chapter_start"],
            "chapter_count": batch["chapter_count"],
            "reset": self._reset_pending,
            "user_ideas": self._user_ideas,
        }
        self._reset_pending = False

        client = get_api_client()
        worker = ApiWorker(
            client.post,
            f"/api/outlines/{self._project_id}/generate_batch",
            json=payload,
            timeout=self._http_timeout,
        )
        worker.result.connect(self._on_batch_done)
        worker.error.connect(self._on_batch_failed)
        self._add_worker(worker)
        worker.start()

    def _on_batch_done(self, data: dict) -> None:
        """单批生成完成：刷新进度并继续下一批."""
        self._filled |= self._extract_filled(data)
        self._current_index += 1
        self.batch_done.emit(data)
        self.progress.emit(self.completed_count, self._total_chapters)
        self._generate_next_batch()

    def _on_batch_failed(self, msg: str) -> None:
        """单批生成失败：停在当前批，用户可点击续写重试该批."""
        self.error.emit(msg)
        self.paused.emit(self.completed_count)

    def _build_batches(self) -> list[dict]:
        """按每批 N 章切分全书章节（不跨卷）."""
        batches: list[dict] = []
        for volume_no in range(1, self._volume_count + 1):
            start = 1
            while start <= self._chapters_per_volume:
                count = min(
                    self._batch_size, self._chapters_per_volume - start + 1
                )
                batches.append(
                    {
                        "volume_no": volume_no,
                        "chapter_start": start,
                        "chapter_count": count,
                    }
                )
                start += count
        return batches

    def _is_batch_filled(self, batch: dict) -> bool:
        """该批章节是否都已生成梗概要点."""
        return all(
            (batch["volume_no"], chapter_no) in self._filled
            for chapter_no in range(
                batch["chapter_start"],
                batch["chapter_start"] + batch["chapter_count"],
            )
        )

    def _is_complete(self) -> bool:
        return all(self._is_batch_filled(batch) for batch in self._batches)

    @staticmethod
    def _extract_filled(data: dict | None) -> set[tuple[int, int]]:
        """从大纲响应中提取已生成梗概要点的章节集合."""
        filled: set[tuple[int, int]] = set()
        if not data:
            return filled
        for vol in data.get("volumes", []) or []:
            volume_no = vol.get("volume_no")
            if volume_no is None:
                continue
            for ch in vol.get("chapters", []) or []:
                if (ch.get("synopsis_points") or "").strip():
                    filled.add((int(volume_no), int(ch.get("chapter_no", 0))))
        return filled
