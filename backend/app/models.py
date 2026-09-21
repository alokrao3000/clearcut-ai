import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Enum-valued columns are stored as plain strings: portable across SQLite/Postgres,
# readable in audit diffs, and extendable without a migration. Validation happens in the API layer.
ENUM = String(40)


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    distribution_scope: Mapped[str] = mapped_column(ENUM)
    production_tier: Mapped[str] = mapped_column(ENUM)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assets: Mapped[list["Asset"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Asset(Base):
    """A composite parent: one sourced item that may carry several separately cleared rights."""

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(ENUM)
    raw_source: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(ENUM)
    platform_asset_id: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(Text)
    owner_name: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[str | None] = mapped_column(String(40))
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    inferred_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    user_notes: Mapped[str | None] = mapped_column(Text)
    usage_seconds: Mapped[int | None] = mapped_column(Integer)  # planned on-screen duration
    ingest_status: Mapped[str] = mapped_column(ENUM)
    ingest_error: Mapped[str | None] = mapped_column(Text)
    # Frozen snapshot of what ingestion produced. Never updated; edits go to the columns above.
    ingest_payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="assets")
    tasks: Mapped[list["ClearanceTask"]] = relationship(back_populates="asset", cascade="all, delete-orphan",
                                                        order_by="ClearanceTask.layer")


class ClearanceTask(Base):
    """One right on one asset, tracked independently through the Kanban."""

    __tablename__ = "clearance_tasks"
    __table_args__ = (UniqueConstraint("asset_id", "layer"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    layer: Mapped[str] = mapped_column(ENUM)
    stage: Mapped[str] = mapped_column(ENUM, default="sourced")

    rightsholder_id: Mapped[str | None] = mapped_column(ForeignKey("rightsholders.id"), index=True)
    mapping_method: Mapped[str | None] = mapped_column(String(20))  # auto | manual
    mapping_confidence: Mapped[float | None] = mapped_column(Float)
    mapping_candidates: Mapped[list[dict]] = mapped_column(JSON, default=list)

    estimate_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    estimate_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    estimate_breakdown: Mapped[dict | None] = mapped_column(JSON)
    quoted_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    agreed_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    asset: Mapped[Asset] = relationship(back_populates="tasks")
    rightsholder: Mapped["Rightsholder | None"] = relationship()


class ScriptDocument(Base):
    """An uploaded screenplay. The file itself is never stored — only the parsed text."""

    __tablename__ = "script_documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    media_type: Mapped[str] = mapped_column(String(40))  # pdf | docx | fdx
    byte_size: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    scene_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(ENUM, default="parsing")  # parsing|extracting|complete|failed
    error: Mapped[str | None] = mapped_column(Text)
    extraction_model: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship()
    scenes: Mapped[list["Scene"]] = relationship(back_populates="script", cascade="all, delete-orphan",
                                                 order_by="Scene.index")


class Scene(Base):
    """One scene-chunk of a script, kept so every extracted asset can point back at its source."""

    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("script_id", "index"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    script_id: Mapped[str] = mapped_column(ForeignKey("script_documents.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    script: Mapped[ScriptDocument] = relationship(back_populates="scenes")
    mentions: Mapped[list["AssetMention"]] = relationship(back_populates="scene", cascade="all, delete-orphan")


class AssetMention(Base):
    """A thing the extractor found in a scene: a song on a jukebox, a poster, a TV clip.

    Stays a proposal until a user confirms it; confirmation creates the Asset and its
    layer tasks. `quote` is the script line it came from, so a producer can check it.
    """

    __tablename__ = "asset_mentions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    owner_name: Mapped[str | None] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(40))  # music|footage|still|artwork|trademark|other
    quote: Mapped[str] = mapped_column(Text)
    suggested_layers: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reasoning: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(ENUM, default="proposed")  # proposed|confirmed|dismissed
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scene: Mapped[Scene] = relationship(back_populates="mentions")


class Job(Base):
    """Ledger of queued work, so the API can report progress without asking Redis."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(ENUM, default="queued")  # queued|running|complete|failed
    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(32), index=True)  # script, asset, ...
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Rightsholder(Base):
    __tablename__ = "rightsholders"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)  # stable slug, e.g. ent_warner_bros_animation
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(ENUM)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("rightsholders.id"))
    licensing_email: Mapped[str | None] = mapped_column(String(300))
    address: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(300))
    preferred_templates: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False)  # unverified seed data

    parent: Mapped["Rightsholder | None"] = relationship(remote_side="Rightsholder.id", back_populates="children")
    children: Mapped[list["Rightsholder"]] = relationship(back_populates="parent")
    aliases: Mapped[list["RightsholderAlias"]] = relationship(back_populates="rightsholder",
                                                              cascade="all, delete-orphan")


class RightsholderAlias(Base):
    __tablename__ = "rightsholder_aliases"
    __table_args__ = (UniqueConstraint("rightsholder_id", "alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rightsholder_id: Mapped[str] = mapped_column(ForeignKey("rightsholders.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(300))
    # Restricts the alias to specific layers, e.g. an artist name routes master_recording to a label.
    layers: Mapped[list[str] | None] = mapped_column(JSON)

    rightsholder: Mapped[Rightsholder] = relationship(back_populates="aliases")


class RateCard(Base):
    """Baseline fee range at the reference point: Studio Feature tier, Worldwide Streaming scope."""

    __tablename__ = "rate_cards"
    __table_args__ = (UniqueConstraint("rightsholder_id", "layer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rightsholder_id: Mapped[str | None] = mapped_column(ForeignKey("rightsholders.id"))  # NULL = industry default
    layer: Mapped[str] = mapped_column(ENUM)
    unit: Mapped[str] = mapped_column(ENUM)
    base_low: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    base_high: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    minimum_units: Mapped[float] = mapped_column(Float, default=1.0)
    source_note: Mapped[str | None] = mapped_column(Text)
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    """Append-only field-level history of every audited row, with who or what made the change."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(80), index=True)
    row_id: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(10))  # insert | update | delete
    changes: Mapped[dict] = mapped_column(JSON)  # {field: [old, new]}
    actor_type: Mapped[str] = mapped_column(ENUM)
    actor_id: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class DisclaimerAcceptance(Base):
    __tablename__ = "disclaimer_acceptances"
    __table_args__ = (UniqueConstraint("user_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[str] = mapped_column(String(40))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    client_ip: Mapped[str | None] = mapped_column(String(64))
