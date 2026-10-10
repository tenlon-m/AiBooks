"""大纲构建器 - 提示词构建与响应解析."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.garbled_normalizer import GarbledConfig

from typing import Any

from src.ai.gateway import get_gateway
from src.api.schemas.character_schema import CharacterDto
from src.api.schemas.outline_schema import (
    ChapterDraft,
    OutlineConsistencyIssue,
    OutlineConsistencyResult,
    OutlineDraft,
    VolumeBatchDraft,
    VolumeDraft,
)
from src.utils.logger import get_logger


class OutlineBuilder:
    """大纲提示词构建与响应解析器."""

    def __init__(self) -> None:
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def build_and_call(
        self,
        synopsis: str,
        worldview: str,
        characters: list[CharacterDto],
        volume_count: int,
        chapters_per_volume: int,
        words_per_chapter: int,
        project_id: str,
        timeout_seconds: int = 120,
        user_ideas: str = "",
        naming_favorites: dict[str, list[str]] | None = None,
    ) -> OutlineDraft:
        """构建提示词并调用 AI 生成大纲."""
        result = await self.gateway.call_and_parse(
            module="outline",
            scene="generate-outline",
            params={
                "synopsis": synopsis,
                "worldview": worldview,
                "characters": [c.model_dump() for c in characters],
                "volume_count": volume_count,
                "chapters_per_volume": chapters_per_volume,
                "words_per_chapter": words_per_chapter,
                "synopsis_min_chars": 100,
                "synopsis_max_chars": 300,
                "user_ideas": user_ideas,
                "naming_favorites": naming_favorites or {},
            },
            project_id=project_id,
            timeout_seconds=timeout_seconds,
        )
        parsed = result.get("parsed", {})
        return self.parse_response(parsed)

    async def build_batch_and_call(
        self,
        synopsis: str,
        worldview: str,
        characters: list[CharacterDto],
        volume_count: int,
        chapters_per_volume: int,
        words_per_chapter: int,
        batch_volume_no: int,
        batch_volume_name: str,
        batch_chapter_start: int,
        batch_chapter_count: int,
        prev_chapters: list[dict],
        generated_chapter_count: int,
        project_id: str,
        timeout_seconds: int = 120,
        user_ideas: str = "",
        naming_favorites: dict[str, list[str]] | None = None,
        all_volume_names: dict[int, str] | None = None,
    ) -> VolumeBatchDraft:
        """构建分批提示词并调用 AI 生成单批章节大纲。

        每批仅生成若干章，单次输出长度大幅缩短，避免整本大纲一次生成而超时。
        """
        total_chapter_count = volume_count * chapters_per_volume
        result = await self.gateway.call_and_parse(
            module="outline",
            scene="generate-outline-batch",
            params={
                "synopsis": synopsis,
                "worldview": worldview,
                "characters": [c.model_dump() for c in characters],
                "volume_count": volume_count,
                "chapters_per_volume": chapters_per_volume,
                "words_per_chapter": words_per_chapter,
                "total_chapter_count": total_chapter_count,
                "generated_chapter_count": generated_chapter_count,
                "batch_volume_no": batch_volume_no,
                "batch_volume_name": batch_volume_name,
                "batch_chapter_start": batch_chapter_start,
                "batch_chapter_count": batch_chapter_count,
                "prev_chapters": prev_chapters,
                "all_volume_names": all_volume_names or {},
                "synopsis_min_chars": 100,
                "synopsis_max_chars": 300,
                "user_ideas": user_ideas,
                "naming_favorites": naming_favorites or {},
            },
            project_id=project_id,
            timeout_seconds=timeout_seconds,
        )
        return self.parse_batch_response(
            result.get("parsed", {}),
            default_volume_no=batch_volume_no,
            default_chapter_start=batch_chapter_start,
            chapter_count=batch_chapter_count,
        )

    def parse_batch_response(
        self,
        raw: str | dict,
        default_volume_no: int,
        default_chapter_start: int,
        chapter_count: int,
    ) -> VolumeBatchDraft:
        """解析单批返回 JSON，并把章节号收敛到本批请求范围内."""
        data = self._load_json(raw)
        volume_no = data.get("volume_no") or default_volume_no
        volume_name = data.get("volume_name") or ""
        chapter_end = default_chapter_start + chapter_count - 1
        chapters: list[ChapterDraft] = []
        for idx, ch in enumerate(data.get("chapters", [])):
            chapter_no = ch.get("chapter_no") or (default_chapter_start + idx)
            if not default_chapter_start <= chapter_no <= chapter_end:
                continue
            chapters.append(
                ChapterDraft(
                    chapter_no=chapter_no,
                    chapter_name=ch.get("chapter_name", ""),
                    synopsis_points=ch.get("synopsis_points", ""),
                    characters_appearing=self._normalize_appearing(
                        ch.get("characters_appearing")
                    ),
                )
            )
        return VolumeBatchDraft(
            volume_no=volume_no,
            volume_name=volume_name,
            chapters=chapters,
        )

    async def build_check_and_call(
        self,
        synopsis: str,
        worldview: str,
        characters: list[CharacterDto],
        volume_no: int,
        chapters: list[dict],
        project_id: str,
        timeout_seconds: int = 90,
        garbled_config: "GarbledConfig | None" = None,
    ) -> OutlineConsistencyResult:
        """构建一致性校验提示词并调用 AI（按批，输入规模可控）.

        chapters: [{chapter_no, chapter_name, synopsis_points, characters_appearing}]
        """
        result = await self.gateway.call_and_parse(
            module="outline",
            scene="check-consistency",
            params={
                "synopsis": synopsis,
                "worldview": worldview,
                "characters": [c.model_dump() for c in characters],
                "volume_no": volume_no,
                "chapter_start": chapters[0]["chapter_no"] if chapters else 1,
                "chapter_count": len(chapters),
                "chapters": chapters,
                "garbled_config_enabled": garbled_config.enabled if garbled_config else True,
            },
            project_id=project_id,
            timeout_seconds=timeout_seconds,
        )
        return self.parse_check_response(result.get("parsed", {}), len(chapters))

    def parse_check_response(
        self, raw: str | dict, checked_count: int
    ) -> OutlineConsistencyResult:
        """解析一致性校验返回；字段缺失时置空，避免因个别字段丢失整体失败."""
        data = self._load_json(raw)
        issues: list[OutlineConsistencyIssue] = []
        for item in data.get("issues", []) or []:
            if not isinstance(item, dict):
                continue
            issues.append(
                OutlineConsistencyIssue(
                    level=str(item.get("level", "") or "").strip(),
                    chapter_no=self._to_int(item.get("chapter_no")),
                    type=str(item.get("type", "") or "").strip(),
                    detail=str(item.get("detail", "") or "").strip(),
                    suggestion=str(item.get("suggestion", "") or "").strip(),
                )
            )
        return OutlineConsistencyResult(
            score=self._normalize_score(data.get("score")),
            summary=str(data.get("summary", "") or "").strip(),
            issues=issues,
            checked_chapter_count=checked_count,
        )

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _normalize_score(value: Any) -> int:
        """把 AI 返回的评分收敛到 0-100 整数."""
        score = OutlineBuilder._to_int(value)
        return max(0, min(100, score))

    @staticmethod
    def _load_json(raw: str | dict) -> dict:
        """把 AI 返回内容统一解析为 dict，失败时抛 ValueError."""
        if isinstance(raw, dict):
            return raw
        import json

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("AI返回内容无法解析为大纲结构")
        if not isinstance(data, dict):
            raise ValueError("AI返回内容无法解析为大纲结构")
        return data

    @staticmethod
    def _normalize_appearing(value: Any) -> str:
        """把 AI 返回的本章出场人物统一成"、"分隔的名字串（兼容 list/str）."""
        if value is None:
            return ""
        if isinstance(value, str):
            text = value.replace("，", "、").replace(",", "、").replace(";", "、")
            return "、".join(p.strip() for p in text.split("、") if p.strip())
        if isinstance(value, (list, tuple, set)):
            names: list[str] = []
            for item in value:
                text = str(item).strip()
                if text and text not in names:
                    names.append(text)
            return "、".join(names)
        return str(value).strip()

    def parse_response(self, raw: str | dict) -> OutlineDraft:
        """解析 AI 返回 JSON 为 OutlineDraft，缺失项置空不抛异常."""
        data = self._load_json(raw)

        volumes_data = data.get("volumes", [])
        volumes: list[VolumeDraft] = []
        for v in volumes_data:
            chapters_data = v.get("chapters", [])
            chapters: list[ChapterDraft] = []
            for ch in chapters_data:
                chapters.append(
                    ChapterDraft(
                        chapter_no=ch.get("chapter_no", 0),
                        chapter_name=ch.get("chapter_name", ""),
                        synopsis_points=ch.get("synopsis_points", ""),
                        characters_appearing=self._normalize_appearing(
                            ch.get("characters_appearing")
                        ),
                    )
                )
            volumes.append(
                VolumeDraft(
                    volume_no=v.get("volume_no", 0),
                    volume_name=v.get("volume_name", ""),
                    chapters=chapters,
                )
            )
        return OutlineDraft(volumes=volumes)
    async def build_fill_appearing_and_call(
        self,
        synopsis: str,
        worldview: str,
        characters: list[CharacterDto],
        chapter: dict,
        project_id: str,
        timeout_seconds: int = 90,
    ) -> list[str]:
        """调用 AI 识别本章实际出场人物."""
        result = await self.gateway.call_and_parse(
            module="outline",
            scene="fill-appearing",
            params={
                "synopsis": synopsis,
                "worldview": worldview,
                "characters": [c.model_dump() for c in characters],
                "chapter": chapter,
            },
            project_id=project_id,
            timeout_seconds=timeout_seconds,
        )
        parsed = result.get("parsed", {})
        names = parsed.get("characters", [])
        if not isinstance(names, list):
            self.logger.warning(f"fill-appearing AI 返回 characters 非列表: {type(names)}")
            return []
        return [str(n).strip() for n in names if n and str(n).strip()]

    async def build_repair_and_call(
        self,
        synopsis: str,
        worldview: str,
        characters: list[CharacterDto],
        chapter: dict,
        chapter_issues: list[dict],
        project_id: str,
        timeout_seconds: int = 120,
        garbled_config: "GarbledConfig | None" = None,
    ) -> dict:
        """调用 AI 修复章节大纲."""
        result = await self.gateway.call_and_parse(
            module="outline",
            scene="repair-outline",
            params={
                "synopsis": synopsis,
                "worldview": worldview,
                "characters": [c.model_dump() for c in characters],
                "chapter": chapter,
                "chapter_issues": chapter_issues,
                "garbled_config_enabled": garbled_config.enabled if garbled_config else True,
            },
            project_id=project_id,
            timeout_seconds=timeout_seconds,
        )
        parsed = result.get("parsed", {})
        if not parsed:
            raise RuntimeError("AI 返回无法解析")
        return parsed