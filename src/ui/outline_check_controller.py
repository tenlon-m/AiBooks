"""大纲一致性校验控制器 - 逐批校验并汇总为可复制报告."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from src.config.settings import get_config
from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker

# 问题严重程度排序：严重的排前面
_LEVEL_ORDER = {"严重": 0, "一般": 1, "轻微": 2}


class OutlineCheckController(QObject):
    """大纲一致性校验的逐批调度器.

    与分批生成对称：每次只校验一批（若干章），避免整本大纲一次校验超时；
    全部批次结束后汇总为一份文本报告（评分 + 问题清单 + 未出场人物统计），
    报告通过可复制的消息弹窗展示。
    """

    progress = Signal(int, int)
    all_done = Signal(dict)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        config = get_config()
        self._batch_size: int = max(1, config.outline_batch_chapters)
        self._http_timeout: float = float(config.outline_batch_timeout_seconds * 2 + 60)
        self._project_id: str = ""
        self._batches: list[dict] = []
        self._index: int = 0
        self._results: list[dict] = []
        self._outline: dict = {}
        self._characters: list[dict] = []
        self._workers: list[ApiWorker] = []

    def start(self, project_id: str) -> None:
        """开始校验：先加载大纲与已确认人物清单，再逐批校验."""
        self._project_id = project_id
        self._batches = []
        self._index = 0
        self._results = []
        self._outline = {}
        self._characters = []

        client = get_api_client()
        worker = ApiWorker(self._fetch_all, client, project_id)
        worker.result.connect(self._on_loaded)
        worker.error.connect(self.error.emit)
        self._workers.append(worker)
        worker.start()

    @staticmethod
    def _fetch_all(client: Any, project_id: str) -> dict:
        """拉取大纲与人物清单（在 worker 线程内同步执行）."""
        return {
            "outline": client.get(f"/api/outlines/{project_id}") or {},
            "characters": client.get(f"/api/characters/{project_id}") or [],
        }

    def _on_loaded(self, data: dict) -> None:
        self._outline = data.get("outline") or {}
        self._characters = [
            c for c in (data.get("characters") or []) if c.get("confirmed")
        ]
        self._batches = self._build_batches(self._outline)
        if not self._batches:
            self.error.emit("大纲中暂无可校验的已生成章节，请先生成大纲")
            return
        self.progress.emit(0, len(self._batches))
        self._check_next_batch()

    def _build_batches(self, outline: dict) -> list[dict]:
        """按已生成章节（有梗概）切分批次，未生成章节不参与校验."""
        batches: list[dict] = []
        for vol in outline.get("volumes", []) or []:
            volume_no = int(vol.get("volume_no", 0) or 0)
            chapter_nos = sorted(
                int(ch.get("chapter_no", 0))
                for ch in (vol.get("chapters") or [])
                if (ch.get("synopsis_points") or "").strip()
            )
            for start in range(0, len(chapter_nos), self._batch_size):
                chunk = chapter_nos[start : start + self._batch_size]
                # 章号不连续时按单章校验，避免把空洞当成连续区间
                if chunk and chunk[-1] - chunk[0] + 1 != len(chunk):
                    batches.extend(
                        {
                            "volume_no": volume_no,
                            "chapter_start": chapter_no,
                            "chapter_count": 1,
                        }
                        for chapter_no in chunk
                    )
                    continue
                if chunk:
                    batches.append(
                        {
                            "volume_no": volume_no,
                            "chapter_start": chunk[0],
                            "chapter_count": len(chunk),
                        }
                    )
        return batches

    def _check_next_batch(self) -> None:
        if self._index >= len(self._batches):
            self.all_done.emit(self._build_report())
            return
        batch = self._batches[self._index]
        client = get_api_client()
        worker = ApiWorker(
            client.post,
            f"/api/outlines/{self._project_id}/check_consistency",
            json={
                "volume_no": batch["volume_no"],
                "chapter_start": batch["chapter_start"],
                "chapter_count": batch["chapter_count"],
            },
            timeout=self._http_timeout,
        )
        worker.result.connect(self._on_batch_done)
        worker.error.connect(self.error.emit)
        self._workers.append(worker)
        worker.start()

    def _on_batch_done(self, data: dict) -> None:
        result = dict(data or {})
        result["volume_no"] = self._batches[self._index]["volume_no"]
        self._results.append(result)
        self._index += 1
        self.progress.emit(self._index, len(self._batches))
        self._check_next_batch()

    def _build_report(self) -> dict:
        """汇总各批结果，生成问题清单与文本报告."""
        issues: list[dict] = []
        checked_chapters = 0
        score_sum = 0
        for item in self._results:
            score_sum += int(item.get("score", 0) or 0)
            checked_chapters += int(item.get("checked_chapter_count", 0) or 0)
            for issue in item.get("issues", []) or []:
                merged = dict(issue)
                merged["volume_no"] = item.get("volume_no", 0)
                issues.append(merged)

        issues.extend(self._build_character_coverage_issues())
        issues.sort(
            key=lambda issue: (
                _LEVEL_ORDER.get(str(issue.get("level", "")), 9),
                int(issue.get("volume_no", 0) or 0),
                int(issue.get("chapter_no", 0) or 0),
            )
        )
        average = round(score_sum / len(self._results)) if self._results else 0
        missing = self._find_missing_characters()
        return {
            "batch_count": len(self._results),
            "score": average,
            "checked_chapter_count": checked_chapters,
            "issues": issues,
            "missing_characters": missing,
            "text": self._format_text(average, checked_chapters, issues, missing),
        }

    def _build_character_coverage_issues(self) -> list[dict]:
        """全书级人物未出场校验：已确认人物未在任何章节出场人物中登记."""
        parts: list[str] = []
        for vol in self._outline.get("volumes", []) or []:
            for ch in vol.get("chapters") or []:
                parts.append(str(ch.get("characters_appearing") or ""))
        haystack = " ".join(parts)

        coverage_issues: list[dict] = []
        for char in self._characters:
            name = str(char.get("name") or "").strip()
            if name and name not in haystack:
                coverage_issues.append(
                    {
                        "level": "一般",
                        "chapter_no": 0,
                        "type": "人物未出场",
                        "detail": f"已确认人物「{name}」未在任何章节出场人物中登记",
                        "suggestion": "请确认该人物在后续情节中的出场安排，或从已确认人物列表中移除",
                        "volume_no": 0,
                    }
                )
        return coverage_issues

    def _find_missing_characters(self) -> list[dict]:
        """统计全书大纲中从未登记出场、也未在梗概中提及的已确认人物."""
        parts: list[str] = []
        for vol in self._outline.get("volumes", []) or []:
            for ch in vol.get("chapters") or []:
                parts.append(str(ch.get("characters_appearing") or ""))
                parts.append(str(ch.get("synopsis_points") or ""))
        haystack = " ".join(parts)

        missing: list[dict] = []
        for char in self._characters:
            name = str(char.get("name") or "").strip()
            if name and name not in haystack:
                missing.append(
                    {"name": name, "identity": str(char.get("identity") or "")}
                )
        return missing

    @staticmethod
    def _format_text(
        score: int, checked: int, issues: list[dict], missing: list[dict]
    ) -> str:
        """生成便于整段复制的纯文本报告."""
        lines = [
            f"整体一致性评分：{score} / 100（分数越低表示与梗概/世界观/人物设定偏差越大）",
            f"已校验章节：{checked} 章",
            "",
        ]
        if issues:
            lines.append(f"发现问题：{len(issues)} 条")
            lines.append("=" * 44)
            for idx, issue in enumerate(issues, 1):
                lines.append(
                    f"[{idx}]【{issue.get('level') or '提示'}】"
                    f"第{issue.get('volume_no')}卷第{issue.get('chapter_no')}章"
                    f"（{issue.get('type') or '其他'}）"
                )
                lines.append(f"    问题：{issue.get('detail') or ''}")
                if issue.get("suggestion"):
                    lines.append(f"    建议：{issue.get('suggestion')}")
                lines.append("")
        else:
            lines.append("未发现问题：大纲与梗概、世界观、人物设定基本一致。")
            lines.append("")

        if missing:
            lines.append("=" * 44)
            lines.append(f"未在大纲中出场的人物（{len(missing)} 个）：")
            for item in missing:
                lines.append(f"    - {item['name']}（{item['identity']}）")
            lines.append("")
            lines.append("提示：请确认其在后续情节中的出场安排，或在对应章节补充登场。")
        return "\n".join(lines)
