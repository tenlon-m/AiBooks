"""风格库服务 - 语料投喂、AI提取6维特征、CRUD、导入导出、默认风格."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.gateway import get_gateway
from src.api.schemas.style_library_schema import (
    CorpusInfoDto,
    StyleFeatureDto,
    StyleLibraryDto,
    StyleLibraryUpdateRequest,
)
from src.config.settings import get_config
from src.db.models import StyleFeature, StyleLibrary
from src.db.session import release_write_lock
from src.services.import_service import ImportService
from src.utils.logger import get_logger

DEFAULT_STYLE_NAME = "默认风格"
DEFAULT_FEATURES = [
    StyleFeatureDto(dimension="narrative_pov", description="第三人称限知视角，以主角视角为主", source="builtin"),
    StyleFeatureDto(dimension="sentence_pattern", description="长短句交替，善用短句制造节奏感", source="builtin"),
    StyleFeatureDto(dimension="word_usage", description="现代口语化用词，避免生僻字和过度华丽辞藻", source="builtin"),
    StyleFeatureDto(dimension="rhythm", description="快节奏推进，张弛有度，战斗快日常慢", source="builtin"),
    StyleFeatureDto(dimension="paragraph_structure", description="短段落为主，每段2-5句，场景用空行分隔", source="builtin"),
    StyleFeatureDto(dimension="dialogue_style", description="对话自然口语化，角色语言有区分度", source="builtin"),
]


class StyleLibraryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()
        self.gateway = get_gateway()
        self.config = get_config()

    def _to_dto(self, sl: StyleLibrary, features: list[StyleFeature] | None = None) -> StyleLibraryDto:
        feature_list = features or []
        corpus = []
        if sl.corpus_info:
            try:
                corpus = [CorpusInfoDto(**c) for c in json.loads(sl.corpus_info)]
            except Exception as e:
                self.logger.warning(f"风格库 corpus_info JSON 解析失败: {e}")
        return StyleLibraryDto(
            style_library_id=sl.style_library_id,
            name=sl.name,
            naming_source=sl.naming_source,
            features=[
                StyleFeatureDto(
                    feature_id=f.feature_id,
                    dimension=f.dimension,
                    description=f.description,
                    source=f.source,
                )
                for f in feature_list
            ],
            corpus_info=corpus,
            built_at=sl.built_at,
            build_method=sl.build_method,
            confirmed=sl.confirmed,
        )

    async def ensure_default_style(self) -> StyleLibraryDto:
        """系统启动时确保默认内置风格库存在."""
        result = await self.session.execute(
            select(StyleLibrary).where(StyleLibrary.name == DEFAULT_STYLE_NAME)
        )
        sl = result.scalars().first()
        if sl is None:
            sl = StyleLibrary(
                style_library_id=str(uuid.uuid4()),
                name=DEFAULT_STYLE_NAME,
                naming_source="builtin",
                build_method="builtin",
                confirmed=True,
            )
            self.session.add(sl)
            await self.session.flush()
            for f in DEFAULT_FEATURES:
                feature = StyleFeature(
                    feature_id=str(uuid.uuid4()),
                    style_library_id=sl.style_library_id,
                    dimension=f.dimension,
                    description=f.description,
                    source="builtin",
                )
                self.session.add(feature)
            await self.session.flush()
        features = await self.session.execute(
            select(StyleFeature).where(StyleFeature.style_library_id == sl.style_library_id)
        )
        return self._to_dto(sl, list(features.scalars().all()))

    async def feed_and_build(
        self,
        file_paths: list[str],
        naming: str,
        name: str,
        user_ideas: str = "",
    ) -> StyleLibraryDto:
        """语料投喂 + AI提取风格特征 + 建立风格库."""
        existing = await self.session.execute(select(StyleLibrary).where(StyleLibrary.name == name))
        if existing.scalars().first():
            raise ValueError(f"风格库名称已存在: {name}")

        import_service = ImportService()
        corpus_infos = []
        all_text = []
        total_size = 0
        for fp in file_paths:
            parsed = import_service.parse(fp, "synopsis")
            if parsed.char_count < self.config.feed_min_single_chars:
                raise ValueError(f"文件 {fp} 内容过少（{parsed.char_count}字），需≥{self.config.feed_min_single_chars}字")
            all_text.append(parsed.content)
            corpus_infos.append(CorpusInfoDto(file_name=Path(fp).name, char_count=parsed.char_count))
            total_size += parsed.char_count
        if total_size > self.config.feed_max_total_size_mb * 1024 * 1024:
            raise ValueError(f"投喂总量超限: {total_size / 1024 / 1024:.1f}MB")

        corpus_text = "\n\n".join(all_text)
        if len(corpus_text) > 50000:
            corpus_text = corpus_text[:50000]

        # 下面是最长 style 提取时长量级的 AI 调用。只要本会话（或调用方）还有
        # 未提交的 DML，写锁就会一直被持有到 commit，期间会阻塞自动保存与网关
        # 计数器写回（database is locked）。进入 AI 调用前先结束事务。
        await release_write_lock(self.session)

        result = await self.gateway.call_and_parse(
            module="style",
            scene="extract-features",
            params={"corpus_text": corpus_text, "user_ideas": user_ideas},
        )
        features_data = result.get("parsed", {}).get("features", [])
        features = [
            StyleFeatureDto(
                dimension=f.get("dimension", "other"),
                description=f.get("description", ""),
                source="ai_extract",
            )
            for f in features_data
        ]
        if not features:
            features = DEFAULT_FEATURES

        sl = StyleLibrary(
            style_library_id=str(uuid.uuid4()),
            name=name,
            naming_source=naming,
            corpus_info=json.dumps([c.model_dump() for c in corpus_infos]),
            build_method="feed",
            confirmed=False,
        )
        self.session.add(sl)
        await self.session.flush()
        for f in features:
            feature = StyleFeature(
                feature_id=str(uuid.uuid4()),
                style_library_id=sl.style_library_id,
                dimension=f.dimension,
                description=f.description,
                source=f.source,
            )
            self.session.add(feature)
        await self.session.flush()

        feat_entities = await self.session.execute(
            select(StyleFeature).where(StyleFeature.style_library_id == sl.style_library_id)
        )
        return self._to_dto(sl, list(feat_entities.scalars().all()))

    async def list_all(self) -> list[StyleLibraryDto]:
        result = await self.session.execute(select(StyleLibrary))
        libraries = list(result.scalars().all())
        if not libraries:
            return []
        lib_ids = [sl.style_library_id for sl in libraries]
        feat_result = await self.session.execute(
            select(StyleFeature).where(StyleFeature.style_library_id.in_(lib_ids))
        )
        features_map: dict[str, list[StyleFeature]] = {}
        for feat in feat_result.scalars().all():
            features_map.setdefault(feat.style_library_id, []).append(feat)
        return [self._to_dto(sl, features_map.get(sl.style_library_id, [])) for sl in libraries]

    async def get(self, style_library_id: str) -> StyleLibraryDto | None:
        sl = await self.session.get(StyleLibrary, style_library_id)
        if not sl:
            return None
        features = await self.session.execute(
            select(StyleFeature).where(StyleFeature.style_library_id == style_library_id)
        )
        return self._to_dto(sl, list(features.scalars().all()))

    async def update(self, style_library_id: str, req: StyleLibraryUpdateRequest) -> StyleLibraryDto:
        sl = await self.session.get(StyleLibrary, style_library_id)
        if not sl:
            raise ValueError(f"风格库不存在: {style_library_id}")
        if req.name is not None:
            existing = await self.session.execute(
                select(StyleLibrary).where(StyleLibrary.name == req.name, StyleLibrary.style_library_id != style_library_id)
            )
            if existing.scalars().first():
                raise ValueError(f"风格库名称已存在: {req.name}")
            sl.name = req.name
        if req.confirmed is not None:
            sl.confirmed = req.confirmed
        if req.features is not None:
            old_features = await self.session.execute(
                select(StyleFeature).where(StyleFeature.style_library_id == style_library_id)
            )
            for f in old_features.scalars().all():
                await self.session.delete(f)
            for f in req.features:
                feature = StyleFeature(
                    feature_id=str(uuid.uuid4()),
                    style_library_id=style_library_id,
                    dimension=f.dimension,
                    description=f.description,
                    source="user_edit",
                )
                self.session.add(feature)
        await self.session.flush()
        return await self.get(style_library_id)

    async def delete(self, style_library_id: str) -> bool:
        sl = await self.session.get(StyleLibrary, style_library_id)
        if not sl:
            return False
        if sl.build_method == "builtin":
            raise ValueError("默认内置风格库不可删除")
        await self.session.delete(sl)
        await self.session.flush()
        return True

    async def export_library(self, style_library_id: str, target_path: str) -> str:
        """导出风格库为 JSON 文件."""
        dto = await self.get(style_library_id)
        if not dto:
            raise ValueError(f"风格库不存在: {style_library_id}")
        data = dto.model_dump(mode="json")
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    async def import_library(self, file_path: str, conflict_strategy: str = "rename") -> StyleLibraryDto:
        """从 JSON 文件导入风格库."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        name = data.get("name", "")
        existing = await self.session.execute(select(StyleLibrary).where(StyleLibrary.name == name))
        existing_sl = existing.scalars().first()
        if existing_sl:
            if conflict_strategy == "overwrite":
                await self.session.delete(existing_sl)
                await self.session.flush()
            elif conflict_strategy == "rename":
                name = f"{name}_导入_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            else:
                raise ValueError("命名冲突，已取消")

        sl = StyleLibrary(
            style_library_id=str(uuid.uuid4()),
            name=name,
            naming_source="import",
            corpus_info=json.dumps(data.get("corpus_info", [])),
            build_method="import",
            confirmed=data.get("confirmed", True),
        )
        self.session.add(sl)
        await self.session.flush()
        for f in data.get("features", []):
            feature = StyleFeature(
                feature_id=str(uuid.uuid4()),
                style_library_id=sl.style_library_id,
                dimension=f.get("dimension", "other"),
                description=f.get("description", ""),
                source="import",
            )
            self.session.add(feature)
        await self.session.flush()
        return await self.get(sl.style_library_id)
    async def delete_batch(self, style_library_ids: list[str]) -> int:
        """单事务内批量删除风格库（含级联删除关联特征），返回实际删除数量.

        风格库为全局共享资源（无 project_id 归属），项目隔离通过仅删除传入
        ID 中实际存在的记录实现：不存在的 ID 被跳过（幂等删除语义）。
        默认内置风格库不可删除，遇到时跳过并记录警告。
        """
        if not style_library_ids:
            raise ValueError("未选中任何风格库")

        result = await self.session.execute(
            select(StyleLibrary).where(StyleLibrary.style_library_id.in_(style_library_ids))
        )
        entities = list(result.scalars().all())
        deleted = 0
        for sl in entities:
            if sl.build_method == "builtin":
                self.logger.warning(f"默认内置风格库不可删除，已跳过: {sl.style_library_id}")
                continue
            await self.session.delete(sl)
            deleted += 1
        await self.session.commit()
        return deleted