"""项目导入服务 - SHA256校验+版本兼容+chapter_id重映射+风格库冲突+事务原子性."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

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


class StyleLibraryConflictError(Exception):
    pass


def _parse_datetime_fields(data: dict, columns: set) -> dict:
    for key in data:
        if key in columns and isinstance(data[key], str) and "T" in data[key]:
            try:
                data[key] = datetime.fromisoformat(data[key])
            except (ValueError, TypeError):
                pass
    return data


class ProjectImportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.archive = ArchiveFormat()

    async def import_project(
        self,
        source_path: str,
        conflict_strategy: str = "rename",
    ) -> dict:
        data = self.archive.read_archive(source_path)
        manifest = data.get("_manifest", {})
        project_data = data.get("project", {})
        warnings: list[str] = []

        original_title = project_data.get("book_title", "")
        original_project_id = project_data.get("project_id", "")
        new_project_id = original_project_id
        is_renamed = False

        existing = await self.session.get(Project, original_project_id)
        if existing:
            if conflict_strategy == "overwrite":
                await self.session.delete(existing)
                await self.session.flush()
            elif conflict_strategy == "rename":
                new_project_id = str(uuid.uuid4())
                project_data["project_id"] = new_project_id
                project_data["book_title"] = f"{original_title}_导入_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                is_renamed = True
            else:
                raise ValueError("项目已存在，已取消导入")

        chapter_id_map: dict[str, str] = {}

        try:
            project_cols = set(Project.__table__.columns.keys())
            _parse_datetime_fields(project_data, project_cols)
            project = Project(**{k: v for k, v in project_data.items() if k in project_cols})
            self.session.add(project)
            await self.session.flush()

            for key, model_cls in [
                ("synopsis", Synopsis), ("worldview", Worldview),
            ]:
                item = data.get(key, {})
                if isinstance(item, list):
                    item = item[0] if item else {}
                if item:
                    item["project_id"] = new_project_id
                    cols_set = set(model_cls.__table__.columns.keys())
                    _parse_datetime_fields(item, cols_set)
                    cols = {k: v for k, v in item.items() if k in cols_set}
                    self.session.add(model_cls(**cols))

            for key, model_cls in [
                ("characters", Character), ("cool_points", CoolPoint), ("hooks", Hook), ("items", Item),
            ]:
                items = data.get(key, [])
                if isinstance(items, dict):
                    items = [items]
                cols_set = set(model_cls.__table__.columns.keys())
                for item_data in items:
                    if "project_id" in item_data:
                        item_data["project_id"] = new_project_id
                    _parse_datetime_fields(item_data, cols_set)
                    cols = {k: v for k, v in item_data.items() if k in cols_set}
                    self.session.add(model_cls(**cols))

            await self.session.flush()

            chapters = data.get("chapters", [])
            if isinstance(chapters, dict):
                chapters = [chapters]
            ch_cols_set = set(Chapter.__table__.columns.keys())
            for ch_data in chapters:
                old_chapter_id = ch_data.get("chapter_id", "")
                if is_renamed or old_chapter_id != str(uuid.uuid4()):
                    new_chapter_id = str(uuid.uuid4())
                    chapter_id_map[old_chapter_id] = new_chapter_id
                    ch_data["chapter_id"] = new_chapter_id
                ch_data["project_id"] = new_project_id
                _parse_datetime_fields(ch_data, ch_cols_set)
                cols = {k: v for k, v in ch_data.items() if k in ch_cols_set}
                self.session.add(Chapter(**cols))
            await self.session.flush()

            modify_records = data.get("modify_records", [])
            if isinstance(modify_records, dict):
                modify_records = [modify_records]
            mr_cols_set = set(ModifyRecord.__table__.columns.keys())
            for r in modify_records:
                old_ch_id = r.get("chapter_id", "")
                if old_ch_id in chapter_id_map:
                    r["chapter_id"] = chapter_id_map[old_ch_id]
                _parse_datetime_fields(r, mr_cols_set)
                cols = {k: v for k, v in r.items() if k in mr_cols_set}
                self.session.add(ModifyRecord(**cols))

            validation_reports = data.get("validation_reports", [])
            if isinstance(validation_reports, dict):
                validation_reports = [validation_reports]
            vr_cols_set = set(ValidationReport.__table__.columns.keys())
            for r in validation_reports:
                r["project_id"] = new_project_id
                _parse_datetime_fields(r, vr_cols_set)
                cols = {k: v for k, v in r.items() if k in vr_cols_set}
                self.session.add(ValidationReport(**cols))

            outline_data = data.get("outline")
            if outline_data and isinstance(outline_data, dict):
                volumes_data = outline_data.pop("volumes", [])
                outline_data["project_id"] = new_project_id
                outline_data["outline_id"] = str(uuid.uuid4())
                ol_cols_set = set(Outline.__table__.columns.keys())
                _parse_datetime_fields(outline_data, ol_cols_set)
                ol_cols = {k: v for k, v in outline_data.items() if k in ol_cols_set}
                outline_entity = Outline(**ol_cols)
                self.session.add(outline_entity)
                await self.session.flush()

                for vol_data in volumes_data:
                    chapters_data = vol_data.pop("chapters", [])
                    vol_data["outline_id"] = outline_entity.outline_id
                    vol_data["volume_outline_id"] = str(uuid.uuid4())
                    vol_cols_set = set(VolumeOutline.__table__.columns.keys())
                    _parse_datetime_fields(vol_data, vol_cols_set)
                    vol_cols = {k: v for k, v in vol_data.items() if k in vol_cols_set}
                    vol_entity = VolumeOutline(**vol_cols)
                    self.session.add(vol_entity)
                    await self.session.flush()

                    for ch_data in chapters_data:
                        ch_data["volume_outline_id"] = vol_entity.volume_outline_id
                        ch_data["chapter_outline_id"] = str(uuid.uuid4())
                        ch_ol_cols_set = set(ChapterOutline.__table__.columns.keys())
                        _parse_datetime_fields(ch_data, ch_ol_cols_set)
                        ch_ol_cols = {k: v for k, v in ch_data.items() if k in ch_ol_cols_set}
                        self.session.add(ChapterOutline(**ch_ol_cols))

            style_libs = data.get("style_libraries", [])
            if isinstance(style_libs, dict):
                style_libs = [style_libs]
            for sl in style_libs:
                features = sl.pop("features", [])
                sl_name = sl.get("name", "")
                existing_sl = await self.session.execute(
                    select(StyleLibrary).where(StyleLibrary.name == sl_name)
                )
                existing_sl_obj = existing_sl.scalars().first()
                if existing_sl_obj:
                    existing_features = await self.session.execute(
                        select(StyleFeature).where(StyleFeature.style_library_id == existing_sl_obj.style_library_id)
                    )
                    existing_feat_list = existing_features.scalars().all()
                    existing_feat_set = {(f.dimension, f.description) for f in existing_feat_list}
                    new_feat_set = {(f.get("dimension", ""), f.get("description", "")) for f in features}
                    if existing_feat_set == new_feat_set:
                        warnings.append(f"风格库'{sl_name}'同名同特征，复用本机版本")
                        project.style_library_id = existing_sl_obj.style_library_id
                        continue
                    else:
                        if conflict_strategy == "overwrite":
                            await self.session.delete(existing_sl_obj)
                            await self.session.flush()
                        elif conflict_strategy == "rename":
                            sl["name"] = f"{sl_name}_导入_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                        else:
                            raise StyleLibraryConflictError(f"风格库'{sl_name}'同名但特征不同，请选择覆盖/重命名/取消")

                sl["style_library_id"] = str(uuid.uuid4())
                sl_cols_set = set(StyleLibrary.__table__.columns.keys())
                _parse_datetime_fields(sl, sl_cols_set)
                cols = {k: v for k, v in sl.items() if k in sl_cols_set}
                entity = StyleLibrary(**cols)
                self.session.add(entity)
                await self.session.flush()
                sf_cols_set = set(StyleFeature.__table__.columns.keys())
                for f in features:
                    f["style_library_id"] = entity.style_library_id
                    _parse_datetime_fields(f, sf_cols_set)
                    fcols = {k: v for k, v in f.items() if k in sf_cols_set}
                    self.session.add(StyleFeature(**fcols))

            await self.session.flush()

            char_id_map: dict[str, str] = {}
            for ch in data.get("characters", []):
                old_cid = ch.get("character_id", "")
                if old_cid and old_cid not in char_id_map:
                    char_id_map[old_cid] = old_cid

            version_id_map: dict[str, str] = {}

            for key, model_cls, id_field in [
                ("writing_chat_histories", WritingChatHistory, "chat_id"),
                ("chapter_versions", ChapterVersion, "version_id"),
                ("chapter_annotations", ChapterAnnotation, "annotation_id"),
                ("chapter_scenes", ChapterScene, "scene_id"),
            ]:
                items = data.get(key, [])
                if isinstance(items, dict):
                    items = [items]
                cols_set = set(model_cls.__table__.columns.keys())
                for item_data in items:
                    old_ch_id = item_data.get("chapter_id", "")
                    if old_ch_id in chapter_id_map:
                        item_data["chapter_id"] = chapter_id_map[old_ch_id]
                    old_id = item_data.get(id_field, "")
                    new_id = str(uuid.uuid4())
                    if key == "chapter_versions" and old_id:
                        version_id_map[old_id] = new_id
                    item_data[id_field] = new_id
                    _parse_datetime_fields(item_data, cols_set)
                    cols = {k: v for k, v in item_data.items() if k in cols_set}
                    self.session.add(model_cls(**cols))

            summaries = data.get("chapter_summaries", [])
            if isinstance(summaries, dict):
                summaries = [summaries]
            sm_cols_set = set(ChapterSummary.__table__.columns.keys())
            for sm in summaries:
                old_ch_id = sm.get("chapter_id", "")
                if old_ch_id in chapter_id_map:
                    sm["chapter_id"] = chapter_id_map[old_ch_id]
                _parse_datetime_fields(sm, sm_cols_set)
                cols = {k: v for k, v in sm.items() if k in sm_cols_set}
                self.session.add(ChapterSummary(**cols))

            for key, model_cls, id_field in [
                ("timeline_nodes", TimelineNode, "node_id"),
                ("character_relationships", CharacterRelationship, "relationship_id"),
                ("emotion_curve_points", EmotionCurvePoint, "point_id"),
                ("sensitive_words", SensitiveWord, "word_id"),
                ("name_favorites", NameFavorite, "favorite_id"),
                ("ai_call_logs", AiCallLog, "log_id"),
            ]:
                items = data.get(key, [])
                if isinstance(items, dict):
                    items = [items]
                cols_set = set(model_cls.__table__.columns.keys())
                for item_data in items:
                    if "project_id" in item_data:
                        item_data["project_id"] = new_project_id
                    if key == "emotion_curve_points":
                        old_ch_id = item_data.get("chapter_id", "")
                        if old_ch_id in chapter_id_map:
                            item_data["chapter_id"] = chapter_id_map[old_ch_id]
                    if key == "character_relationships":
                        for cid_field in ("source_character_id", "target_character_id"):
                            old_cid = item_data.get(cid_field, "")
                            if old_cid in char_id_map:
                                item_data[cid_field] = char_id_map[old_cid]
                    item_data[id_field] = str(uuid.uuid4())
                    _parse_datetime_fields(item_data, cols_set)
                    cols = {k: v for k, v in item_data.items() if k in cols_set}
                    self.session.add(model_cls(**cols))

            story_unit_id_map: dict[str, str] = {}
            story_units = data.get("story_units", [])
            if isinstance(story_units, dict):
                story_units = [story_units]
            su_cols_set = set(StoryUnit.__table__.columns.keys())
            su_entities_by_new_id: dict[str, tuple] = {}
            for su_data in story_units:
                old_su_id = su_data.get("story_unit_id", "")
                new_su_id = str(uuid.uuid4())
                story_unit_id_map[old_su_id] = new_su_id
                su_data["story_unit_id"] = new_su_id
                su_data["project_id"] = new_project_id
                original_parent = su_data.get("parent_unit_id")
                su_data["parent_unit_id"] = None
                _parse_datetime_fields(su_data, su_cols_set)
                cols = {k: v for k, v in su_data.items() if k in su_cols_set}
                entity = StoryUnit(**cols)
                self.session.add(entity)
                su_entities_by_new_id[new_su_id] = (entity, original_parent)
            await self.session.flush()
            for _new_su_id, (_entity, _original_parent) in su_entities_by_new_id.items():
                if _original_parent and _original_parent in story_unit_id_map:
                    _entity.parent_unit_id = story_unit_id_map[_original_parent]

            for key, model_cls, id_field in [
                ("batch_operation_records", BatchOperationRecord, "batch_id"),
                ("scripts", Script, "script_id"),
                ("anti_ai_rewrite_records", AntiAiRewriteRecord, "rewrite_id"),
                ("iteration_records", IterationRecord, "iteration_id"),
                ("proofread_drafts", ProofreadDraft, "draft_id"),
            ]:
                items = data.get(key, [])
                if isinstance(items, dict):
                    items = [items]
                cols_set = set(model_cls.__table__.columns.keys())
                for item_data in items:
                    if "project_id" in item_data:
                        item_data["project_id"] = new_project_id
                    old_ch_id = item_data.get("chapter_id", "")
                    if old_ch_id in chapter_id_map:
                        item_data["chapter_id"] = chapter_id_map[old_ch_id]
                    if key == "scripts":
                        old_suid = item_data.get("outline_unit_id", "")
                        if old_suid and old_suid in story_unit_id_map:
                            item_data["outline_unit_id"] = story_unit_id_map[old_suid]
                    if key == "anti_ai_rewrite_records":
                        old_vid = item_data.get("original_version_id", "")
                        if old_vid in version_id_map:
                            item_data["original_version_id"] = version_id_map[old_vid]
                    if key == "iteration_records":
                        for vid_field in ("input_version_id", "output_version_id"):
                            old_vid = item_data.get(vid_field, "")
                            if old_vid in version_id_map:
                                item_data[vid_field] = version_id_map[old_vid]
                    if key == "proofread_drafts":
                        old_vid = item_data.get("version_id", "")
                        if old_vid in version_id_map:
                            item_data["version_id"] = version_id_map[old_vid]
                    item_data[id_field] = str(uuid.uuid4())
                    _parse_datetime_fields(item_data, cols_set)
                    cols = {k: v for k, v in item_data.items() if k in cols_set}
                    self.session.add(model_cls(**cols))

            await self.session.flush()
            self.logger.info(f"项目导入成功: {new_project_id}")
            return {
                "project_id": new_project_id,
                "project_name": project_data.get("book_title", ""),
                "imported_at": datetime.now(timezone.utc).isoformat(),
                "warnings": warnings,
                "ai_source_hint": "请确认 AI 源配置可用后再开始撰写",
            }
        except Exception as e:
            self.logger.error(f"项目导入失败，事务回滚: {e}")
            raise
