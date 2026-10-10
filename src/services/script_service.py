"""AI写剧本服务 - 基于多级大纲生成分集剧本."""
from __future__ import annotations


import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.script_schema import ScriptEpisodeDto, ScriptProgressEvent
from src.config.settings import get_config
from src.db.models import ChapterOutline, Character, Outline, Project, Script, VolumeOutline
from src.db.session import release_write_lock
from src.utils.logger import get_logger


class ScriptService:
    """AI写剧本服务."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    async def generate_script(
        self, project_id: str
    ) -> AsyncGenerator[ScriptProgressEvent, None]:
        project = await self.session.get(Project, project_id)
        if not project:
            yield ScriptProgressEvent(type="error", message="项目不存在")
            return

        outline_result = await self.session.execute(
            select(Outline).where(Outline.project_id == project_id)
        )
        outline = outline_result.scalars().first()
        if not outline or outline.gen_status != "已生成":
            yield ScriptProgressEvent(type="error", message="大纲尚未生成，请先生成大纲")
            return

        outline_units = await self._collect_outline_units(outline)
        if not outline_units:
            yield ScriptProgressEvent(type="error", message="大纲无有效章节，无法生成剧本")
            return

        characters = await self._collect_characters(project_id)
        if not characters:
            yield ScriptProgressEvent(type="error", message="无已确认人物，请先确认人物清单")
            return

        existing = await self._list_script_entities(project_id)
        for ent in existing:
            await self.session.delete(ent)
        await self.session.flush()
        await release_write_lock(self.session)

        total = len(outline_units)
        gateway = get_gateway()
        timeout = get_config().script_generate_timeout_seconds
        min_length = get_config().min_ai_content_length

        for idx, unit in enumerate(outline_units):
            episode_no = idx + 1
            yield ScriptProgressEvent(
                type="progress",
                episode_no=episode_no,
                progress=int(idx / total * 100),
                message=f"正在生成第{episode_no}集剧本...",
            )

            try:
                scene_description, character_dialogue = await self._call_script_ai(
                    gateway, project_id, outline_units, characters, episode_no, timeout
                )
            except Exception as e:
                self.logger.error(f"第{episode_no}集剧本AI调用失败: {e}")
                yield ScriptProgressEvent(
                    type="error",
                    episode_no=episode_no,
                    message=f"第{episode_no}集剧本生成失败: {e}",
                )
                return

            combined_len = len(scene_description) + len(character_dialogue)
            if combined_len < min_length:
                self.logger.warning(
                    f"第{episode_no}集剧本内容过短({combined_len}字)，重试一次"
                )
                await release_write_lock(self.session)
                try:
                    scene_description, character_dialogue = await self._call_script_ai(
                        gateway, project_id, outline_units, characters, episode_no, timeout
                    )
                except Exception as e:
                    self.logger.error(f"第{episode_no}集剧本重试失败: {e}")
                    yield ScriptProgressEvent(
                        type="error",
                        episode_no=episode_no,
                        message=f"第{episode_no}集剧本重试失败: {e}",
                    )
                    return
                combined_len = len(scene_description) + len(character_dialogue)
                if combined_len < min_length:
                    self.logger.warning(
                        f"第{episode_no}集剧本重试后内容仍过短({combined_len}字)"
                    )

            script = Script(
                script_id=str(uuid.uuid4()),
                project_id=project_id,
                episode_no=episode_no,
                scene_description=scene_description,
                character_dialogue=character_dialogue,
                outline_unit_id=unit.get("story_unit_id"),
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(script)
            await self.session.flush()
            await self.session.commit()

            yield ScriptProgressEvent(
                type="episode_done",
                episode_no=episode_no,
                scene_description=scene_description,
                character_dialogue=character_dialogue,
                progress=int((idx + 1) / total * 100),
                message=f"第{episode_no}集剧本生成完成",
            )

        yield ScriptProgressEvent(
            type="completed",
            progress=100,
            message="全部分集剧本生成完成",
        )

    async def _call_script_ai(
        self,
        gateway,
        project_id: str,
        outline_units: list[dict],
        characters: list[dict],
        episode_no: int,
        timeout: int,
    ) -> tuple[str, str]:
        params = {
            "outline_units": outline_units,
            "characters": characters,
            "episode_no": episode_no,
        }
        result = await gateway.call_and_parse(
            module="writing",
            scene="script",
            params=params,
            project_id=project_id,
            timeout_seconds=timeout,
        )
        parsed = result.get("parsed", {})
        scene_description = parsed.get("scene_description", "")
        character_dialogue = parsed.get("character_dialogue", "")
        if not scene_description or not character_dialogue:
            raise RuntimeError("AI返回的场景描述或角色对白为空")
        return scene_description, character_dialogue

    async def _collect_outline_units(self, outline: Outline) -> list[dict]:
        vol_result = await self.session.execute(
            select(VolumeOutline)
            .where(VolumeOutline.outline_id == outline.outline_id)
            .order_by(VolumeOutline.volume_no)
        )
        units: list[dict] = []
        for vol in vol_result.scalars().all():
            ch_result = await self.session.execute(
                select(ChapterOutline)
                .where(ChapterOutline.volume_outline_id == vol.volume_outline_id)
                .order_by(ChapterOutline.chapter_no)
            )
            for ch in ch_result.scalars().all():
                if ch.synopsis_points and ch.synopsis_points.strip():
                    units.append({
                        "volume_no": vol.volume_no,
                        "volume_name": vol.volume_name,
                        "chapter_no": ch.chapter_no,
                        "chapter_name": ch.chapter_name,
                        "synopsis_points": ch.synopsis_points,
                        "characters_appearing": ch.characters_appearing or "",
                        "story_unit_id": ch.story_unit_id,
                    })
        return units

    async def _collect_characters(self, project_id: str) -> list[dict]:
        result = await self.session.execute(
            select(Character).where(
                Character.project_id == project_id,
                Character.confirmed.is_(True),
            ).order_by(Character.created_at)
        )
        return [
            {
                "name": c.name,
                "identity": c.identity,
                "intro": c.intro or "",
                "relation": c.relation or "",
            }
            for c in result.scalars().all()
        ]

    async def _list_script_entities(self, project_id: str) -> list[Script]:
        result = await self.session.execute(
            select(Script)
            .where(Script.project_id == project_id)
            .order_by(Script.episode_no)
        )
        return list(result.scalars().all())

    async def list_episodes(self, project_id: str) -> list[ScriptEpisodeDto]:
        entities = await self._list_script_entities(project_id)
        return [
            ScriptEpisodeDto(
                script_id=e.script_id,
                project_id=e.project_id,
                episode_no=e.episode_no,
                scene_description=e.scene_description,
                character_dialogue=e.character_dialogue,
                created_at=e.created_at,
            )
            for e in entities
        ]

    async def export_script(
        self, project_id: str, target_dir: str, format: str = "txt"
    ) -> dict:
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")

        episodes = await self._list_script_entities(project_id)
        if not episodes:
            raise ValueError("暂无剧本，请先生成分集剧本")

        target_path = Path(target_dir)
        if ".." in target_path.parts:
            raise ValueError("目标路径包含非法的目录穿越符")
        target_path.mkdir(parents=True, exist_ok=True)

        book_title = project.book_title
        file_path = target_path / f"{book_title}_剧本.{format}"
        lines: list[str] = [book_title, "", "=" * 50, ""]

        for ep in episodes:
            lines.append(f"第{ep.episode_no}集")
            lines.append("-" * 30)
            lines.append("")
            lines.append("【场景描述】")
            lines.append(ep.scene_description)
            lines.append("")
            lines.append("【角色对白】")
            lines.append(ep.character_dialogue)
            lines.append("")
            lines.append("=" * 50)
            lines.append("")

        content = "\n".join(lines)
        file_path.write_text(content, encoding="utf-8")
        self.logger.info(f"剧本导出成功: {file_path}, 共 {len(episodes)} 集")
        return {
            "file_path": str(file_path),
            "episode_count": len(episodes),
        }