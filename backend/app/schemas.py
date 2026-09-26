from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.enums import DistributionScope, Layer, ProductionTier, RightsholderKind, Role, Stage


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
    # Who to approach, decided by the resolver. Full ranking at GET /api/tasks/{id}/contacts.
    recommended_contact: dict | None = None
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


# ---------------------------------------------------------------- contact resolution

class ContactOptionOut(BaseModel):
    rightsholder_id: str
    name: str
    kind: RightsholderKind
    identity: float = Field(description="Confidence this party can actually grant the right")
    reliability: float = Field(description="How likely approaching them is to work")
    cost_low: Decimal | None
    cost_high: Decimal | None
    overall: float
    contact: ContactOut
    reliability_breakdown: dict
    evidence: list[dict] = []
    reasons: list[str] = []
    blockers: list[str] = Field(default=[], description="Why this option cannot be recommended")


class ResearchLeadOut(BaseModel):
    source: str
    label: str
    url: str
    why: str
    automatable: bool = Field(description="True when we hold credentials to query it directly")


class ContactResolutionOut(BaseModel):
    task_id: str
    layer: Layer
    recommended: dict | None
    options: list[ContactOptionOut]
    research_leads: list[ResearchLeadOut]


# ---------------------------------------------------------------- outreach packets (M4)

class TemplateOut(BaseModel):
    name: str
    description: str


class PdfStatusOut(BaseModel):
    """Whether the native PDF stack is present. The HTML letter works regardless."""

    available: bool
    version: str | None = None
    error: str | None = None
    install_hint: str | None = None


class PacketGroupOut(BaseModel):
    """Outreach-ready tasks bundled by the licensing desk that would receive the letter."""

    rightsholder_id: str
    name: str
    kind: RightsholderKind
    licensing_email: str | None
    is_placeholder: bool
    suggested_template: str
    task_ids: list[str]
    layers: list[Layer]
    asset_titles: list[str]
    existing_packet_ids: list[str] = []


class PacketItemOut(BaseModel):
    task_id: str
    asset_id: str
    asset_title: str | None
    layer: Layer
    stage: Stage
    estimate_low: Decimal | None
    estimate_high: Decimal | None


class ExcerptOut(ORM):
    id: str
    packet_id: str
    scene_id: str | None
    label: str
    text: str
    created_at: datetime


class ExcerptCreate(BaseModel):
    """Selecting an excerpt is an explicit act: a scene, and optionally a range within it.

    Omitting the offsets shares the whole scene. The text is frozen at selection time.
    """

    scene_id: str
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)
    label: str | None = Field(default=None, max_length=300)


class ContextViewOut(ORM):
    id: str
    packet_id: str
    recipient_name: str
    recipient_email: str | None
    token_hint: str
    status: str = Field(description="active | expired | revoked")
    expires_at: datetime
    revoked_at: datetime | None
    created_by: str
    created_at: datetime
    access_count: int
    last_accessed_at: datetime | None


class ContextViewCreated(ContextViewOut):
    """Carries the plaintext token. Returned once, at creation, and never retrievable again."""

    url: str
    token: str


class ContextViewCreate(BaseModel):
    recipient_name: str = Field(min_length=1, max_length=300)
    recipient_email: str | None = None
    ttl_days: int | None = Field(default=None, ge=1, le=60,
                                 description="Defaults to the configured 14-day expiry")


class AccessOut(ORM):
    id: int
    view_id: str
    at: datetime
    outcome: str
    path: str
    client_ip: str | None
    user_agent: str | None
    referer: str | None


class PacketOut(ORM):
    id: str
    project_id: str
    rightsholder: RightsholderBrief
    contact: ContactOut
    template: str
    status: str
    recipient_name: str | None
    recipient_email: str | None
    sender_name: str | None
    sender_email: str | None
    sender_title: str | None
    subject: str | None
    intro_note: str | None
    finalized_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[PacketItemOut] = []
    excerpts: list[ExcerptOut] = []
    context_views: list[ContextViewOut] = []


class PacketCreate(BaseModel):
    task_ids: list[str] = Field(min_length=1, max_length=50)
    template: str | None = Field(default=None, description="Defaults to the rightsholder's preference")
    recipient_name: str | None = None
    recipient_email: str | None = None
    subject: str | None = None
    intro_note: str | None = None


class PacketUpdate(BaseModel):
    """Only fields present in the body are applied."""

    template: str | None = None
    recipient_name: str | None = None
    recipient_email: str | None = None
    sender_name: str | None = None
    sender_email: str | None = None
    sender_title: str | None = None
    subject: str | None = None
    intro_note: str | None = None
    task_ids: list[str] | None = Field(default=None, description="Replaces the packet's task set")
    reason: str | None = Field(default=None, description="Recorded in the audit log")


class PacketFinalize(BaseModel):
    """Freeze the letter and move every task in the packet to outreach_sent."""

    transition_tasks: bool = Field(default=True,
                                   description="Move eligible tasks to 'outreach sent'")
    reason: str | None = None


# ---------------------------------------------------------------- mail loop (M5)

class SendRequest(BaseModel):
    """Sending is refused to unverified or reserved-domain contacts unless overridden."""

    allow_unverified: bool = Field(
        default=False,
        description="Send even though the directory marks this contact as unverified placeholder data")
    reason: str | None = None


class OutboundOut(ORM):
    id: str
    thread_id: str
    to_email: str
    from_email: str
    reply_to: str
    subject: str
    provider: str
    provider_message_id: str | None
    status: str
    error: str | None
    note: str | None
    sent_at: datetime | None
    sent_by: str
    created_at: datetime


class ProposedChangeOut(ORM):
    id: str
    intent_id: str
    task_id: str
    kind: str
    from_stage: Stage
    to_stage: Stage | None
    quoted_amount: Decimal | None
    currency: str | None
    quote_text: str | None
    confidence: float
    note: str | None
    status: str
    blocked_reason: str | None
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime
    # Filled by the presenter so the queue reads without a second round trip.
    asset_title: str | None = None
    layer: Layer | None = None


class ReplyIntentOut(ORM):
    id: str
    inbound_id: str
    model: str
    kind: str
    confidence: float
    summary: str
    reasoning: str | None
    created_at: datetime
    changes: list[ProposedChangeOut] = []


class InboundOut(ORM):
    id: str
    thread_id: str | None
    provider: str
    from_email: str
    from_name: str | None
    subject: str | None
    text_body: str
    status: str
    error: str | None
    received_at: datetime
    intent: ReplyIntentOut | None = None
    packet_id: str | None = None
    rightsholder_name: str | None = None


class ThreadOut(ORM):
    id: str
    packet_id: str
    reply_to: str
    closed_at: datetime | None
    created_at: datetime
    outbound: list[OutboundOut] = []
    inbound: list[InboundOut] = []


class DecisionRequest(BaseModel):
    reason: str | None = Field(default=None, description="Recorded in the audit log")


class ApplyRequest(DecisionRequest):
    """Confirming a proposal. The amount may be corrected at the moment of confirmation."""

    quoted_amount: Decimal | None = Field(
        default=None, ge=0, description="Overrides the parsed figure before it is applied")


class InboundAck(BaseModel):
    """What the webhook returns. Deliberately terse — the provider is not a user."""

    status: str
    inbound_id: str | None = None
    proposals: int = 0


class LedgerLineOut(BaseModel):
    task_id: str
    asset_id: str
    asset_title: str | None
    layer: Layer
    stage: Stage
    rightsholder_name: str | None
    estimate_low: Decimal | None
    estimate_high: Decimal | None
    quoted: Decimal | None
    agreed: Decimal | None
    exposure: Decimal
    basis: str = Field(description="agreed | quoted | estimate | none")
    variance: Decimal | None = Field(description="Firm figure minus the top of the estimate range")
    closed: bool


class LedgerTotals(BaseModel):
    live_tasks: int
    closed_tasks: int
    estimate_low: Decimal
    estimate_high: Decimal
    quoted_total: Decimal
    agreed_total: Decimal
    exposure: Decimal
    recommended_contingency: Decimal
    committed: Decimal
    awaiting_reply: int
    priced_tasks: int
    over_estimate_tasks: int
    variance_total: Decimal
    worst_variance: Decimal


class LedgerOut(BaseModel):
    lines: list[LedgerLineOut]
    totals: LedgerTotals


# ---------------------------------------------------------------- auth and tenancy (M6)

class RegisterRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=300)
    password: str = Field(min_length=12, max_length=200)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    org_id: str
    email: str
    name: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class OrgOut(ORM):
    id: str
    name: str
    slug: str
    created_at: datetime


class TokenOut(BaseModel):
    """The bearer token exists only here. It is stored as a digest and never returned again."""

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


class MeOut(BaseModel):
    user: UserOut
    organization: OrgOut


class SessionOut(BaseModel):
    id: str
    token_hint: str
    status: str = Field(description="active | expired | revoked")
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_seen_at: datetime | None
    client_ip: str | None
    user_agent: str | None


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=300)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=200)
    role: Role = Role.member


class UserUpdate(BaseModel):
    name: str | None = None
    role: Role | None = None
    is_active: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=200)


class HealthOut(BaseModel):
    """Readiness, component by component, so a failing dependency is named rather than guessed."""

    status: str = Field(description="ok | degraded")
    version: str
    components: dict[str, dict]
