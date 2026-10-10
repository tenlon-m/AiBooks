"""创作参数服务 - 参数校验、项目创建、梗概/世界观管理."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.creation_schema import (
    CreationParamsRequest,
    CreationParamsResponse,
    ProjectDto,
    ProjectSaveRequest,
    ProjectSaveResponse,
    ProjectSummaryDto,
    SynopsisResponse,
    WorldviewResponse,
)
from src.db.models import Project, Synopsis, Worldview, Chapter
from src.utils.logger import get_logger


class CreationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    async def create_project(self, req: CreationParamsRequest) -> CreationParamsResponse:
        existing = await self.session.execute(select(Project).where(Project.book_title == req.book_title))
        if existing.scalars().first():
            raise ValueError(f"书名已存在: {req.book_title}")
        project = Project(
            project_id=str(uuid.uuid4()),
            book_title=req.book_title,
            volume_count=req.volume_count,
            chapters_per_volume=req.chapters_per_volume,
            words_per_chapter=req.words_per_chapter,
            status="draft",
        )
        self.session.add(project)
        await self.session.flush()
        return CreationParamsResponse(
            project_id=project.project_id,
            book_title=project.book_title,
            volume_count=project.volume_count,
            chapters_per_volume=project.chapters_per_volume,
            words_per_chapter=project.words_per_chapter,
            created_at=project.created_at,
        )

    async def get_project(self, project_id: str) -> ProjectDto | None:
        project = await self.session.get(Project, project_id)
        if not project:
            return None
        synopsis = await self.session.get(Synopsis, project_id)
        worldview = await self.session.get(Worldview, project_id)
        return ProjectDto(
            project_id=project.project_id,
            book_title=project.book_title,
            volume_count=project.volume_count,
            chapters_per_volume=project.chapters_per_volume,
            words_per_chapter=project.words_per_chapter,
            style_library_id=project.style_library_id,
            status=project.status,
            created_at=project.created_at,
            updated_at=project.updated_at,
            has_synopsis=synopsis is not None,
            has_worldview=worldview is not None,
        )

    async def list_projects(self) -> list[ProjectDto]:
        result = await self.session.execute(select(Project))
        projects = list(result.scalars().all())
        project_ids = [p.project_id for p in projects]

        syn_result = await self.session.execute(
            select(Synopsis).where(Synopsis.project_id.in_(project_ids))
        )
        synopsis_ids = {s.project_id for s in syn_result.scalars().all()}

        wv_result = await self.session.execute(
            select(Worldview).where(Worldview.project_id.in_(project_ids))
        )
        worldview_ids = {w.project_id for w in w_result.scalars().all()}

        return [
            ProjectDto(
                project_id=p.project_id,
                book_title=p.book_title,
                volume_count=p.volume_count,
                chapters_per_volume=p.chapters_per_volume,
                words_per_chapter=p.words_per_chapter,
                style_library_id=p.style_library_id,
                status=p.status,
                created_at=p.created_at,
                updated_at=p.updated_at,
                has_synopsis=p.project_id in synopsis_ids,
                has_worldview=p.project_id in worldview_ids,
            )
            for p in projects
        ]

    async def set_synopsis(self, project_id: str, content: str, source: str) -> SynopsisResponse:
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        if len(content) < 50:
            raise ValueError("梗概内容不足50字")
        synopsis = await self.session.get(Synopsis, project_id)
        now = datetime.now(timezone.utc)
        if synopsis is None:
            synopsis = Synopsis(project_id=project_id, content=content, source=source, updated_at=now)
            self.session.add(synopsis)
        else:
            synopsis.content = content
            synopsis.source = source
            synopsis.updated_at = now
        await self.session.flush()
        return SynopsisResponse(project_id=project_id, content=content, source=source, updated_at=now)

    async def set_worldview(self, project_id: str, content: str, source: str) -> WorldviewResponse:
        project = await self.session.get(Project, project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        if len(content) < 50:
            raise ValueError("世界观内容不足50字")
        worldview = await self.session.get(Worldview, project_id)
        now = datetime.now(timezone.utc)
        if worldview is None:
            worldview = Worldview(project_id=project_id, content=content, source=source, updated_at=now)
            self.session.add(worldview)
        else:
            worldview.content = content
            worldview.source = source
            worldview.updated_at = now
        await self.session.flush()
        return WorldviewResponse(project_id=project_id, content=content, source=source, updated_at=now)

    async def get_synopsis(self, project_id: str) -> SynopsisResponse | None:
        synopsis = await self.session.get(Synopsis, project_id)
        if not synopsis:
            return None
        return SynopsisResponse(
            project_id=project_id,
            content=synopsis.content,
            source=synopsis.source,
            updated_at=synopsis.updated_at,
        )

    async def get_worldview(self, project_id: str) -> WorldviewResponse | None:
        worldview = await self.session.get(Worldview, project_id)
        if not worldview:
            return None
        return WorldviewResponse(
            project_id=project_id,
            content=worldview.content,
            source=worldview.source,
            updated_at=worldview.updated_at,
        )

    async def delete_project(self, project_id: str) -> bool:
        project = await self.session.get(Project, project_id)
        if not project:
            return False
        if project.status == "writing":
            raise ValueError("项目正在撰写中，无法删除")
        await self.session.delete(project)
        await self.session.flush()
        return True

    async def list_project_summaries(self) -> list[ProjectSummaryDto]:
        from sqlalchemy import func, desc

        result = await self.session.execute(
            select(Project).order_by(desc(Project.updated_at))
        )
        projects = list(result.scalars().all())
        if not projects:
            return []

        project_ids = [p.project_id for p in projects]
        chapter_result = await self.session.execute(
            select(
                Chapter.project_id,
                func.count().label("total"),
                func.sum(
                    func.cast(Chapter.gen_status == "completed", type_=Integer)
                ).label("written"),
            )
            .where(Chapter.project_id.in_(project_ids))
            .group_by(Chapter.project_id)
        )
        chapter_map: dict[str, tuple[int, int]] = {}
        for row in chapter_result:
            chapter_map[row.project_id] = (row.total, row.written or 0)

        dtos = []
        for p in projects:
            total, written = chapter_map.get(p.project_id, (0, 0))
            progress = (written / total * 100.0) if total > 0 else 0.0
            dtos.append(ProjectSummaryDto(
                project_id=p.project_id,
                book_title=p.book_title,
                status=p.status,
                created_at=p.created_at,
                updated_at=p.updated_at,
                total_chapters=total,
                written_chapters=written,
                writing_progress=round(progress, 1),
            ))
        return dtos
    async def save_project(self, req: ProjectSaveRequest) -> ProjectSaveResponse:
        """聚合保存工程：新建或更新项目 + 梗概 + 世界观，单事务原子性."""
        is_new = req.project_id is None
        if is_new:
            existing = await self.session.execute(select(Project).where(Project.book_title == req.book_title))
            if existing.scalars().first():
                raise ValueError(f"书名已存在: {req.book_title}")
            project = Project(
                project_id=str(uuid.uuid4()),
                book_title=req.book_title,
                volume_count=req.volume_count,
                chapters_per_volume=req.chapters_per_volume,
                words_per_chapter=req.words_per_chapter,
                status="draft",
            )
            self.session.add(project)
            await self.session.flush()
            project_id = project.project_id
        else:
            project = await self.session.get(Project, req.project_id)
            if not project:
                raise ValueError(f"项目不存在: {req.project_id}")
            project.book_title = req.book_title
            project.volume_count = req.volume_count
            project.chapters_per_volume = req.chapters_per_volume
            project.words_per_chapter = req.words_per_chapter
            await self.session.flush()
            project_id = req.project_id

        now = datetime.now(timezone.utc)
        if req.synopsis and len(req.synopsis) >= 50:
            synopsis = await self.session.get(Synopsis, project_id)
            if synopsis is None:
                synopsis = Synopsis(project_id=project_id, content=req.synopsis, source="manual_input", updated_at=now)
                self.session.add(synopsis)
            else:
                synopsis.content = req.synopsis
                synopsis.updated_at = now

        if req.worldview and len(req.worldview) >= 50:
            worldview = await self.session.get(Worldview, project_id)
            if worldview is None:
                worldview = Worldview(project_id=project_id, content=req.worldview, source="manual_input", updated_at=now)
                self.session.add(worldview)
            else:
                worldview.content = req.worldview
                worldview.updated_at = now

        await self.session.flush()
        synopsis_rec = await self.session.get(Synopsis, project_id)
        worldview_rec = await self.session.get(Worldview, project_id)
        return ProjectSaveResponse(
            project_id=project_id,
            book_title=req.book_title,
            is_new=is_new,
            message="工程已保存",
            has_synopsis=synopsis_rec is not None,
            has_worldview=worldview_rec is not None,
        )