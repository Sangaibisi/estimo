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
  if (typeof window !== "undefined" && window.__ESTIMO_API__) {
    return window.__ESTIMO_API__;
  }
  return process.env.NEXT_PUBLIC_ESTIMO_API ?? "http://localhost:8000";
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

export interface DeskItem {
  work_item: {
    id: string;
    title: string;
    description?: string | null;
    module_tags: string[];
    requirement_ids: string[];
  };
  independent: ThreePoint | null;
  signed: boolean;
  ai: {
    range: ThreePoint;
    confidence: string;
    basis_note?: string | null;
    evidence: { uri: string; kind: string; label?: string | null }[];
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
    request<{ summary: EstimateSummary; state: Record<string, unknown>; boe: Record<string, unknown> | null }>(
      `/v1/estimates/${id}`,
    ),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<EstimateSummary>("/v1/estimates", { method: "POST", body: form });
  },
  applyAnswers: (id: string, answers: Record<string, string>) =>
    request<EstimateSummary>(`/v1/estimates/${id}/answers`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),
  buildBoe: (id: string) =>
    request<{ boe: Record<string, unknown>; critic: string[] }>(
      `/v1/estimates/${id}/estimate`,
      { method: "POST" },
    ),
  desk: (id: string, estimator: string) =>
    request<{ items: DeskItem[]; has_boe: boolean }>(
      `/v1/estimates/${id}/desk?estimator=${encodeURIComponent(estimator)}`,
    ),
  recordIndependent: (
    id: string,
    payload: { work_item_id: string; estimator: string } & ThreePoint,
  ) =>
    request<{ status: string }>(`/v1/estimates/${id}/independent`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  sign: (id: string, payload: { work_item_id: string; name: string; role: string }) =>
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
};
