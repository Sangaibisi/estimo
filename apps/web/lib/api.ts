/**
 * Thin client for the Estimo API.
 *
 * Base URL resolution order: runtime-injected `window.__ESTIMO_API__` (set by the
 * root layout from the ESTIMO_API_URL container env — never baked into the bundle),
 * then NEXT_PUBLIC_ESTIMO_API (dev convenience), then the local default.
 */

declare global {
  interface Window {
    __ESTIMO_API__?: string;
  }
}

export function apiBase(): string {
  const base =
    (typeof window !== "undefined" && window.__ESTIMO_API__) ||
    process.env.NEXT_PUBLIC_ESTIMO_API ||
    "http://localhost:8000";
  // Paths always start with "/" — a trailing slash in the configured origin would
  // produce "//v1/…" and 404 every call.
  return base.replace(/\/+$/, "");
}

export interface EstimateSummary {
  id: string;
  brd_ref: string;
  title: string;
  status: string;
  requirements: number;
  blocked: number;
  open_questions: number;
  work_items: number;
  has_boe: boolean;
}

export interface ThreePoint {
  optimistic: number;
  likely: number;
  pessimistic: number;
}

export interface HeldRequirement {
  requirement_id: string;
  text: string;
  reason: string;
}

/** Cone-of-uncertainty stage a draft was issued at, and the band it promises
 * (PRINCIPLES #1 / McConnell). Concept-stage numbers are a different claim from
 * detailed-stage ones, so the desk says which it is showing. */
export const CONE_MULTIPLIER: Record<string, string> = {
  concept: "±4x",
  approved_scope: "±1.6x",
  detailed: "±1.25x",
};

export interface DeskItem {
  work_item: {
    id: string;
    title: string;
    description?: string | null;
    module_tags: string[];
    requirement_ids: string[];
  };
  independent: ThreePoint | null;
  rationale: string | null;
  confidence: string | null;
  discovery_pd: number | null;
  signed: boolean;
  delphi: {
    // "you_first" and "below_threshold" carry no band-shaped value at all — with two
    // panelists a median plus your own band reconstructs the other person's exactly.
    state: "you_first" | "below_threshold" | "open";
    estimators: number;
    threshold: number;
    bands: ThreePoint[];
    consensus: ThreePoint | null;
    spread_likely: number | null;
    overlap: "intersect" | "disjoint" | null;
  };
  ai: {
    range: ThreePoint;
    confidence: string;
    basis_note?: string | null;
    evidence: { uri: string; kind: string; label?: string | null }[];
    assumptions: { kind: string; text: string; contingency_pd: number | null }[];
    risks: { kind: string; text: string; contingency_pd: number | null }[];
  } | null;
  delta_likely: number | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    ...init,
    headers:
      init?.body instanceof FormData
        ? init?.headers
        : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status}: ${detail}`);
  }
  return (await response.json()) as T;
}

export const api = {
  listEstimates: () => request<EstimateSummary[]>("/v1/estimates"),
  getEstimate: (id: string) =>
    request<{
      summary: EstimateSummary;
      state: Record<string, unknown>;
      boe: Record<string, unknown> | null;
      critic: string[];
      fully_signed: boolean;
    }>(`/v1/estimates/${id}`),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<EstimateSummary>("/v1/estimates", {
      method: "POST",
      body: form,
    });
  },
  applyAnswers: (id: string, answers: Record<string, string>) =>
    request<EstimateSummary>(`/v1/estimates/${id}/answers`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),
  buildBoe: (id: string) =>
    request<{ status: string; version: number; critic: string[] }>(
      `/v1/estimates/${id}/estimate`,
      { method: "POST" },
    ),
  desk: (id: string, estimator: string) =>
    request<{
      items: DeskItem[];
      has_boe: boolean;
      held: HeldRequirement[];
      cone_stage: string | null;
    }>(`/v1/estimates/${id}/desk?estimator=${encodeURIComponent(estimator)}`),
  recordIndependent: (
    id: string,
    payload: {
      work_item_id: string;
      estimator: string;
      rationale?: string;
    } & ThreePoint,
  ) =>
    request<{ status: string }>(`/v1/estimates/${id}/independent`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  sign: (
    id: string,
    payload: { work_item_id: string; name: string; role: string },
  ) =>
    request<{ status: string }>(`/v1/estimates/${id}/sign`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  event: (id: string, kind: string, payload?: Record<string, unknown>) =>
    request<{ status: string }>(`/v1/estimates/${id}/events`, {
      method: "POST",
      body: JSON.stringify({ kind, payload }),
    }),
  boeDocxUrl: (id: string) => `${apiBase()}/v1/estimates/${id}/boe.docx`,
  recordActual: (
    id: string,
    payload: {
      work_item_id: string;
      actual_effort: number;
      actual_source: string;
      scope_changed: boolean;
      team?: string;
    },
  ) =>
    request<{ status: string; deviation: number | null }>(
      `/v1/estimates/${id}/actuals`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),
  listActuals: (id: string) =>
    request<ActualEntry[]>(`/v1/estimates/${id}/actuals`),
  metrics: () => request<MetricsOverview>("/v1/metrics/overview"),
  ledger: (q: string) =>
    request<{
      entries: LedgerEntry[];
      total: number;
      with_actuals: number;
      searched: boolean;
    }>(`/v1/ledger?q=${encodeURIComponent(q)}`),
  listConnections: () => request<ConnectionEntry[]>("/v1/connections"),
  createConnection: (payload: {
    kind: string;
    name: string;
    base_url: string;
    config: Record<string, unknown>;
    secret_env: string | null;
    secret: string | null;
    acl_keys: string[] | null;
  }) =>
    request<ConnectionEntry>("/v1/connections", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteConnection: (id: string) =>
    request<void>(`/v1/connections/${id}`, { method: "DELETE" }),
  triggerSync: (id: string) =>
    request<{ status: string }>(`/v1/connections/${id}/sync`, {
      method: "POST",
    }),
  listCanonical: () => request<CanonicalEntry[]>("/v1/canonical"),
  createCanonical: (topic: string) =>
    request<{ id: string; status: string }>("/v1/canonical", {
      method: "POST",
      body: JSON.stringify({ topic }),
    }),
  approveCanonical: (id: string, approver: string) =>
    request<{ id: string; status: string; version: number }>(
      `/v1/canonical/${id}/approve`,
      { method: "POST", body: JSON.stringify({ approver }) },
    ),
  systemInfo: () => request<SystemInfo>("/v1/system"),
  gatewayCheck: () =>
    request<GatewayCheckResult>("/v1/system/gateway-check", { method: "POST" }),
  putGateway: (payload: {
    reset?: boolean;
    base_url?: string;
    api_key?: string;
    clear_api_key?: boolean;
    profiles?: Record<string, string>;
    timeout_seconds?: number;
    connect_timeout_seconds?: number;
    max_retries?: number;
  }) =>
    request<GatewayView>("/v1/system/gateway", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
};

export interface GatewayView {
  base_url: string;
  api_key_present: boolean;
  profiles: Record<string, string>;
  timeout_seconds: number;
  connect_timeout_seconds: number;
  max_retries: number;
  source: "panel" | "environment";
  secrets_encrypted: boolean;
  stored_key_readable: boolean;
}

export interface SystemInfo {
  version: string;
  auth: {
    mode: "oidc" | "open";
    issuer: string | null;
    audience: string | null;
    role_claim: string;
    tenant_claim: string;
    acl_claim: string | null;
  };
  gateway: GatewayView;
  database: { host: string | null; name: string | null; role: string | null };
  cors_origins: string[];
}

export interface GatewayCheckResult {
  ok: boolean;
  model?: string;
  latency_ms: number;
  error?: string;
}

export interface ConnectionEntry {
  id: string;
  kind: string;
  name: string;
  base_url: string;
  config: Record<string, unknown>;
  secret_env: string | null;
  secret_present: boolean;
  secret_stored: boolean;
  acl_keys: string[] | null;
  last_run: {
    status: string;
    started_at: string;
    finished_at: string | null;
    stats: Record<string, unknown> | null;
    error: string | null;
  } | null;
}

export interface CanonicalEntry {
  id: string;
  topic: string;
  title: string;
  body: string;
  status: string;
  version: number;
  approved_by: string | null;
  source_refs: string[] | null;
  stale: boolean;
  updated_at: string;
}

export interface ActualEntry {
  work_item_id: string;
  actual_effort: number | null;
  actual_source: string | null;
  completed_at: string | null;
  scope_changed: boolean;
  team: string | null;
  domain_tags: string[];
  recorded_band: {
    optimistic: number | null;
    likely: number | null;
    pessimistic: number | null;
  };
  deviation: number | null;
}

/** Parse a person-day input accepting both `1.5` and the Turkish `1,5`;
 * returns null for anything non-finite or non-positive. */
export function parseEffort(raw: string): number | null {
  const value = Number(raw.trim().replace(",", "."));
  return Number.isFinite(value) && value > 0 ? value : null;
}

export interface MetricsOverview {
  calibration: {
    current: {
      samples: number;
      prior_based: boolean;
      q10: number;
      q50: number;
      q90: number;
      rolling_coverage: number | null;
    };
    series: {
      at: string;
      samples: number;
      prior_based: boolean;
      q10: number;
      q50: number;
      q90: number;
      nominal: number;
      rolling_coverage: number | null;
    }[];
  };
  product_accuracy: {
    samples: number;
    coverage: number | null;
    nominal: number;
    mae_product: number | null;
    mae_naive_median: number | null;
  };
  anchoring: {
    samples: number;
    mean_abs_delta: number | null;
    zero_delta_share: number | null;
  };
  workflow: {
    estimates: number;
    wip: number;
    question_revision_rate: number | null;
    rebuild_share: number | null;
  };
}

export interface LedgerEntry {
  id: string;
  brd_ref: string;
  item_title: string;
  module_tags: string[];
  team: string | null;
  estimate: {
    optimistic: number | null;
    likely: number | null;
    pessimistic: number | null;
    single: number | null;
  };
  actual_effort: number | null;
  actual_source: string | null;
  scope_changed: boolean;
  deviation: number | null;
  origin: "product" | "imported";
  completed_at: string | null;
}
