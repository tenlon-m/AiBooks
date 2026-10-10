"""SQLite 写锁释放 - 回归测试.

缺陷现场（用户上报）
--------------------
AI 生成大纲时弹出 "自动保存多次失败，请检查存储空间与数据库状态"，日志同时出现::

    src.ai.gateway:212 - AI源计数器写回失败（已忽略，不影响业务）:
    OperationalError: (sqlite3.OperationalError) database is locked
    [SQL: UPDATE ai_sources SET health_status=?, success_count=?, fail_count=?, updated_at=? ...]

根因（已实测验证）
------------------
SQLite 是单写者模型，锁是**数据库级**的。SQLAlchemy 的 Session 只要执行过任一
DML（含显式 ``flush()``）就开启写事务并持有写锁，直到 commit/rollback；
而**纯 SELECT 不持有任何写锁**。

``OutlineService.generate_outline_batch`` 改造前的顺序是::

    _reset_outline()          -> delete + flush()  ← 拿到写锁
    _collect_generated()      -> SELECT
    ensure_sufficient_for_outline()  -> 网关调用（数十秒~数分钟）  ← 写锁一直被攥着
    session.commit()          ← 太晚了

于是这段时间里所有其它写入者（网关的 AI 源计数器写回、AI 调用日志、前端
``POST /api/creation/save``）全部在 busy_timeout 耗尽后报 database is locked。

修复：长 AI 调用前调用 ``src.db.session.release_write_lock()``。

本测试用"独立连接写入探针"验证 AI 调用发生的那一刻写锁确实已经释放。
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any, Coroutine

import pytest
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    event,
    select,
    update,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from src.api.schemas.outline_schema import (
    ChapterDraft,
    OutlineBatchGenerateRequest,
    OutlineDraft,
    OutlineGenerateRequest,
    VolumeBatchDraft,
    VolumeDraft,
)
from src.db.models import Base, Character, ChapterOutline, Project, Synopsis, Worldview
from src.db.session import release_write_lock
from src.services.auto_supporting_service import AutoSupportingService
from src.services.outline_service import OutlineService

# 独立探针表：用于"另开一条连接尝试真实写入"。
# 单独建表是为了避免探针污染被测业务的字段。
_PROBE_META = MetaData()
_PROBE = Table(
    "lock_probe",
    _PROBE_META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("note", String(32), nullable=False),
)

# 探针用的超时：测试里要让"锁冲突"快速暴露，而不是等生产环境的 60s
_BUSY_TIMEOUT_MS = 300
_CHAPTERS_PER_VOLUME = 2


# --------------------------------------------------------------------------- #
# 基础设施
# --------------------------------------------------------------------------- #


async def _make_env(tmp_path: Any) -> tuple[AsyncEngine, async_sessionmaker]:
    """建一个与生产同构的 SQLite(WAL) 环境."""
    db_path = tmp_path / "write_lock.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"timeout": _BUSY_TIMEOUT_MS / 1000},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_PROBE_META.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return engine, factory


async def _seed_project(factory: async_sessionmaker) -> str:
    """写入一个可跑通大纲流程的最小项目."""
    project_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Project(
                project_id=project_id,
                book_title=f"锁测试-{project_id[:8]}",
                volume_count=1,
                chapters_per_volume=_CHAPTERS_PER_VOLUME,
                words_per_chapter=2000,
                status="draft",
            )
        )
        session.add(Synopsis(project_id=project_id, content="梗概" * 60, source="manual"))
        session.add(Worldview(project_id=project_id, content="世界观" * 60, source="manual"))
        session.add(
            Character(
                character_id=str(uuid.uuid4()),
                project_id=project_id,
                name="主角",
                identity="主角",
                source="manual_input",
                confirmed=True,
            )
        )
        await session.commit()
    return project_id


async def _probe_write(factory: async_sessionmaker) -> None:
    """用"另一条独立连接"做一次真实写入.

    若此刻有别的连接正持有 SQLite 写锁，这里会抛
    ``OperationalError: (sqlite3.OperationalError) database is locked``。
    """
    async with factory() as session:
        await session.execute(_PROBE.insert().values(note="probe"))
        await session.commit()


def _run(coro: Coroutine[Any, Any, None]) -> None:
    """在单个事件循环里跑完整场景，避免异步 fixture 的 loop 绑定问题."""
    asyncio.run(coro)


# --------------------------------------------------------------------------- #
# 1. release_write_lock 自身语义
# --------------------------------------------------------------------------- #


async def _case_release_write_lock_ends_transaction(tmp_path: Any) -> None:
    engine, factory = await _make_env(tmp_path)
    try:
        project_id = await _seed_project(factory)
        async with factory() as session:
            # 造成未提交的 DML —— 这正是"持有写锁"的来源
            await session.execute(
                update(Project)
                .where(Project.project_id == project_id)
                .values(status="writing")
            )
            assert session.in_transaction()

            await release_write_lock(session)

            assert not session.in_transaction()
            # expire_on_commit=False：提交后对象仍可安全读取，无需重查
            project = await session.get(Project, project_id)
            assert project is not None
            assert project.status == "writing"

        # 锁已释放：其它连接可以正常写入
        await _probe_write(factory)
    finally:
        await engine.dispose()


def test_release_write_lock_ends_transaction(tmp_path: Any) -> None:
    _run(_case_release_write_lock_ends_transaction(tmp_path))


async def _case_release_write_lock_is_noop_without_transaction(tmp_path: Any) -> None:
    engine, factory = await _make_env(tmp_path)
    try:
        await _seed_project(factory)
        async with factory() as session:
            await release_write_lock(session)  # 无事务时不应报错
            assert not session.in_transaction()
        async with factory() as session:
            # 纯只读会话同样可以安全调用
            await session.execute(select(Project))
            await release_write_lock(session)
            assert not session.in_transaction()
    finally:
        await engine.dispose()


def test_release_write_lock_is_noop_without_transaction(tmp_path: Any) -> None:
    _run(_case_release_write_lock_is_noop_without_transaction(tmp_path))


# --------------------------------------------------------------------------- #
# 2. 锁定"病因"本身：未提交 DML 才会阻塞别人；纯读不会
# --------------------------------------------------------------------------- #


async def _case_uncommitted_dml_blocks_others(tmp_path: Any) -> None:
    engine, factory = await _make_env(tmp_path)
    try:
        project_id = await _seed_project(factory)
        async with factory() as holder:
            await holder.execute(
                update(Project)
                .where(Project.project_id == project_id)
                .values(status="holding")
            )
            # 未提交 → 写锁被 holder 独占
            with pytest.raises(OperationalError):
                await _probe_write(factory)
            await holder.rollback()

        # 释放后可写：证明上面的失败确实来自锁，而不是探针本身有问题
        await _probe_write(factory)
    finally:
        await engine.dispose()


def test_uncommitted_dml_blocks_other_connection(tmp_path: Any) -> None:
    """复现用户日志里的 database is locked（同时验证探针有效）."""
    _run(_case_uncommitted_dml_blocks_others(tmp_path))


async def _case_readonly_session_does_not_block(tmp_path: Any) -> None:
    engine, factory = await _make_env(tmp_path)
    try:
        await _seed_project(factory)
        async with factory() as reader:
            await reader.execute(select(Project))
            assert reader.in_transaction()  # SQLAlchemy 层有事务
            # 但 DBAPI 层未开启写事务 → 不持有 SQLite 写锁
            await _probe_write(factory)
    finally:
        await engine.dispose()


def test_readonly_session_does_not_block_writers(tmp_path: Any) -> None:
    """固定"病因边界"：只有未提交的 DML 才持锁，纯读不持锁."""
    _run(_case_readonly_session_does_not_block(tmp_path))


# --------------------------------------------------------------------------- #
# 3. 核心回归：AI 调用期间不能持有写锁
# --------------------------------------------------------------------------- #


def test_outline_batch_releases_write_lock_before_ai_calls(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """分批生成大纲：在每个 AI 调用点，写锁都必须已经释放.

    复现路径：``_reset_outline()`` 的 ``flush()`` 拿到写锁 →
    ``ensure_sufficient_for_outline()``（AI 调用）→ ``build_batch_and_call()``（AI 调用）。
    """
    _run(_case_outline_batch(tmp_path, monkeypatch))


async def _case_outline_batch(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory = await _make_env(tmp_path)
    try:
        project_id = await _seed_project(factory)
        ai_call_probes: list[str] = []

        async def _fake_ensure(
            self: Any, pid: str, synopsis: str, worldview: str, characters: list[Any]
        ) -> Any:
            # 探针：这里等价于"网关调用即将发出"的时刻
            await _probe_write(factory)
            ai_call_probes.append("supporting")
            return SimpleNamespace(added=[], temporary=[], warnings=[])

        async def _fake_build_batch(self: Any, **kwargs: Any) -> VolumeBatchDraft:
            await _probe_write(factory)
            ai_call_probes.append("batch")
            return VolumeBatchDraft(
                volume_no=1,
                volume_name="第一卷",
                chapters=[
                    ChapterDraft(
                        chapter_no=1, chapter_name="开局", synopsis_points="主角登场"
                    )
                ],
            )

        monkeypatch.setattr(
            AutoSupportingService, "ensure_sufficient_for_outline", _fake_ensure
        )
        from src.services.outline_builder import OutlineBuilder

        monkeypatch.setattr(
            OutlineBuilder, "build_batch_and_call", _fake_build_batch
        )

        async with factory() as session:
            service = OutlineService(session)
            dto = await service.generate_outline_batch(
                project_id,
                OutlineBatchGenerateRequest(
                    volume_no=1, chapter_start=1, chapter_count=1, reset=True
                ),
            )

        assert ai_call_probes == ["supporting", "batch"], (
            "两个 AI 调用点都应先释放写锁；若为 ['supporting'] 说明批次调用仍持锁"
        )
        assert dto.gen_status == "生成中"

        # 批次结果确实落库了
        async with factory() as session:
            rows = (await session.execute(select(ChapterOutline))).scalars().all()
        assert len(rows) == 1
        assert rows[0].synopsis_points == "主角登场"

        # 流程结束时不应残留悬挂事务
        await _probe_write(factory)
    finally:
        await engine.dispose()


def test_auto_supporting_releases_caller_write_lock(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """调用方已持有未提交 DML 时，自动配角流程的 AI 调用前必须先释放写锁."""
    _run(_case_auto_supporting(tmp_path, monkeypatch))


async def _case_auto_supporting(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory = await _make_env(tmp_path)
    try:
        project_id = await _seed_project(factory)
        scenes: list[str] = []

        async def _fake_call_and_parse(**kwargs: Any) -> dict[str, Any]:
            # 探针：网关调用发出的那一刻
            await _probe_write(factory)
            scenes.append(str(kwargs.get("scene")))
            return {"parsed": {"needed_count": 0}}

        async with factory() as session:
            service = AutoSupportingService(session)
            service.gateway = SimpleNamespace(call_and_parse=_fake_call_and_parse)

            # 伪造"调用方已持有未提交的写事务"（例如大纲 reset 的 flush）
            await session.execute(
                update(Project)
                .where(Project.project_id == project_id)
                .values(status="writing")
            )
            assert session.in_transaction()

            await service.ensure_sufficient_for_outline(
                project_id, "梗概" * 60, "世界观" * 60, []
            )

        assert scenes == ["auto-generate-supporting"]
        # 调用方的写被提交而非悬挂丢弃
        async with factory() as session:
            project = await session.get(Project, project_id)
            assert project is not None and project.status == "writing"
        await _probe_write(factory)
    finally:
        await engine.dispose()


def test_generate_outline_releases_write_lock_before_ai(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """整本生成大纲：两次 AI 调用前都不应持有写锁."""
    _run(_case_generate_outline(tmp_path, monkeypatch))


async def _case_generate_outline(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory = await _make_env(tmp_path)
    try:
        project_id = await _seed_project(factory)
        ai_call_probes: list[str] = []

        async def _fake_ensure(
            self: Any, pid: str, synopsis: str, worldview: str, characters: list[Any]
        ) -> Any:
            await _probe_write(factory)
            ai_call_probes.append("supporting")
            return SimpleNamespace(added=[], temporary=[], warnings=[])

        async def _fake_build(self: Any, **kwargs: Any) -> OutlineDraft:
            await _probe_write(factory)
            ai_call_probes.append("outline")
            return OutlineDraft(
                volumes=[
                    VolumeDraft(
                        volume_no=1,
                        volume_name="第一卷",
                        chapters=[
                            ChapterDraft(
                                chapter_no=n,
                                chapter_name=f"第{n}章",
                                synopsis_points=f"要点{n}",
                            )
                            for n in range(1, _CHAPTERS_PER_VOLUME + 1)
                        ],
                    )
                ]
            )

        monkeypatch.setattr(
            AutoSupportingService, "ensure_sufficient_for_outline", _fake_ensure
        )
        from src.services.outline_builder import OutlineBuilder

        monkeypatch.setattr(OutlineBuilder, "build_and_call", _fake_build)

        async with factory() as session:
            service = OutlineService(session)
            dto = await service.generate_outline(
                project_id, OutlineGenerateRequest(force_overwrite=True)
            )

        assert ai_call_probes == ["supporting", "outline"]
        assert dto.gen_status == "已生成"
        await _probe_write(factory)
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# 4. 网关计数器写回（用户日志里的直接报错点）不再被阻塞
# --------------------------------------------------------------------------- #

def test_gateway_counter_write_not_blocked_during_outline(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模拟网关的 AI 源计数器写回：在大纲 AI 调用期间必须能成功写入."""
    _run(_case_gateway_counter(tmp_path, monkeypatch))


async def _case_gateway_counter(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory = await _make_env(tmp_path)
    try:
        project_id = await _seed_project(factory)
        counter_updates: list[str] = []

        async def _fake_ensure(
            self: Any, pid: str, synopsis: str, worldview: str, characters: list[Any]
        ) -> Any:
            # 等价于 gateway._apply_source_updates 的那条 UPDATE ai_sources
            await _probe_write(factory)
            counter_updates.append("ok")
            return SimpleNamespace(added=[], temporary=[], warnings=[])

        async def _fake_build_batch(self: Any, **kwargs: Any) -> VolumeBatchDraft:
            await _probe_write(factory)
            counter_updates.append("ok")
            return VolumeBatchDraft(
                volume_no=1,
                volume_name="第一卷",
                chapters=[ChapterDraft(chapter_no=1, synopsis_points="要点")],
            )

        monkeypatch.setattr(
            AutoSupportingService, "ensure_sufficient_for_outline", _fake_ensure
        )
        from src.services.outline_builder import OutlineBuilder

        monkeypatch.setattr(OutlineBuilder, "build_batch_and_call", _fake_build_batch)

        async with factory() as session:
            await OutlineService(session).generate_outline_batch(
                project_id,
                OutlineBatchGenerateRequest(
                    volume_no=1, chapter_start=1, chapter_count=1, reset=True
                ),
            )

        assert counter_updates == ["ok", "ok"]
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# 5. 撰写流程里的同类实例：物品抽取跨越"本章未提交的写入"
# --------------------------------------------------------------------------- #


def test_item_extraction_releases_chapter_write_lock(tmp_path: Any) -> None:
    """撰写每章时，本章正文/状态已写入会话，物品抽取的 AI 调用前必须先提交.

    这是与大纲同源的第二个实例：``writing_service`` 在设置完
    ``chapter.content``/``gen_status`` 后调用 ``ItemService.extract_and_save``，
    其中还夹着一次 AI 调用；若不先提交，写锁会在该 AI 调用期间被独占。
    """
    _run(_case_item_extraction(tmp_path))


async def _case_item_extraction(tmp_path: Any) -> None:
    engine, factory = await _make_env(tmp_path)
    try:
        project_id = await _seed_project(factory)
        scenes: list[str] = []

        async def _fake_call_and_parse(**kwargs: Any) -> dict[str, Any]:
            # 探针：物品抽取的 AI 调用发出的那一刻
            await _probe_write(factory)
            scenes.append(str(kwargs.get("scene")))
            return {"parsed": {"items": []}}

        from src.db.models import Chapter
        from src.services.item_service import ItemService

        chapter_id = str(uuid.uuid4())
        async with factory() as session:
            # 模拟 writing_service 已经写好的本章记录
            session.add(
                Chapter(
                    chapter_id=chapter_id,
                    project_id=project_id,
                    volume_no=1,
                    chapter_no=1,
                    title="第一章",
                    gen_status="writing",
                    modify_status="none",
                    word_count=0,
                )
            )
            await session.commit()

        async with factory() as session:
            service = ItemService(session)
            service.gateway = SimpleNamespace(call_and_parse=_fake_call_and_parse)

            # 模拟"本章正文刚写好并已落库但尚未提交"——这正是写锁的来源。
            # 注意：会话配置了 autoflush=False，单纯给属性赋值不会真的写库，
            # 所以这里必须显式 flush 才能拿到 SQLite 写锁。
            chapter = await session.get(Chapter, chapter_id)
            assert chapter is not None
            chapter.content = "正文内容" * 50
            chapter.word_count = len(chapter.content)
            chapter.gen_status = "completed"
            await session.flush()
            assert session.in_transaction()

            await service.extract_and_save(project_id, chapter.content, 1, 1)

        assert scenes == ["extract-items"]
        await _probe_write(factory)
    finally:
        await engine.dispose()
