"""项目导出服务."""
from __future__ import annotations

import hashlib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backup.archive_format import ArchiveFormat
from src.db.models import (
    AiCallLog,
    AntiAiRewriteRecord,
    BatchOperationRecord,
    Chapter,
    ChapterAnnotation,
    ChapterOutline,
    ChapterScene,
    ChapterSummary,
    ChapterVersion,
    Character,
    CharacterRelationship,
    CoolPoint,
    EmotionCurvePoint,
    Hook,
    IterationRecord,
    Item,
    ModifyRecord,
    NameFavorite,
    Outline,
    ProofreadDraft,
    Project,
    Script,
    SensitiveWord,
    StoryUnit,
    StyleFeature,
    StyleLibrary,
    Synopsis,
    TimelineNode,
    ValidationReport,
    VolumeOutline,
    Worldview,
    WritingChatHistory,
)
from src.utils.logger import get_logger


class ProjectExportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.archive = ArchiveFormat()

    async def export_project(
        self,
        project_id: str,
        target_path: str,
        include_ai_call_logs: bool = False,
        include_style_libraries: bool = True,
    ) -> dict:
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")

        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)

        chars = await self.session.execute(select(Character).where(Character.project_id == project_id))
        cool_points = await self.session.execute(select(CoolPoint).where(CoolPoint.project_id == project_id))
        hooks = await self.session.execute(select(Hook).where(Hook.project_id == project_id))
        chapters = await self.session.execute(select(Chapter).where(Chapter.project_id == project_id))
        items = await self.session.execute(select(Item).where(Item.project_id == project_id))
        modify_records = await self.session.execute(select(ModifyRecord).where(ModifyRecord.chapter_id.in_(
            select(Chapter.chapter_id).where(Chapter.project_id == project_id)
        )))
        validation_reports = await self.session.execute(select(ValidationReport).where(ValidationReport.project_id == project_id))

        outline_result = await self.session.execute(select(Outline).where(Outline.project_id == project_id))
        outline = outline_result.scalars().first()
        outline_data = None
        if outline:
            vol_result = await self.session.execute(select(VolumeOutline).where(VolumeOutline.outline_id == outline.outline_id))
            volumes = []
            for vol in vol_result.scalars().all():
                ch_result = await self.session.execute(select(ChapterOutline).where(ChapterOutline.volume_outline_id == vol.volume_outline_id))
                volumes.append({
                    **self._serialize(vol),
                    "chapters": [self._serialize(ch) for ch in ch_result.scalars().all()],
                })
            outline_data = {
                **self._serialize(outline),
                "volumes": volumes,
            }

        data = {
            "project": self._serialize(project),
            "synopsis": self._serialize(synopsis),
            "worldview": self._serialize(worldview),
            "characters": [self._serialize(c) for c in chars.scalars().all()],
            "cool_points": [self._serialize(c) for c in cool_points.scalars().all()],
            "hooks": [self._serialize(h) for h in hooks.scalars().all()],
            "chapters": [self._serialize(c) for c in chapters.scalars().all()],
            "items": [self._serialize(i) for i in items.scalars().all()],
            "modify_records": [self._serialize(r) for r in modify_records.scalars().all()],
            "validation_reports": [self._serialize(r) for r in validation_reports.scalars().all()],
            "outline": outline_data,
        }

        chapter_ids_subq = select(Chapter.chapter_id).where(Chapter.project_id == project_id)
        char_ids_subq = select(Character.character_id).where(Character.project_id == project_id)

        chat_histories = await self.session.execute(
            select(WritingChatHistory).where(WritingChatHistory.chapter_id.in_(chapter_ids_subq))
        )
        data["writing_chat_histories"] = [self._serialize(r) for r in chat_histories.scalars().all()]

        versions = await self.session.execute(
            select(ChapterVersion).where(ChapterVersion.chapter_id.in_(chapter_ids_subq))
        )
        data["chapter_versions"] = [self._serialize(r) for r in versions.scalars().all()]

        annotations = await self.session.execute(
            select(ChapterAnnotation).where(ChapterAnnotation.chapter_id.in_(chapter_ids_subq))
        )
        data["chapter_annotations"] = [self._serialize(r) for r in annotations.scalars().all()]

        scenes = await self.session.execute(
            select(ChapterScene).where(ChapterScene.chapter_id.in_(chapter_ids_subq))
        )
        data["chapter_scenes"] = [self._serialize(r) for r in scenes.scalars().all()]

        summaries = await self.session.execute(
            select(ChapterSummary).where(ChapterSummary.chapter_id.in_(chapter_ids_subq))
        )
        data["chapter_summaries"] = [self._serialize(r) for r in summaries.scalars().all()]

        timeline_nodes = await self.session.execute(
            select(TimelineNode).where(TimelineNode.project_id == project_id)
        )
        data["timeline_nodes"] = [self._serialize(r) for r in timeline_nodes.scalars().all()]

        relationships = await self.session.execute(
            select(CharacterRelationship).where(CharacterRelationship.project_id == project_id)
        )
        data["character_relationships"] = [self._serialize(r) for r in relationships.scalars().all()]

        emotion_points = await self.session.execute(
            select(EmotionCurvePoint).where(EmotionCurvePoint.project_id == project_id)
        )
        data["emotion_curve_points"] = [self._serialize(r) for r in emotion_points.scalars().all()]

        sensitive_words = await self.session.execute(
            select(SensitiveWord).where(SensitiveWord.project_id == project_id)
        )
        data["sensitive_words"] = [self._serialize(r) for r in sensitive_words.scalars().all()]

        name_favorites = await self.session.execute(
            select(NameFavorite).where(NameFavorite.project_id == project_id)
        )
        data["name_favorites"] = [self._serialize(r) for r in name_favorites.scalars().all()]

        story_units = await self.session.execute(
            select(StoryUnit).where(StoryUnit.project_id == project_id)
        )
        data["story_units"] = [self._serialize(r) for r in story_units.scalars().all()]

        scripts = await self.session.execute(
            select(Script).where(Script.project_id == project_id)
        )
        data["scripts"] = [self._serialize(r) for r in scripts.scalars().all()]

        batch_ops = await self.session.execute(
            select(BatchOperationRecord).where(BatchOperationRecord.project_id == project_id)
        )
        data["batch_operation_records"] = [self._serialize(r) for r in batch_ops.scalars().all()]

        iteration_records = await self.session.execute(
            select(IterationRecord).where(IterationRecord.project_id == project_id)
        )
        data["iteration_records"] = [self._serialize(r) for r in iteration_records.scalars().all()]


        anti_ai_rewrites = await self.session.execute(
            select(AntiAiRewriteRecord).where(AntiAiRewriteRecord.chapter_id.in_(chapter_ids_subq))
        )
        data["anti_ai_rewrite_records"] = [self._serialize(r) for r in anti_ai_rewrites.scalars().all()]

        proofread_drafts = await self.session.execute(
            select(ProofreadDraft).where(ProofreadDraft.chapter_id.in_(chapter_ids_subq))
        )
        data["proofread_drafts"] = [self._serialize(r) for r in proofread_drafts.scalars().all()]

        if include_style_libraries and project.style_library_id:
            sl = await self.session.get(StyleLibrary, project.style_library_id)
            if sl:
                features = await self.session.execute(
                    select(StyleFeature).where(StyleFeature.style_library_id == sl.style_library_id)
                )
                data["style_libraries"] = [{
                    **self._serialize(sl),
                    "features": [self._serialize(f) for f in features.scalars().all()],
                }]

        if include_ai_call_logs:
            logs = await self.session.execute(select(AiCallLog).where(AiCallLog.project_id == project_id))
            data["ai_call_logs"] = [self._serialize(l) for l in logs.scalars().all()]

        file_path = self.archive.write_archive(
            target_path, data, project_id,
            project_name=project.book_title,
            options={"include_ai_call_logs": include_ai_call_logs, "include_style_libraries": include_style_libraries},
        )
        from pathlib import Path
        p = Path(file_path)
        size = p.stat().st_size
        checksum = hashlib.sha256(p.read_bytes()).hexdigest()
        return {
            "file_path": file_path,
            "file_size_bytes": size,
            "checksum": checksum,
            "archived_at": data["project"].get("updated_at"),
            "item_count": sum(len(v) for v in data.values() if isinstance(v, list)) + 3,
        }

    @staticmethod
    def _serialize(obj) -> dict:
        if obj is None:
            return {}
        from sqlalchemy import inspect as sa_inspect
        mapper = sa_inspect(type(obj))
        result = {}
        for col in mapper.columns:
            val = getattr(obj, col.key)
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            if isinstance(val, bytes):
                val = val.decode("utf-8", errors="replace")
            result[col.key] = val
        return result