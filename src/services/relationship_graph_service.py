"""角色关系图谱服务 - 关系 CRUD、图谱查询与从角色描述自动提取."""
from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.relationship_schema import (
    AutoExtractResult,
    CharacterRelationshipDto,
    RelationshipCreateRequest,
    RelationshipGraphDto,
    RelationshipUpdateRequest,
)
from src.db.models import Character, CharacterRelationship, Project
from src.utils.logger import get_logger

_RELATION_PATTERNS: list[tuple[str, str]] = [
    (r"(.+?)的(父亲|母亲|哥哥|弟弟|姐姐|妹妹|儿子|女儿|爷爷|奶奶|叔叔|阿姨)", "family"),
    (r"(.+?)与(.+?)是(兄弟|姐妹|兄妹|姐弟|父子|父女|母子|母女)", "family"),
    (r"(.+?)的(师父|师傅|徒弟|弟子|师尊)", "master_apprentice"),
    (r"(.+?)拜(.+?)为师", "master_apprentice"),
    (r"(.+?)与(.+?)是(朋友|挚友|知己|好友|闺蜜)", "friend"),
    (r"(.+?)与(.+?)(交好|结盟|同盟)", "friend"),
    (r"(.+?)与(.+?)是(敌人|仇人|宿敌|死敌)", "hostile"),
    (r"(.+?)与(.+?)(交恶|为敌|对立|仇视)", "hostile"),
    (r"(.+?)是(.+?)的(仆人|侍女|下属|随从)", "servant_master"),
    (r"(.+?)侍奉(.+?)", "servant_master"),
    (r"(.+?)与(.+?)是(恋人|情侣|夫妻|爱人)", "lover"),
    (r"(.+?)爱(上|着)?(.+?)", "lover"),
]


class RelationshipGraphService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    @staticmethod
    def _to_dto(rel: CharacterRelationship) -> CharacterRelationshipDto:
        return CharacterRelationshipDto(
            relationship_id=rel.relationship_id,
            project_id=rel.project_id,
            source_character_id=rel.source_character_id,
            target_character_id=rel.target_character_id,
            relation_type=rel.relation_type,
            description=rel.description,
        )

    async def create(self, project_id: str, req: RelationshipCreateRequest) -> CharacterRelationshipDto:
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        rel = CharacterRelationship(
            relationship_id=str(uuid.uuid4()),
            project_id=project_id,
            source_character_id=req.source_character_id,
            target_character_id=req.target_character_id,
            relation_type=req.relation_type,
            description=req.description,
        )
        self.session.add(rel)
        await self.session.commit()
        self.logger.info(f"创建角色关系 relationship_id={rel.relationship_id} project_id={project_id} type={req.relation_type}")
        return self._to_dto(rel)

    async def get_graph(self, project_id: str) -> RelationshipGraphDto:
        chars_result = await self.session.execute(
            select(Character).where(Character.project_id == project_id)
        )
        nodes = [
            {
                "character_id": c.character_id,
                "name": c.name,
                "identity": c.identity,
                "intro": c.intro or "",
                "relation": c.relation or "",
            }
            for c in chars_result.scalars().all()
        ]
        rel_result = await self.session.execute(
            select(CharacterRelationship).where(
                CharacterRelationship.project_id == project_id
            )
        )
        edges = [self._to_dto(r) for r in rel_result.scalars().all()]
        return RelationshipGraphDto(project_id=project_id, nodes=nodes, edges=edges)

    async def save_relations(self, project_id: str, relations: list[dict]) -> dict:
        """按全量列表保存关系：有 id 的更新，无 id 的新建，缺的被删除."""
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")

        existing_result = await self.session.execute(
            select(CharacterRelationship).where(
                CharacterRelationship.project_id == project_id
            )
        )
        existing = {r.relationship_id: r for r in existing_result.scalars().all()}
        kept_ids: set[str] = set()

        for item in relations:
            rel_id = item.get("relationship_id")
            relation_type = item.get("relation_type")
            source_id = item.get("source_character_id")
            target_id = item.get("target_character_id")
            if not relation_type or not source_id or not target_id:
                continue
            description = item.get("description")
            if rel_id and rel_id in existing:
                entity = existing[rel_id]
                entity.source_character_id = source_id
                entity.target_character_id = target_id
                entity.relation_type = relation_type
                entity.description = description
                kept_ids.add(rel_id)
            else:
                entity = CharacterRelationship(
                    relationship_id=str(uuid.uuid4()),
                    project_id=project_id,
                    source_character_id=source_id,
                    target_character_id=target_id,
                    relation_type=relation_type,
                    description=description,
                )
                self.session.add(entity)
                kept_ids.add(entity.relationship_id)

        for rel_id, entity in existing.items():
            if rel_id not in kept_ids:
                await self.session.delete(entity)

        await self.session.commit()
        self.logger.info(f"全量保存角色关系 project_id={project_id} kept_count={len(kept_ids)}")
        return {"saved_count": len(kept_ids)}

    async def update(
        self, project_id: str, relationship_id: str, req: RelationshipUpdateRequest
    ) -> CharacterRelationshipDto:
        rel = await self.session.get(CharacterRelationship, relationship_id)
        if not rel or rel.project_id != project_id:
            raise ValueError("角色关系不存在")
        if req.relation_type is not None:
            rel.relation_type = req.relation_type
        if req.description is not None:
            rel.description = req.description
        await self.session.commit()
        self.logger.info(f"更新角色关系 relationship_id={relationship_id} project_id={project_id}")
        return self._to_dto(rel)

    async def delete(self, project_id: str, relationship_id: str) -> int:
        rel = await self.session.get(CharacterRelationship, relationship_id)
        if not rel or rel.project_id != project_id:
            raise ValueError("角色关系不存在")
        await self.session.delete(rel)
        await self.session.commit()
        self.logger.info(f"删除角色关系 relationship_id={relationship_id} project_id={project_id}")
        return 1

    async def auto_extract(self, project_id: str) -> AutoExtractResult:
        """从 Character.relation 文本提取关系并落库."""
        chars_result = await self.session.execute(
            select(Character).where(Character.project_id == project_id)
        )
        characters = chars_result.scalars().all()
        name_to_id = {c.name: c.character_id for c in characters}
        extracted: list[CharacterRelationshipDto] = []
        skipped = 0
        for char in characters:
            if not char.relation:
                continue
            for pattern, rel_type in _RELATION_PATTERNS:
                for match in re.finditer(pattern, char.relation):
                    src_name = match.group(1).strip()
                    tgt_name = match.group(2).strip()
                    src_id = name_to_id.get(src_name)
                    tgt_id = name_to_id.get(tgt_name)
                    if not src_id or not tgt_id or src_id == tgt_id:
                        skipped += 1
                        continue
                    entity = CharacterRelationship(
                        relationship_id=str(uuid.uuid4()),
                        project_id=project_id,
                        source_character_id=src_id,
                        target_character_id=tgt_id,
                        relation_type=rel_type,
                        description=f"从 {char.name} 的关系描述自动提取",
                    )
                    self.session.add(entity)
                    await self.session.flush()
                    extracted.append(self._to_dto(entity))
        await self.session.commit()
        self.logger.info(f"自动提取角色关系落库 project_id={project_id} extracted={len(extracted)} skipped={skipped}")
        return AutoExtractResult(extracted=extracted, skipped=skipped)