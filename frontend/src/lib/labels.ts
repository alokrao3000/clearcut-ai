import type {
  DistributionScope,
  Layer,
  ProductionTier,
  RightsholderKind,
  Stage,
} from "@/lib/types";

export const STAGE_LABEL: Record<Stage, string> = {
  sourced: "Sourced",
  rights_mapped: "Rights mapped",
  budget_approved: "Budget approved",
  outreach_sent: "Outreach sent",
  quote_received: "Quote received",
  deal_memo_signed: "Deal memo signed",
  denied: "Denied",
  dropped: "Dropped",
};

/** Board column order: the pipeline first, then the two closed columns. */
export const PIPELINE_STAGES: Stage[] = [
  "sourced",
  "rights_mapped",
  "budget_approved",
  "outreach_sent",
  "quote_received",
  "deal_memo_signed",
];
export const CLOSED_STAGES: Stage[] = ["denied", "dropped"];

export const STAGE_ACCENT: Record<Stage, string> = {
  sourced: "border-l-slate-400 dark:border-l-slate-500",
  rights_mapped: "border-l-sky-500",
  budget_approved: "border-l-violet-500",
  outreach_sent: "border-l-amber-500",
  quote_received: "border-l-teal-500",
  deal_memo_signed: "border-l-emerald-600",
  denied: "border-l-rose-500",
  dropped: "border-l-zinc-400",
};

export const STAGE_BADGE: Record<Stage, string> = {
  sourced: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
  rights_mapped: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200",
  budget_approved: "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-200",
  outreach_sent: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  quote_received: "bg-teal-100 text-teal-900 dark:bg-teal-950 dark:text-teal-200",
  deal_memo_signed: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  denied: "bg-rose-100 text-rose-900 dark:bg-rose-950 dark:text-rose-200",
  dropped: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
};

export const LAYER_LABEL: Record<Layer, string> = {
  footage: "Footage",
  still_image: "Still image",
  master_recording: "Master recording",
  composition: "Composition (sync)",
  performance: "Performer likeness",
  trademark: "Trademark",
};

export const SCOPE_LABEL: Record<DistributionScope, string> = {
  festival: "Film festivals only",
  worldwide_streaming: "Worldwide streaming",
  all_media_perpetual: "All media perpetual",
};

export const TIER_LABEL: Record<ProductionTier, string> = {
  ultra_low: "Ultra low budget",
  sag_moderate_low: "SAG moderate low",
  studio_feature: "Studio feature",
};

export const KIND_LABEL: Record<RightsholderKind, string> = {
  studio: "Studio",
  broadcaster: "Broadcaster",
  label: "Label",
  publisher: "Publisher",
  stock_agency: "Stock agency",
  archive: "Archive",
  individual: "Individual",
  brand: "Brand",
};

export const ACTOR_LABEL: Record<string, string> = {
  user: "User",
  system: "System",
  scraper: "Scraper",
  llm: "LLM",
};
