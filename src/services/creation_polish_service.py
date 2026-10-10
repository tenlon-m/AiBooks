"""创作参数AI润色服务 - 扩展用户简单思路为完整梗概/世界观."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.creation_schema import CreationPolishRequest, CreationPolishResponse
from src.config.settings import get_config
from src.db.models import Project
from src.db.session import release_write_lock
from src.utils.logger import get_logger


class CreationPolishService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()

    async def polish_creation(
        self, project_id: str, req: CreationPolishRequest,
        garbled_config: "GarbledConfig | None" = None,
    ) -> CreationPolishResponse:
        from src.services.garbled_config_service import GarbledConfigService
        from src.services.garbled_normalizer import GarbledNormalizer

        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")

        if garbled_config is None:
            cfg_svc = GarbledConfigService(self.session)
            garbled_config = await cfg_svc.resolve_effective_config(project_id)
        normalizer = GarbledNormalizer()

        if req.target == "synopsis":
            scene = "polish-synopsis"
            timeout = get_config().creation_polish_synopsis_timeout_seconds
            params: dict[str, Any] = {
                "raw_ideas": req.raw_ideas,
                "book_title": req.book_title,
                "volume_count": req.volume_count,
                "chapters_per_volume": req.chapters_per_volume,
                "words_per_chapter": req.words_per_chapter,
                "garbled_config_enabled": garbled_config.enabled,
            }
        else:
            scene = "polish-worldview"
            timeout = get_config().creation_polish_worldview_timeout_seconds
            params = {
                "raw_ideas": req.raw_ideas,
                "book_title": req.book_title,
                "volume_count": req.volume_count,
                "chapters_per_volume": req.chapters_per_volume,
                "words_per_chapter": req.words_per_chapter,
                "synopsis": req.synopsis,
                "garbled_config_enabled": garbled_config.enabled,
            }

        await release_write_lock(self.session)

        result = await self.gateway.call_and_parse(
            module="creation",
            scene=scene,
            params=params,
            project_id=project_id,
            timeout_seconds=timeout,
        )
        parsed = result.get("parsed", {})
        polished = parsed.get("polished_content", "")
        if not polished:
            raise ValueError("AI 未返回有效内容，请重试或调整思路")
        if len(polished) < 50:
            raise ValueError("润色结果过短，未达到可保存要求（≥50字），请补充思路后重试")
        if garbled_config.enabled:
            polished, _ = normalizer.detect_and_normalize(polished, garbled_config)
        return CreationPolishResponse(
            target=req.target,
            polished_content=polished,
        )