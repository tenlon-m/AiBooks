"""爽点钩子逐章循环控制器 - 封装循环控制/暂停续写/单章调度."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker


class HookChapterController(QObject):
    """逐章生成爽点钩子的循环控制器."""

    chapter_generated = Signal(dict)
    all_done = Signal()
    error = Signal(str)
    paused = Signal(int)
    resumed_from_progress = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current_index: int = 0
        self._chapter_list: list[tuple[int, int]] = []
        self._is_paused: bool = False
        self._project_id: str = ""
        self._worker: ApiWorker | None = None
        self._workers: list[ApiWorker] = []
        self._user_ideas: str = ""
        self._generated_set: set[tuple[int, int]] = set()

    def start(self, project_id: str, chapter_list: list[tuple[int, int]], user_ideas: str = "") -> None:
        """启动逐章生成，先查询已生成进度跳过已完成章节."""
        self._project_id = project_id
        self._chapter_list = chapter_list
        self._is_paused = False
        self._current_index = 0
        self._user_ideas = user_ideas

        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/hooks/{project_id}/progress_chapter")
        worker.result.connect(self._on_progress_loaded)
        worker.error.connect(lambda _: self._begin_generation())
        self._workers.append(worker)
        worker.start()

    def _on_progress_loaded(self, data: dict) -> None:
        """查询到已生成进度后跳过已完成章节."""
        generated = data.get("generated_chapters", [])
        self._generated_set = {(v, c) for v, c in generated}
        skipped = 0
        while self._current_index < len(self._chapter_list):
            vol, ch = self._chapter_list[self._current_index]
            if (vol, ch) in self._generated_set:
                self._current_index += 1
                skipped += 1
            else:
                break
        if skipped > 0:
            self.resumed_from_progress.emit(skipped)
        if self._current_index >= len(self._chapter_list):
            self.all_done.emit()
            return
        self._begin_generation()

    def _begin_generation(self) -> None:
        """开始或继续逐章生成."""
        self._generate_next_chapter()

    def pause(self) -> None:
        """暂停（完成当前章后停止）."""
        self._is_paused = True
        self.paused.emit(self._current_index)

    def resume(self) -> None:
        """续写（从下一章继续）."""
        self._is_paused = False
        self._generate_next_chapter()

    def _generate_next_chapter(self) -> None:
        """调度下一章生成，跳过已生成章节."""
        if self._is_paused:
            return
        while self._current_index < len(self._chapter_list):
            vol, ch = self._chapter_list[self._current_index]
            if (vol, ch) in self._generated_set:
                self._current_index += 1
                continue
            break
        if self._current_index >= len(self._chapter_list):
            self.all_done.emit()
            return

        vol, ch = self._chapter_list[self._current_index]
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            f"/api/hooks/{self._project_id}/generate_chapter",
            json={"volume_no": vol, "chapter_no": ch, "user_ideas": self._user_ideas},
        )
        worker.result.connect(self._on_chapter_done)
        worker.error.connect(self._on_chapter_failed)
        self._workers.append(worker)
        worker.start()

    def _on_chapter_done(self, data: dict) -> None:
        """单章生成完成."""
        self.chapter_generated.emit(data)
        self._current_index += 1
        self._generate_next_chapter()

    def _on_chapter_failed(self, msg: str) -> None:
        """单章生成失败."""
        self.error.emit(msg)
