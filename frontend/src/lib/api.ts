import { isCodedError, type AddLayerBody, type ValidationError } from "@/lib/api-types";
import type {
  Asset,
  AuditEntry,
  Board,
  BudgetTotals,
  Disclaimer,
  IngestResult,
  Layer,
  Project,
  Rightsholder,
  RightsholderKind,
  Stage,
  Task,
} from "@/lib/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "http://localhost:8000";

/** Placeholder identity until auth lands in M6; the backend reads X-User-Id. */
export const USER_ID = process.env.NEXT_PUBLIC_USER_ID ?? "dev-user";

export class ApiError extends Error {
  status: number;
  code?: string;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(ApiError.messageFrom(status, detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    if (isCodedError(detail) && detail.code) {
      this.code = detail.code;
    }
  }

  /** True when the disclaimer gate (HTTP 428) rejected a write. */
  get isDisclaimerRequired() {
    return this.status === 428;
  }

  /** True when the workflow rules (HTTP 409) rejected a transition. */
  get isWorkflowError() {
    return this.status === 409;
  }

  private static messageFrom(status: number, detail: unknown): string {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const first = detail[0] as ValidationError | undefined;
      if (first?.msg) return `${(first.loc ?? []).slice(1).join(".")}: ${first.msg}`;
    } else if (isCodedError(detail) && detail.message) {
      return detail.message;
    }
    return `Request failed (${status})`;
  }
}

async function request<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const { json, ...rest } = init;
  const res = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: {
      "X-User-Id": USER_ID,
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...rest.headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
    cache: "no-store",
  });

  if (!res.ok) {
    let detail: unknown = null;
    try {
      const body = await res.json();
      detail = body?.detail ?? body;
    } catch {
      detail = await res.text().catch(() => null);
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") search.set(k, String(v));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
};

export const api = {
  // ---------------------------------------------------------- disclaimer
  getDisclaimer: () => request<Disclaimer>("/api/disclaimer"),
  acceptDisclaimer: () => request<Disclaimer>("/api/disclaimer/accept", { method: "POST" }),

  // ---------------------------------------------------------- projects
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (body: {
    name: string;
    distribution_scope: string;
    production_tier: string;
  }) => request<Project>("/api/projects", { method: "POST", json: body }),
  updateProject: (
    id: string,
    body: Partial<{ name: string; distribution_scope: string; production_tier: string }>,
  ) => request<Project>(`/api/projects/${id}`, { method: "PATCH", json: body }),
  deleteProject: (id: string) =>
    request<void>(`/api/projects/${id}`, { method: "DELETE" }),

  // ---------------------------------------------------------- ingest + views
  ingest: (
    projectId: string,
    items: { url: string; notes?: string | null; usage_seconds?: number | null }[],
  ) =>
    request<IngestResult[]>(`/api/projects/${projectId}/ingest`, {
      method: "POST",
      json: { items },
    }),
  listAssets: (projectId: string) => request<Asset[]>(`/api/projects/${projectId}/assets`),
  listTasks: (projectId: string) => request<Task[]>(`/api/projects/${projectId}/tasks`),
  board: (projectId: string) => request<Board>(`/api/projects/${projectId}/board`),
  budget: (projectId: string) => request<BudgetTotals>(`/api/projects/${projectId}/budget`),
  reestimateProject: (projectId: string) =>
    request<BudgetTotals>(`/api/projects/${projectId}/estimate`, { method: "POST" }),

  // ---------------------------------------------------------- assets
  getAsset: (id: string) => request<Asset>(`/api/assets/${id}`),
  updateAsset: (
    id: string,
    body: Partial<{
      title: string | null;
      owner_name: string | null;
      description: string | null;
      published_at: string | null;
      inferred_keywords: string[];
      user_notes: string | null;
      usage_seconds: number | null;
      remap: boolean;
    }>,
  ) => request<Asset>(`/api/assets/${id}`, { method: "PATCH", json: body }),
  deleteAsset: (id: string) => request<void>(`/api/assets/${id}`, { method: "DELETE" }),
  addLayer: (assetId: string, layer: Layer) =>
    request<Task>(`/api/assets/${assetId}/layers`, {
      method: "POST",
      json: { layer } satisfies AddLayerBody,
    }),
  remapAsset: (assetId: string) =>
    request<Asset>(`/api/assets/${assetId}/remap`, { method: "POST" }),

  // ---------------------------------------------------------- tasks
  getTask: (id: string) => request<Task>(`/api/tasks/${id}`),
  updateTask: (
    id: string,
    body: Partial<{
      rightsholder_id: string | null;
      quoted_amount: string | null;
      agreed_amount: string | null;
      notes: string | null;
      reason: string | null;
    }>,
  ) => request<Task>(`/api/tasks/${id}`, { method: "PATCH", json: body }),
  transition: (id: string, to: Stage, reason?: string) =>
    request<Task>(`/api/tasks/${id}/transition`, {
      method: "POST",
      json: { to, reason: reason ?? null },
    }),
  estimateTask: (id: string) =>
    request<Task>(`/api/tasks/${id}/estimate`, { method: "POST" }),
  taskHistory: (id: string) => request<AuditEntry[]>(`/api/tasks/${id}/history`),

  // ---------------------------------------------------------- directory
  searchRightsholders: (params: {
    q?: string;
    kind?: RightsholderKind;
    layer?: Layer;
    limit?: number;
  }) => request<Rightsholder[]>(`/api/rightsholders${qs(params)}`),
  getRightsholder: (id: string) => request<Rightsholder>(`/api/rightsholders/${id}`),

  // ---------------------------------------------------------- audit
  audit: (params: { table?: string; row_id?: string; actor_type?: string; limit?: number }) =>
    request<AuditEntry[]>(`/api/audit${qs(params)}`),
};
