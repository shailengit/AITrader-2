// Typed client for /api/strategy-lab/*

import { request } from "@/lib/api";

export interface ModelVariant {
  name: string;
  type: "cloud" | "local";
  size_bytes?: number;
}

export interface OllamaModel {
  id: string;
  variants: ModelVariant[];
}

export interface StrategySession {
  id: string;
  name: string;
  prompt: string;
  plan_text: string | null;
  code_text: string | null;
  model_id: string;
  tags: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface CreateSessionInput {
  name: string;
  prompt: string;
  model_id: string;
  tags?: string[];
}

export interface UpdateSessionInput {
  plan_text?: string;
  code_text?: string;
  tags?: string[];
  name?: string;
}

export interface ListSessionsParams {
  search?: string;
  tags?: string[];
  limit?: number;
  offset?: number;
}

export interface StrategyClassItem {
  name: string;
  path: string;
  description: string;
  created_at: string | null;
  modified_at: string | null;
  cagr_pct: number | null;
  sharpe_ratio: number | null;
  total_return_pct: number | null;
  win_rate: number | null;
  max_drawdown_pct: number | null;
  total_trades: number | null;
  last_backtest: string | null;
  deployed: boolean;
  deployed_at: string | null;
}

export interface ExperimentRow {
  id: string;
  session_id: string;
  batch_id: string;
  run_index: number;
  start_date: string | null;
  end_date: string | null;
  status: string;
  error_message: string | null;
  kpis: Record<string, any> | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface BatchStats {
  n_total: number;
  n_completed: number;
  n_failed: number;
  mean_sharpe: number | null;
  best_sharpe: number | null;
  best_experiment_id: string | null;
  top_3: Array<{ id: string; run_index: number; start_date: string; sharpe: number; kpis: any }>;
  worst_3: Array<{ id: string; run_index: number; start_date: string; sharpe: number; kpis: any }>;
}

export interface LibraryEntryResponse {
  version: number;
  strategy_name: string;
  created_at: string;
  change_description: string;
  backtest_kpis: Record<string, any>;
  code?: string;
  folder?: string;
}

export interface LibraryListResponse {
  name: string;
  display_name: string;
  version_count: number;
  latest_version: LibraryEntryResponse;
  versions: LibraryEntryResponse[];
}

export interface DeploymentInfo {
  deployment_id: string;
  class_name: string;
  class_file_path: string;
  is_active: boolean;
  deployed_at: string | null;
  rolled_back_at: string | null;
  experiment_id: string | null;
  session_id: string;
  verification?: Record<string, boolean>;
}

export interface DeploymentListItem {
  deployment_id: string;
  class_name: string;
  class_file_path: string;
  is_active: boolean;
  deployed_at: string | null;
  rolled_back_at: string | null;
  experiment_id: string | null;
  session_id: string;
}

const base = "/strategy-lab";

async function getJson<T>(url: string): Promise<T> {
  return request<T>(url);
}

async function postJson<T>(url: string, body: unknown, timeoutMs?: number): Promise<T> {
  return request<T>(url, { method: "POST", body, timeoutMs });
}

async function patchJson<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, { method: "PATCH", body });
}

async function deleteJson(url: string): Promise<void> {
  await request(url, { method: "DELETE" });
}

export const strategyLabApi = {
  listModels: () => getJson<OllamaModel[]>(`${base}/models`),

  listSessions: (params: ListSessionsParams = {}) => {
    const q = new URLSearchParams();
    if (params.search) q.set("search", params.search);
    if (params.tags && params.tags.length > 0) q.set("tags", params.tags.join(","));
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    if (params.offset !== undefined) q.set("offset", String(params.offset));
    const qs = q.toString();
    return getJson<StrategySession[]>(`${base}/sessions${qs ? `?${qs}` : ""}`);
  },

  getSession: (id: string) => getJson<StrategySession>(`${base}/sessions/${id}`),

  createSession: (body: CreateSessionInput) => postJson<StrategySession>(`${base}/sessions`, body),

  updateSession: (id: string, body: UpdateSessionInput) =>
    patchJson<StrategySession>(`${base}/sessions/${id}`, body),

  deleteSession: (id: string) => deleteJson(`${base}/sessions/${id}`),

  // ── Strategy class endpoints (new mode) ──
  listStrategyClasses: () => getJson<StrategyClassItem[]>(`${base}/strategy-classes`),

  deleteStrategyClass: (path: string) =>
    postJson<{ deleted: string; name: string }>(`${base}/strategy-classes/delete`, { path }),

  startExperimentsWithClass: (strategyClassPath: string, body: { n_runs: number; end_date: string; start_date_min?: string; start_date_max?: string }) =>
    postJson<{ batch_id: string }>(`${base}/sessions/_/experiments`, {
      ...body,
      strategy_class_path: strategyClassPath,
    }),

  deployStrategyClass: (strategyClassPath: string, experimentId: string, sourceHypothesisIds?: string[]) =>
    postJson<DeploymentInfo>(`${base}/sessions/_/deploy`, {
      strategy_class_path: strategyClassPath,
      experiment_id: experimentId,
      source_hypothesis_ids: sourceHypothesisIds ?? [],
    }),

  // ── Experiment endpoints ──
  startExperiments: (id: string, body: { n_runs: number; end_date: string; start_date_min?: string; start_date_max?: string; fixed_start_dates?: string[]; model?: string }) =>
    postJson<{ batch_id: string }>(`${base}/sessions/${id}/experiments`, body),

  listExperiments: (id: string) => getJson<ExperimentRow[]>(`${base}/sessions/${id}/experiments`),

  listBatchExperiments: (id: string, batchId: string) =>
    getJson<ExperimentRow[]>(`${base}/sessions/${id}/batches/${batchId}/experiments`),

  getBatchStats: (id: string, batchId: string) =>
    getJson<BatchStats>(`${base}/sessions/${id}/batches/${batchId}/stats`),

  getEquityCurve: (experimentId: string) =>
    getJson<{ equity_curve: Array<{ date: string; value: number }> }>(
      `${base}/experiments/${experimentId}/equity-curve`,
    ),

  // ── Deployment endpoints ──
  listDeployments: (params: { active_only?: boolean } = {}) => {
    const q = new URLSearchParams();
    if (params.active_only) q.set("active_only", "true");
    const qs = q.toString();
    return getJson<DeploymentListItem[]>(`${base}/deployments${qs ? `?${qs}` : ""}`);
  },

  rollbackDeployment: (deploymentId: string) =>
    postJson<{ rolled_back_deployment_id: string; new_active_class_name: string }>(
      `${base}/deployments/${deploymentId}/rollback`,
      {},
    ),

  // ── Library endpoints ──
  saveToLibrary: (id: string, body: { name: string; change_description?: string; model?: string }) =>
    postJson<LibraryEntryResponse>(`${base}/sessions/${id}/library/save`, body),

  listLibrary: () => getJson<LibraryListResponse[]>(`${base}/library`),

  getLibraryEntry: (name: string) => getJson<LibraryListResponse>(`${base}/library/${name}`),

  loadFromLibrary: (body: { name: string; version?: number }) =>
    postJson<StrategySession>(`${base}/library/load`, body),
};
