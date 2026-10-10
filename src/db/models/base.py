"""SQLAlchemy ORM 实体 - 18 个领域对象.

按 design.md 2.3.2 定义，含完整字段、关系与约束。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    LargeBinary,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """声明式基类."""

    pass


class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    book_title: Mapped[str] = mapped_column(String(50), nullable=False)
    volume_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chapters_per_volume: Mapped[int] = mapped_column(Integer, nullable=False)
    words_per_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    style_library_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("style_libraries.style_library_id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    synopsis: Mapped["Synopsis | None"] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
    worldview: Mapped["Worldview | None"] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
    characters: Mapped[list["Character"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    cool_points: Mapped[list["CoolPoint"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    hooks: Mapped[list["Hook"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    chapters: Mapped[list["Chapter"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    items: Mapped[list["Item"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    validation_reports: Mapped[list["ValidationReport"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    outline: Mapped["Outline | None"] = relationship("Outline", uselist=False, back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("book_title", name="uq_project_title"),)


class Synopsis(Base):
    __tablename__ = "synopses"

    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    project: Mapped["Project"] = relationship(back_populates="synopsis")


class Worldview(Base):
    __tablename__ = "worldviews"

    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    project: Mapped["Project"] = relationship(back_populates="worldview")


class Character(Base):
    __tablename__ = "characters"

    character_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(20), nullable=False)
    identity: Mapped[str] = mapped_column(String(100), nullable=False)
    intro: Mapped[str] = mapped_column(Text, nullable=True)
    relation: Mapped[str] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    appearance_records: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    supporting_type: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    auto_gen_context: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    future_reference: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    scope_type: Mapped[str | None] = mapped_column(String(10), nullable=True, default="全书")
    scope_unit_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped["Project"] = relationship(back_populates="characters")


class CoolPoint(Base):
    __tablename__ = "cool_points"

    cool_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    volume_no: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_no: Mapped[int] = mapped_column(Integer, nullable=False)
    cool_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content_desc: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)

    project: Mapped["Project"] = relationship(back_populates="cool_points")

    __table_args__ = (Index("ix_cool_point_loc", "project_id", "volume_no", "chapter_no"),)


class Hook(Base):
    __tablename__ = "hooks"

    hook_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    volume_no: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_no: Mapped[int] = mapped_column(Integer, nullable=False)
    hook_content: Mapped[str] = mapped_column(Text, nullable=False)
    recycle_volume_no: Mapped[int] = mapped_column(Integer, nullable=False)
    recycle_chapter_no: Mapped[int] = mapped_column(Integer, nullable=False)
    recycle_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    source: Mapped[str] = mapped_column(String(20), nullable=False)

    project: Mapped["Project"] = relationship(back_populates="hooks")

    __table_args__ = (Index("ix_hook_loc", "project_id", "volume_no", "chapter_no"),)


class Chapter(Base):
    __tablename__ = "chapters"

    chapter_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    volume_no: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gen_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    modify_status: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_modified_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped["Project"] = relationship(back_populates="chapters")
    modify_records: Mapped[list["ModifyRecord"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")
    versions: Mapped[list["ChapterVersion"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")
    annotations: Mapped[list["ChapterAnnotation"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")
    scenes: Mapped[list["ChapterScene"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")
    summary: Mapped["ChapterSummary | None"] = relationship(back_populates="chapter", uselist=False, cascade="all, delete-orphan")
    chat_histories: Mapped[list["WritingChatHistory"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("project_id", "volume_no", "chapter_no", name="uq_chapter_loc"),
    )


class Item(Base):
    __tablename__ = "items"

    item_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    key_attrs: Mapped[str] = mapped_column(Text, nullable=True)
    owner_character: Mapped[str] = mapped_column(String(50), nullable=True)
    first_appear_volume: Mapped[int] = mapped_column(Integer, nullable=False)
    first_appear_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped["Project"] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_item_name_in_project"),
    )


class StyleLibrary(Base):
    __tablename__ = "style_libraries"

    style_library_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    naming_source: Mapped[str] = mapped_column(String(20), nullable=False, default="custom")
    corpus_info: Mapped[str] = mapped_column(Text, nullable=True)
    built_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    build_method: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    features: Mapped[list["StyleFeature"]] = relationship(back_populates="style_library", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("name", name="uq_style_library_name"),)


class StyleFeature(Base):
    __tablename__ = "style_features"

    feature_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    style_library_id: Mapped[str] = mapped_column(String(36), ForeignKey("style_libraries.style_library_id", ondelete="CASCADE"), nullable=False, index=True)
    dimension: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="ai_extract")

    style_library: Mapped["StyleLibrary"] = relationship(back_populates="features")


class ModifyRecord(Base):
    __tablename__ = "modify_records"

    record_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapters.chapter_id", ondelete="CASCADE"), nullable=False, index=True)
    modify_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual_edit")
    content_before: Mapped[str] = mapped_column(Text, nullable=True)
    content_after: Mapped[str] = mapped_column(Text, nullable=True)
    rollback_target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    modified_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    revalidate_result: Mapped[str] = mapped_column(Text, nullable=True)
    triggered_polish: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    polished_content: Mapped[str] = mapped_column(Text, nullable=True)
    polish_notes: Mapped[str] = mapped_column(Text, nullable=True)
    polish_confirm_status: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    final_content: Mapped[str] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_rollbackable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    chapter: Mapped["Chapter"] = relationship(back_populates="modify_records")


class ValidationReport(Base):
    __tablename__ = "validation_reports"

    report_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    check_type: Mapped[str] = mapped_column(String(50), nullable=False)
    result: Mapped[str] = mapped_column(String(10), nullable=False)
    problem_desc: Mapped[str] = mapped_column(Text, nullable=True)
    volume_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_degree_score: Mapped[str | None] = mapped_column(String(20), nullable=True)
    validation_category: Mapped[str] = mapped_column(String(30), nullable=False, default="full_book")
    validated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped["Project"] = relationship(back_populates="validation_reports")


class AiCallLog(Base):
    __tablename__ = "ai_call_logs"

    log_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scene: Mapped[str] = mapped_column(String(100), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=True)
    response: Mapped[str] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    failover_from: Mapped[str | None] = mapped_column(String(36), nullable=True)
    called_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AiSource(Base):
    __tablename__ = "ai_sources"

    source_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    api_endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tags: Mapped[str] = mapped_column(String(500), nullable=True, default="")
    health_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    circuit_broken_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (UniqueConstraint("name", name="uq_ai_source_name"),)


class RoutingPolicy(Base):
    __tablename__ = "routing_policies"

    policy_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    strategy: Mapped[str] = mapped_column(String(20), nullable=False, default="failover")
    manual_source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    health_check_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    circuit_break_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    circuit_break_cool_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    failover_within_retry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class BackupPolicy(Base):
    __tablename__ = "backup_policies"

    policy_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    schedule_cron: Mapped[str] = mapped_column(String(100), nullable=False, default="0 0 * * *")
    target_dir: Mapped[str] = mapped_column(String(500), nullable=False)
    retain_count: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    trigger_on_exit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trigger_before_risky_op: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class BackupRecord(Base):
    __tablename__ = "backup_records"

    backup_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    project_ids: Mapped[str] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    template_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    scene: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("module", "scene", "version", name="uq_template_version"),
    )


class Outline(Base):
    __tablename__ = "outlines"

    outline_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), unique=True, nullable=False)
    gen_status: Mapped[str] = mapped_column(String(20), nullable=False, default="未生成")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="AI生成")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="outline")
    volumes: Mapped[list["VolumeOutline"]] = relationship("VolumeOutline", back_populates="outline", cascade="all, delete-orphan", order_by="VolumeOutline.volume_no")

    __table_args__ = (Index("ix_outline_project", "project_id"),)


class VolumeOutline(Base):
    __tablename__ = "volume_outlines"

    volume_outline_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    outline_id: Mapped[str] = mapped_column(String(36), ForeignKey("outlines.outline_id", ondelete="CASCADE"), nullable=False)
    volume_no: Mapped[int] = mapped_column(Integer, nullable=False)
    volume_name: Mapped[str] = mapped_column(String(50), nullable=False)
    chapter_count: Mapped[int] = mapped_column(Integer, nullable=False)

    outline: Mapped["Outline"] = relationship("Outline", back_populates="volumes")
    chapters: Mapped[list["ChapterOutline"]] = relationship("ChapterOutline", back_populates="volume_outline", cascade="all, delete-orphan", order_by="ChapterOutline.chapter_no")

    __table_args__ = (
        UniqueConstraint("outline_id", "volume_no", name="uq_volume_outline_no"),
        Index("ix_volume_outline", "outline_id", "volume_no"),
    )


class ChapterOutline(Base):
    __tablename__ = "chapter_outlines"

    chapter_outline_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    volume_outline_id: Mapped[str] = mapped_column(String(36), ForeignKey("volume_outlines.volume_outline_id", ondelete="CASCADE"), nullable=False)
    volume_no: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_no: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_name: Mapped[str] = mapped_column(String(50), nullable=False)
    synopsis_points: Mapped[str] = mapped_column(Text, nullable=False)
    characters_appearing: Mapped[str | None] = mapped_column(Text, nullable=True)
    gen_source: Mapped[str] = mapped_column(String(20), nullable=False, default="AI生成")
    story_unit_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)

    volume_outline: Mapped["VolumeOutline"] = relationship("VolumeOutline", back_populates="chapters")

    __table_args__ = (
        UniqueConstraint("volume_outline_id", "chapter_no", name="uq_chapter_outline_no"),
        Index("ix_chapter_outline", "volume_outline_id", "chapter_no"),
    )


class WritingChatHistory(Base):
    __tablename__ = "writing_chat_histories"

    chat_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapters.chapter_id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="selected")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    chapter: Mapped["Chapter"] = relationship(back_populates="chat_histories")


class ChapterVersion(Base):
    __tablename__ = "chapter_versions"

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapters.chapter_id", ondelete="CASCADE"), nullable=False, index=True)
    version_type: Mapped[str] = mapped_column(String(10), nullable=False, default="auto")
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    chapter: Mapped["Chapter"] = relationship(back_populates="versions")


class ChapterAnnotation(Base):
    __tablename__ = "chapter_annotations"

    annotation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapters.chapter_id", ondelete="CASCADE"), nullable=False, index=True)
    paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    annotation_type: Mapped[str] = mapped_column(String(20), nullable=False, default="note")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    chapter: Mapped["Chapter"] = relationship(back_populates="annotations")


class ChapterScene(Base):
    __tablename__ = "chapter_scenes"

    scene_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapters.chapter_id", ondelete="CASCADE"), nullable=False, index=True)
    scene_order: Mapped[int] = mapped_column(Integer, nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    characters: Mapped[str] = mapped_column(Text, nullable=True)
    key_event: Mapped[str] = mapped_column(Text, nullable=False)
    mood: Mapped[str] = mapped_column(String(50), nullable=True)
    est_words: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    chapter: Mapped["Chapter"] = relationship(back_populates="scenes")


class ChapterSummary(Base):
    __tablename__ = "chapter_summaries"

    chapter_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapters.chapter_id", ondelete="CASCADE"), primary_key=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    chapter: Mapped["Chapter"] = relationship(back_populates="summary")


class TimelineNode(Base):
    __tablename__ = "timeline_nodes"

    node_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    event_name: Mapped[str] = mapped_column(String(200), nullable=False)
    time_point: Mapped[str] = mapped_column(String(100), nullable=True)
    characters: Mapped[str] = mapped_column(Text, nullable=True)
    chapter_ids: Mapped[str] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    node_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class CharacterRelationship(Base):
    __tablename__ = "character_relationships"

    relationship_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    source_character_id: Mapped[str] = mapped_column(String(36), ForeignKey("characters.character_id", ondelete="CASCADE"), nullable=False)
    target_character_id: Mapped[str] = mapped_column(String(36), ForeignKey("characters.character_id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (
        Index("ix_char_rel_project", "project_id", "source_character_id"),
    )


class EmotionCurvePoint(Base):
    __tablename__ = "emotion_curve_points"

    point_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapters.chapter_id", ondelete="CASCADE"), nullable=False)
    chapter_no: Mapped[int] = mapped_column(Integer, nullable=False)
    tension: Mapped[float] = mapped_column(Float, nullable=False)
    emotion_fluctuation: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (
        UniqueConstraint("project_id", "chapter_id", name="uq_emotion_point"),
    )


class SensitiveWord(Base):
    __tablename__ = "sensitive_words"

    word_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=True, index=True)
    word: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class NameFavorite(Base):
    __tablename__ = "name_favorites"

    favorite_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    name_type: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(String(50), nullable=False)
    meaning: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (
        UniqueConstraint("project_id", "name_type", "value", name="uq_name_favorite"),
    )


class LayoutTemplate(Base):
    __tablename__ = "layout_templates"

    template_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    font: Mapped[str] = mapped_column(String(50), nullable=True)
    font_size: Mapped[int] = mapped_column(Integer, nullable=True)
    line_spacing: Mapped[float] = mapped_column(Float, nullable=True)
    title_style: Mapped[str] = mapped_column(String(30), nullable=True)
    first_indent: Mapped[bool] = mapped_column(Boolean, nullable=True, default=True)
    header: Mapped[str | None] = mapped_column(String(200), nullable=True)
    footer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class ShortcutConfig(Base):
    __tablename__ = "shortcut_configs"

    shortcut_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_name: Mapped[str] = mapped_column(String(50), nullable=False)
    action_label: Mapped[str] = mapped_column(String(100), nullable=False)
    key_sequence: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("action_name", name="uq_shortcut_action"),
    )


class GarbledConfigModel(Base):
    """乱码检测修复配置 ORM 模型 - 支持全局/项目级两层配置."""

    __tablename__ = "garbled_configs"

    config_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    max_blank_lines: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_punct_repeat: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_consecutive_spaces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enable_fullwidth_indent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    enable_punct_repeat_fix: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    enable_whitespace_cleanup: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    enable_irreversible_clear: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("scope", "project_id", name="uq_garbled_config_scope"),
    )


class StoryUnit(Base):
    """故事单元 - 雪花式5级分层大纲的大篇/中篇/小篇三层（自引用树）."""

    __tablename__ = "story_units"

    story_unit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    parent_unit_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("story_units.story_unit_id", ondelete="CASCADE"), nullable=True, index=True)
    level_type: Mapped[str] = mapped_column(String(10), nullable=False)
    unit_no: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_name: Mapped[str] = mapped_column(String(50), nullable=False)
    synopsis: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_count: Mapped[int] = mapped_column(Integer, nullable=False)
    gen_status: Mapped[str] = mapped_column(String(20), nullable=False, default="未生成")
    narrative_duty: Mapped[str] = mapped_column(Text, nullable=False)
    cascade_dirty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_story_unit_project", "project_id"),
        Index("ix_story_unit_parent", "parent_unit_id"),
        UniqueConstraint("project_id", "parent_unit_id", "unit_no", name="uq_story_unit_no"),
    )


class AntiAiRewriteRecord(Base):
    """降AI率改写记录."""

    __tablename__ = "anti_ai_rewrite_records"

    rewrite_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapters.chapter_id", ondelete="CASCADE"), nullable=False, index=True)
    original_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapter_versions.version_id"), nullable=False)
    rewritten_content: Mapped[str] = mapped_column(Text, nullable=False)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    adopt_status: Mapped[str] = mapped_column(String(10), nullable=False, default="待采纳")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class BatchOperationRecord(Base):
    """批量操作记录."""

    __tablename__ = "batch_operation_records"

    batch_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    operation_type: Mapped[str] = mapped_column(String(10), nullable=False)
    target_scope: Mapped[str] = mapped_column(Text, nullable=False)
    batch_no: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    process_status: Mapped[str] = mapped_column(String(10), nullable=False, default="处理中")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class BookTeardown(Base):
    """拆书结果."""

    __tablename__ = "book_teardowns"

    teardown_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)
    multi_level_outline: Mapped[str] = mapped_column(Text, nullable=False)
    characters_extract: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_places: Mapped[str | None] = mapped_column(Text, nullable=True)
    worldview_setting: Mapped[str | None] = mapped_column(Text, nullable=True)
    special_items: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_points: Mapped[str | None] = mapped_column(Text, nullable=True)
    teardown_status: Mapped[str] = mapped_column(String(10), nullable=False, default="处理中")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class IterationRecord(Base):
    """迭代生成记录."""

    __tablename__ = "iteration_records"

    iteration_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    iteration_unit: Mapped[str] = mapped_column(String(10), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    total_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    input_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapter_versions.version_id"), nullable=False)
    output_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapter_versions.version_id"), nullable=False)
    iteration_status: Mapped[str] = mapped_column(String(10), nullable=False, default="进行中")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Script(Base):
    """剧本分集."""

    __tablename__ = "scripts"

    script_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False, index=True)
    episode_no: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_description: Mapped[str] = mapped_column(Text, nullable=False)
    character_dialogue: Mapped[str] = mapped_column(Text, nullable=False)
    outline_unit_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("story_units.story_unit_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ProofreadDraft(Base):
    """AB稿/ABC稿纠错稿件."""

    __tablename__ = "proofread_drafts"

    draft_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapters.chapter_id", ondelete="CASCADE"), nullable=False, index=True)
    draft_stage: Mapped[str] = mapped_column(String(10), nullable=False)
    ai_source_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_sources.source_id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    version_id: Mapped[str] = mapped_column(String(36), ForeignKey("chapter_versions.version_id"), nullable=False)
    adopt_status: Mapped[str] = mapped_column(String(10), nullable=False, default="待采纳")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


ALL_MODELS = [
    Project, Synopsis, Worldview, Character, CoolPoint, Hook, Chapter, Item,
    StyleLibrary, StyleFeature, ModifyRecord, ValidationReport, AiCallLog,
    AiSource, RoutingPolicy, BackupPolicy, BackupRecord, PromptTemplate,
    Outline, VolumeOutline, ChapterOutline,
    WritingChatHistory, ChapterVersion, ChapterAnnotation, ChapterScene,
    ChapterSummary, TimelineNode, CharacterRelationship, EmotionCurvePoint,
    SensitiveWord, NameFavorite, LayoutTemplate, ShortcutConfig,
    GarbledConfigModel,
    StoryUnit, AntiAiRewriteRecord, BatchOperationRecord, BookTeardown,
    IterationRecord, Script, ProofreadDraft,
]