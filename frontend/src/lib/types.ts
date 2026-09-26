// Mirrors backend/app/schemas.py and backend/app/enums.py.
// Money is Decimal on the server and arrives as a JSON string.

export const STAGES = [
  "sourced",
  "rights_mapped",
  "budget_approved",
  "outreach_sent",
  "quote_received",
  "deal_memo_signed",
  "denied",
  "dropped",
] as const;
export type Stage = (typeof STAGES)[number];

export const LAYERS = [
  "footage",
  "still_image",
  "master_recording",
  "composition",
  "performance",
  "trademark",
] as const;
export type Layer = (typeof LAYERS)[number];

export const DISTRIBUTION_SCOPES = [
  "festival",
  "worldwide_streaming",
  "all_media_perpetual",
] as const;
export type DistributionScope = (typeof DISTRIBUTION_SCOPES)[number];

export const PRODUCTION_TIERS = ["ultra_low", "sag_moderate_low", "studio_feature"] as const;
export type ProductionTier = (typeof PRODUCTION_TIERS)[number];

export const RIGHTSHOLDER_KINDS = [
  "studio",
  "broadcaster",
  "label",
  "publisher",
  "stock_agency",
  "archive",
  "individual",
  "brand",
] as const;
export type RightsholderKind = (typeof RIGHTSHOLDER_KINDS)[number];

export type Decimalish = string;

export interface Disclaimer {
  version: string;
  text: string;
  accepted: boolean;
  accepted_at: string | null;
}

export interface Project {
  id: string;
  name: string;
  distribution_scope: DistributionScope;
  production_tier: ProductionTier;
  created_at: string;
}

export interface Contact {
  via_rightsholder_id: string | null;
  via_name: string | null;
  licensing_email: string | null;
  address: string | null;
  preferred_templates: string[];
  is_placeholder: boolean;
}

export interface RightsholderBrief {
  id: string;
  name: string;
  kind: RightsholderKind;
  is_placeholder: boolean;
}

export interface Rightsholder extends RightsholderBrief {
  parent_id: string | null;
  licensing_email: string | null;
  address: string | null;
  website: string | null;
  preferred_templates: string[];
  aliases: string[];
  contact: Contact;
  children: RightsholderBrief[];
}

export interface Candidate {
  rightsholder_id: string;
  name: string;
  score: number;
  matched_alias: string;
  matched_query: string;
}

export interface EstimateBreakdown {
  formula?: string;
  rate_card_id?: number;
  rate_basis?: string;
  unit?: string;
  base_low?: string;
  base_high?: string;
  units?: number;
  distribution_scope?: string;
  distribution_multiplier?: string;
  production_tier?: string;
  tier_factor?: string;
  assumptions?: string[];
  summary?: string;
}

export interface Task {
  id: string;
  asset_id: string;
  layer: Layer;
  stage: Stage;
  rightsholder: RightsholderBrief | null;
  contact: Contact | null;
  mapping_method: string | null;
  mapping_confidence: number | null;
  mapping_candidates: Candidate[];
  estimate_low: Decimalish | null;
  estimate_high: Decimalish | null;
  estimate_breakdown: EstimateBreakdown | null;
  quoted_amount: Decimalish | null;
  agreed_amount: Decimalish | null;
  notes: string | null;
  allowed_transitions: Stage[];
  recommended_contact: RecommendedContact | null;
  updated_at: string;
}

export interface ReliabilityComponent {
  weight: number;
  score: number;
  note: string;
}

export interface ReliabilityBreakdown {
  components?: Record<string, ReliabilityComponent>;
  formula?: string;
  cost_advantage?: number;
}

export interface OwnershipEvidence {
  name: string;
  claim_type: string;
  layers: Layer[];
  strength: number;
  source_field: string;
  excerpt: string;
}

export interface ContactOption {
  rightsholder_id: string;
  name: string;
  kind: RightsholderKind;
  identity: number;
  reliability: number;
  cost_low: Decimalish | null;
  cost_high: Decimalish | null;
  overall: number;
  contact: Contact;
  reliability_breakdown: ReliabilityBreakdown;
  evidence: OwnershipEvidence[];
  reasons: string[];
  blockers: string[];
}

export interface RecommendedContact extends ContactOption {
  why?: string[];
  cheaper_alternative?: {
    rightsholder_id: string;
    name: string;
    cost_low: Decimalish | null;
    cost_high: Decimalish | null;
    reliability: number;
  } | null;
}

export interface ResearchLead {
  source: string;
  label: string;
  url: string;
  why: string;
  /** True when we hold credentials to query the source directly rather than by hand. */
  automatable: boolean;
}

export interface ContactResolution {
  task_id: string;
  layer: Layer;
  recommended: RecommendedContact | null;
  options: ContactOption[];
  research_leads: ResearchLead[];
}

export interface Asset {
  id: string;
  project_id: string;
  source_type: string;
  raw_source: string;
  platform: string;
  platform_asset_id: string | null;
  title: string | null;
  owner_name: string | null;
  description: string | null;
  published_at: string | null;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  inferred_keywords: string[];
  user_notes: string | null;
  usage_seconds: number | null;
  ingest_status: "complete" | "partial" | "failed";
  ingest_error: string | null;
  created_at: string;
  tasks: Task[];
}

export interface IngestResult {
  url: string;
  asset_id: string;
  status: string;
  duplicate: boolean;
  error: string | null;
}

export interface BoardCard {
  task: Task;
  asset_id: string;
  asset_title: string | null;
  asset_thumbnail_url: string | null;
  platform: string;
}

export type Board = Record<Stage, BoardCard[]>;

export interface BudgetTotals {
  active_tasks: number;
  unestimated_tasks: number;
  estimate_low: Decimalish;
  estimate_high: Decimalish;
  recommended_contingency: Decimalish;
  quoted_total: Decimalish;
  agreed_total: Decimalish;
}

export interface AuditEntry {
  id: number;
  table_name: string;
  row_id: string;
  action: string;
  changes: Record<string, unknown>;
  actor_type: "user" | "system" | "scraper" | "llm";
  actor_id: string;
  reason: string | null;
  at: string;
}

// ------------------------------------------------------------ outreach (M4)

export interface OutreachTemplate {
  name: string;
  description: string;
}

/** Whether the host can render PDFs. The HTML letter works either way. */
export interface PdfStatus {
  available: boolean;
  version: string | null;
  error: string | null;
  install_hint: string | null;
}

/** Outreach-ready tasks bundled by the licensing desk that would receive the letter. */
export interface PacketGroup {
  rightsholder_id: string;
  name: string;
  kind: RightsholderKind;
  licensing_email: string | null;
  is_placeholder: boolean;
  suggested_template: string;
  task_ids: string[];
  layers: Layer[];
  asset_titles: string[];
  existing_packet_ids: string[];
}

export interface PacketItem {
  task_id: string;
  asset_id: string;
  asset_title: string | null;
  layer: Layer;
  stage: Stage;
  estimate_low: Decimalish | null;
  estimate_high: Decimalish | null;
}

export interface Excerpt {
  id: string;
  packet_id: string;
  scene_id: string | null;
  label: string;
  text: string;
  created_at: string;
}

export type ContextViewStatus = "active" | "expired" | "revoked";

export interface ContextView {
  id: string;
  packet_id: string;
  recipient_name: string;
  recipient_email: string | null;
  token_hint: string;
  status: ContextViewStatus;
  expires_at: string;
  revoked_at: string | null;
  created_by: string;
  created_at: string;
  access_count: number;
  last_accessed_at: string | null;
}

/** Only ever returned by the create call — the token is not retrievable afterwards. */
export interface ContextViewCreated extends ContextView {
  url: string;
  token: string;
}

export interface ContextViewAccess {
  id: number;
  view_id: string;
  at: string;
  outcome: "ok" | "expired" | "revoked";
  path: string;
  client_ip: string | null;
  user_agent: string | null;
  referer: string | null;
}

export interface Packet {
  id: string;
  project_id: string;
  rightsholder: RightsholderBrief;
  contact: Contact;
  template: string;
  status: "draft" | "finalized";
  recipient_name: string | null;
  recipient_email: string | null;
  sender_name: string | null;
  sender_email: string | null;
  sender_title: string | null;
  subject: string | null;
  intro_note: string | null;
  finalized_at: string | null;
  created_at: string;
  updated_at: string;
  items: PacketItem[];
  excerpts: Excerpt[];
  context_views: ContextView[];
}

// Minimal script reads, needed only so a producer can pick an excerpt to share.
// The full script UI belongs to M3's frontend work.
export interface ScriptDocument {
  id: string;
  project_id: string;
  filename: string;
  media_type: string;
  scene_count: number;
  status: string;
  created_at: string;
}

export interface Scene {
  id: string;
  index: number;
  heading: string;
  page_number: number | null;
  text: string;
}

// ------------------------------------------------------------ mail loop (M5)

export interface OutboundMessage {
  id: string;
  thread_id: string;
  to_email: string;
  from_email: string;
  reply_to: string;
  subject: string;
  provider: string;
  provider_message_id: string | null;
  status: "queued" | "sent" | "failed";
  error: string | null;
  /** Something the provider said about a successful send — the console provider admits it did not send. */
  note: string | null;
  sent_at: string | null;
  sent_by: string;
  created_at: string;
}

export const REPLY_KINDS = ["approved", "denied", "quote", "needs_info", "unclear"] as const;
export type ReplyKind = (typeof REPLY_KINDS)[number];

export type ProposalStatus = "pending" | "applied" | "rejected" | "superseded";

export interface ProposedChange {
  id: string;
  intent_id: string;
  task_id: string;
  kind: ReplyKind;
  from_stage: Stage;
  to_stage: Stage | null;
  quoted_amount: Decimalish | null;
  currency: string | null;
  /** The span of the reply this came from. A producer confirms against this, not a paraphrase. */
  quote_text: string | null;
  confidence: number;
  note: string | null;
  status: ProposalStatus;
  blocked_reason: string | null;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
  asset_title: string | null;
  layer: Layer | null;
}

export interface ReplyIntent {
  id: string;
  inbound_id: string;
  model: string;
  kind: ReplyKind;
  confidence: number;
  summary: string;
  reasoning: string | null;
  created_at: string;
  changes: ProposedChange[];
}

export interface InboundMessage {
  id: string;
  thread_id: string | null;
  provider: string;
  from_email: string;
  from_name: string | null;
  subject: string | null;
  text_body: string;
  status: "received" | "parsed" | "unroutable" | "failed";
  error: string | null;
  received_at: string;
  intent: ReplyIntent | null;
  packet_id: string | null;
  rightsholder_name: string | null;
}

export interface MailThread {
  id: string;
  packet_id: string;
  reply_to: string;
  closed_at: string | null;
  created_at: string;
  outbound: OutboundMessage[];
  inbound: InboundMessage[];
}

export interface LedgerLine {
  task_id: string;
  asset_id: string;
  asset_title: string | null;
  layer: Layer;
  stage: Stage;
  rightsholder_name: string | null;
  estimate_low: Decimalish | null;
  estimate_high: Decimalish | null;
  quoted: Decimalish | null;
  agreed: Decimalish | null;
  /** The firmest figure available for this task right now. */
  exposure: Decimalish;
  basis: "agreed" | "quoted" | "estimate" | "none";
  /** Firm figure minus the top of the estimate range; null until something firm exists. */
  variance: Decimalish | null;
  closed: boolean;
}

export interface LedgerTotals {
  live_tasks: number;
  closed_tasks: number;
  estimate_low: Decimalish;
  estimate_high: Decimalish;
  quoted_total: Decimalish;
  agreed_total: Decimalish;
  exposure: Decimalish;
  recommended_contingency: Decimalish;
  committed: Decimalish;
  awaiting_reply: number;
  priced_tasks: number;
  over_estimate_tasks: number;
  variance_total: Decimalish;
  worst_variance: Decimalish;
}

export interface Ledger {
  lines: LedgerLine[];
  totals: LedgerTotals;
}

// ------------------------------------------------------------ auth (M6)

export const ROLES = ["owner", "admin", "member", "viewer"] as const;
export type Role = (typeof ROLES)[number];

export interface AppUser {
  id: string;
  org_id: string;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  created_at: string;
}

/** Returned once, by login or register. The token is stored as a digest server-side. */
export interface AuthToken {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: AppUser;
}

export interface Me {
  user: AppUser;
  organization: Organization;
}

export interface UserSession {
  id: string;
  token_hint: string;
  status: "active" | "expired" | "revoked";
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  last_seen_at: string | null;
  client_ip: string | null;
  user_agent: string | null;
}

export interface ExportSummary {
  tasks: number;
  unassigned: number;
  by_stage: Record<string, number>;
  assigned_automatically: number;
  assigned_by_a_person: number;
  signed: number;
  packets: number;
  context_links: number;
  ledger_entries: number;
  actor_breakdown: Record<string, number>;
  reconciliation: { available: boolean; unmatched: number; note: string };
  disclaimer_version: string;
  disclaimer_text: string;
  generated_at: string;
}
