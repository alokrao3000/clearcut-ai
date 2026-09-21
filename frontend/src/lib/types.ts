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
  updated_at: string;
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
