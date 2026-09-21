from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.enums import DistributionScope, Layer, ProductionTier, RightsholderKind, Stage


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- disclaimer

class DisclaimerOut(BaseModel):
    version: str
    text: str
    accepted: bool
    accepted_at: datetime | None = None


# ---------------------------------------------------------------- projects

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    distribution_scope: DistributionScope
    production_tier: ProductionTier


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    distribution_scope: DistributionScope | None = None
    production_tier: ProductionTier | None = None


class ProjectOut(ORM):
    id: str
    name: str
    distribution_scope: DistributionScope
    production_tier: ProductionTier
    created_at: datetime


# ---------------------------------------------------------------- rightsholders

class ContactOut(BaseModel):
    via_rightsholder_id: str | None
    via_name: str | None
    licensing_email: str | None
    address: str | None
    preferred_templates: list[str]
    is_placeholder: bool


class RightsholderBrief(ORM):
    id: str
    name: str
    kind: RightsholderKind
    is_placeholder: bool


class RightsholderOut(RightsholderBrief):
    parent_id: str | None
    licensing_email: str | None
    address: str | None
    website: str | None
    preferred_templates: list[str]
    aliases: list[str]
    contact: ContactOut
    children: list[RightsholderBrief] = []


class RightsholderCreate(BaseModel):
    id: str = Field(pattern=r"^ent_[a-z0-9_]{2,76}$")
    name: str = Field(min_length=1, max_length=300)
    kind: RightsholderKind
    parent_id: str | None = None
    licensing_email: str | None = None
    address: str | None = None
    website: str | None = None
    preferred_templates: list[str] = []
    aliases: list[str] = []


class RightsholderUpdate(BaseModel):
    name: str | None = None
    kind: RightsholderKind | None = None
    parent_id: str | None = None
    licensing_email: str | None = None
    address: str | None = None
    website: str | None = None
    preferred_templates: list[str] | None = None
    is_placeholder: bool | None = None


# ---------------------------------------------------------------- tasks

class CandidateOut(BaseModel):
    rightsholder_id: str
    name: str
    score: float
    matched_alias: str
    matched_query: str


class TaskOut(ORM):
    id: str
    asset_id: str
    layer: Layer
    stage: Stage
    rightsholder: RightsholderBrief | None
    contact: ContactOut | None = None
    mapping_method: str | None
    mapping_confidence: float | None
    mapping_candidates: list[CandidateOut]
    estimate_low: Decimal | None
    estimate_high: Decimal | None
    estimate_breakdown: dict | None
    quoted_amount: Decimal | None
    agreed_amount: Decimal | None
    notes: str | None
    allowed_transitions: list[Stage] = []
    updated_at: datetime


class TaskUpdate(BaseModel):
    """Only fields present in the request body are applied; send rightsholder_id=null to unassign."""

    rightsholder_id: str | None = None
    quoted_amount: Decimal | None = Field(default=None, ge=0)
    agreed_amount: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None
    reason: str | None = Field(default=None, description="Recorded in the audit log")


class TransitionRequest(BaseModel):
    to: Stage
    reason: str | None = None


# ---------------------------------------------------------------- assets

class IngestItem(BaseModel):
    url: HttpUrl
    notes: str | None = Field(default=None, description="How the asset is used, e.g. 'jukebox in diner scene'")
    usage_seconds: int | None = Field(default=None, ge=1)


class IngestRequest(BaseModel):
    items: list[IngestItem] = Field(min_length=1, max_length=50)
    defer: bool = Field(
        default=False,
        description="Queue the fetch as a background job and return immediately instead of waiting.",
    )


class AssetOut(ORM):
    id: str
    project_id: str
    source_type: str
    raw_source: str
    platform: str
    platform_asset_id: str | None
    title: str | None
    owner_name: str | None
    description: str | None
    published_at: str | None
    thumbnail_url: str | None
    duration_seconds: int | None
    inferred_keywords: list[str]
    user_notes: str | None
    usage_seconds: int | None
    ingest_status: str
    ingest_error: str | None
    created_at: datetime
    tasks: list[TaskOut]


class AssetUpdate(BaseModel):
    title: str | None = None
    owner_name: str | None = None
    description: str | None = None
    published_at: str | None = None
    inferred_keywords: list[str] | None = None
    user_notes: str | None = None
    usage_seconds: int | None = Field(default=None, ge=1)
    remap: bool = Field(default=True, description="Re-run rights matching on auto-mapped layers after the edit")


class IngestResultOut(BaseModel):
    url: str
    asset_id: str
    status: str
    duplicate: bool
    error: str | None


class AddLayerRequest(BaseModel):
    layer: Layer


# ---------------------------------------------------------------- board / budget / audit

class BoardCard(BaseModel):
    task: TaskOut
    asset_id: str
    asset_title: str | None
    asset_thumbnail_url: str | None
    platform: str


class BudgetTotals(BaseModel):
    active_tasks: int
    unestimated_tasks: int
    estimate_low: Decimal
    estimate_high: Decimal
    recommended_contingency: Decimal
    quoted_total: Decimal
    agreed_total: Decimal


class AuditOut(ORM):
    id: int
    table_name: str
    row_id: str
    action: str
    changes: dict
    actor_type: str
    actor_id: str
    reason: str | None
    at: datetime


# ---------------------------------------------------------------- scripts (M3)

class SceneOut(ORM):
    id: str
    index: int
    heading: str
    page_number: int | None
    text: str


class MentionOut(ORM):
    id: str
    scene_id: str
    project_id: str
    title: str
    owner_name: str | None
    kind: str
    quote: str
    suggested_layers: list[Layer]
    confidence: float
    reasoning: str | None
    status: str
    asset_id: str | None
    created_at: datetime
    scene_heading: str | None = None
    scene_index: int | None = None
    page_number: int | None = None


class ScriptOut(ORM):
    id: str
    project_id: str
    filename: str
    media_type: str
    byte_size: int
    page_count: int | None
    scene_count: int
    status: str
    error: str | None
    extraction_model: str | None
    created_at: datetime
    mention_count: int = 0
    job_id: str | None = None


class ConfirmMentionRequest(BaseModel):
    """Turn a proposed mention into a real asset with its layer tasks."""

    usage_seconds: int | None = Field(default=None, ge=1)
    layers: list[Layer] | None = Field(default=None, description="Overrides the suggested layers")
    title: str | None = None
    owner_name: str | None = None


class JobOut(ORM):
    id: str
    kind: str
    status: str
    project_id: str | None
    subject_id: str | None
    result: dict | None
    error: str | None
    enqueued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
