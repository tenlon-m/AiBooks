"""配角构建器 - 提示词构建与响应解析."""
from __future__ import annotations

from src.ai.gateway import get_gateway
from src.api.schemas.character_schema import CharacterDto, SupportingDraft
from src.utils.logger import get_logger


class SupportingBuilder:
    """自动生成配角的提示词构建与响应解析器."""

    def __init__(self) -> None:
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def build_and_call(
        self,
        synopsis: str,
        worldview: str,
        existing: list[CharacterDto],
        scene_context: dict,
        count: int,
        project_id: str,
        timeout_seconds: int = 60,
    ) -> list[SupportingDraft]:
        """构建提示词并调用 AI 生成配角，返回解析后的 SupportingDraft 列表."""
        result = await self.gateway.call_and_parse(
            module="character",
            scene="auto-generate-supporting",
            params={
                "synopsis": synopsis,
                "worldview": worldview,
                "existing_characters": [c.model_dump() for c in existing],
                "scene_context": scene_context,
                "count": count,
            },
            project_id=project_id,
            timeout_seconds=timeout_seconds,
            max_tokens=8192,
        )
        parsed = result.get("parsed", {})
        return self.parse_response(parsed)

    def parse_response(self, raw: str | dict) -> list[SupportingDraft]:
        """解析 AI 返回 JSON 为 SupportingDraft 列表，缺姓名的配角跳过."""
        if isinstance(raw, dict):
            data = raw
        else:
            import json

            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                self.logger.warning("自动生成配角响应解析失败")
                return []

        chars_data = data.get("supporting_characters", [])
        if not chars_data:
            chars_data = data.get("characters", [])

        drafts: list[SupportingDraft] = []
        for c in chars_data:
            name = c.get("name", "").strip() if c.get("name") else ""
            if not name:
                continue
            drafts.append(
                SupportingDraft(
                    name=name,
                    identity=c.get("identity", "配角"),
                    intro=c.get("intro", ""),
                    relation=c.get("relation", ""),
                    future_reference=c.get("future_reference", True),
                )
            )
        return drafts
