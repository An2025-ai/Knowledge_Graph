import type { ChatResult, GraphData, Job, SearchItem, Stats } from "./types";

export type AppSettings = {
  llm_provider: "none" | "openai-compatible";
  llm_base_url: string;
  llm_model: string;
  embedding_provider: "none" | "openai-compatible";
  embedding_base_url: string;
  embedding_model: string;
  data_dir?: string;
  llm_api_key_configured?: boolean;
};

export type ConnectionTestResult = {
  status: "ok" | "error";
  llm: { status: "ok" | "error" | "skipped"; message: string };
  embedding: { status: "ok" | "error" | "skipped"; message: string };
};

export type ProviderTestResult = {
  status: "ok" | "error" | "skipped";
  message: string;
};

let apiBase = import.meta.env.VITE_API_BASE || "/api";
let apiToken = import.meta.env.VITE_API_TOKEN || "dev-token";

/** Configure the API origin supplied by the desktop shell at runtime. */
export function configureRuntime(baseUrl: string, token: string) {
  const normalized = baseUrl.replace(/\/$/, "");
  apiBase = normalized.endsWith("/api") ? normalized : `${normalized}/api`;
  apiToken = token;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${apiToken}`);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${apiBase}${path}`, { ...init, headers });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `API request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; llm_provider: string }>("/health"),
  settings: () => request<AppSettings>("/settings"),
  updateSettings: (payload: Record<string, unknown>) => request<{ status: string; settings: AppSettings }>("/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  }),
  testSettings: (payload: Record<string, unknown>) => request<ConnectionTestResult>("/settings/test", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  testLlm: (payload: Record<string, unknown>) => request<ProviderTestResult>("/settings/test/llm", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  testEmbedding: (payload: Record<string, unknown>) => request<ProviderTestResult>("/settings/test/embedding", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  stats: () => request<Stats>("/stats"),
  graph: (layer?: string) => request<GraphData>(`/graph${layer ? `?layer=${layer}` : ""}`),
  search: (query: string) => request<{ items: SearchItem[] }>(`/graph/search?q=${encodeURIComponent(query)}`),
  documents: () => request<Array<Record<string, unknown>>>("/documents"),
  chat: (message: string, history: Array<{ role: "user" | "assistant"; content: string }> = []) => request<ChatResult>("/agent/chat", {
    method: "POST",
    body: JSON.stringify({ message, history: history.slice(-10) }),
  }),
  importDocument: (payload: Record<string, unknown>) => request<{ job_id: string }>("/documents/import", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  job: (jobId: string) => request<Job>(`/documents/jobs/${jobId}`),
};
