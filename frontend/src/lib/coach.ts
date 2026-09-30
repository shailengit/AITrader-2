// Typed client for /api/coach/*

import { request } from "@/lib/api";

export interface KPISet {
  total_pnl: number;
  win_rate: number;
  expectancy: number;
  n_trades: number;
  n_open: number;
  max_dd: number;
  current_dd: number;
  sharpe_proxy: number;
  kpi_mode?: 'pct';
  label?: string;
}

export interface Trade {
  id: string;
  ticker: string;
  side: 'long' | 'short';
  qty: number;
  entry_px: number;
  exit_px: number | null;
  entry_at: string;
  exit_at: string | null;
  pnl: number | null;
  pnl_pct: number | null;
  mae: number | null;
  mfe: number | null;
  strategy_id: string | null;
  signal_id: string | null;
  notes: string | null;
}

export interface Strategy {
  id: string;
  kind: 'screener' | 'quantgen' | 'markov' | 'manual';
  name: string;
  params: Record<string, unknown>;
  created_at: string;
  retired_at: string | null;
  notes: string | null;
}

export interface OverviewResponse {
  empty?: boolean;
  period: { start: string; end: string };
  kpis?: KPISet;
  equity_curve?: { date: string; equity: number }[];
  drawdown_curve?: { date: string; dd: number }[];
  pnl_by_regime?: Record<string, { n: number; pnl: number; pnl_pct: number }>;
  win_rate_by_strategy?: { strategy_id: string; name: string; n: number; win_rate: number }[];
  entry_timing_lag?: { p25: number; p50: number; p75: number; mean: number; n: number };
}

export interface MAEMFEPoint {
  mae: number | null;
  mfe: number | null;
  pnl: number | null;
  ticker: string;
  entry_at: string | null;
}

export interface ReportSummary {
  id: string;
  generated_at: string;
  period_start: string;
  period_end: string;
  strategy_id: string | null;
  model_id: string;
  duration_ms: number | null;
}

export interface ReportDetail extends ReportSummary {
  report_md: string;
  metrics: Record<string, unknown>;
  bundle: Record<string, unknown>;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  empty?: boolean;
  message?: string;
}

const base = '/coach';

async function getJson<T>(url: string): Promise<T> {
  return request<T>(url);
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, { method: 'POST', body });
}

export const coachApi = {
  overview: (params: { period_start?: string; period_end?: string; strategy_id?: string; strategy_path?: string; source?: 'live' | 'backtest' } = {}) => {
    const q = new URLSearchParams();
    if (params.period_start) q.set('period_start', params.period_start);
    if (params.period_end) q.set('period_end', params.period_end);
    if (params.strategy_id) q.set('strategy_id', params.strategy_id);
    if (params.strategy_path) q.set('strategy_path', params.strategy_path);
    if (params.source) q.set('source', params.source);
    return getJson<OverviewResponse>(`${base}/metrics/overview?${q}`);
  },
  maeMfe: (params: { period_start?: string; period_end?: string; strategy_id?: string; source?: 'live' | 'backtest' } = {}) => {
    const q = new URLSearchParams();
    if (params.period_start) q.set('period_start', params.period_start);
    if (params.period_end) q.set('period_end', params.period_end);
    if (params.strategy_id) q.set('strategy_id', params.strategy_id);
    if (params.source) q.set('source', params.source);
    return getJson<MAEMFEPoint[]>(`${base}/metrics/mae-mfe?${q}`);
  },
  winRateByStrategy: (params: { period_start?: string; period_end?: string; source?: 'live' | 'backtest' } = {}) => {
    const q = new URLSearchParams();
    if (params.period_start) q.set('period_start', params.period_start);
    if (params.period_end) q.set('period_end', params.period_end);
    if (params.source) q.set('source', params.source);
    return getJson<{ strategy_id: string; name: string; n: number; win_rate: number }[]>(`${base}/metrics/win-rate-by-strategy?${q}`);
  },
  listTrades: (params: { limit?: number; offset?: number; strategy_id?: string; open_only?: boolean } = {}) => {
    const q = new URLSearchParams();
    if (params.limit) q.set('limit', String(params.limit));
    if (params.offset) q.set('offset', String(params.offset));
    if (params.strategy_id) q.set('strategy_id', params.strategy_id);
    if (params.open_only) q.set('open_only', 'true');
    return getJson<{ total: number; rows: Trade[] }>(`${base}/trades?${q}`);
  },
  createTrade: (body: Partial<Trade> & { ticker: string; qty: number; entry_px: number; entry_at: string }) =>
    postJson<Trade>(`${base}/trades`, body),
  patchTrade: (id: string, body: Partial<Trade>) =>
    request<Trade>(`${base}/trades/${id}`, { method: 'PATCH', body }),
  closeTrade: (id: string, body: { exit_px?: number; exit_at?: string } = {}) =>
    postJson<Trade>(`${base}/trades/${id}/close`, body),
  deleteTrade: (id: string) => request(`${base}/trades/${id}`, { method: 'DELETE' }),
  listStrategies: () => getJson<Strategy[]>(`${base}/strategies`),
  createStrategy: (body: {
    kind: Strategy['kind'];
    name: string;
    params?: Record<string, unknown>;
    notes?: string;
  }) => postJson<Strategy>(`${base}/strategies`, body),
  patchStrategy: (id: string, body: Partial<Strategy>) =>
    request<Strategy>(`${base}/strategies/${id}`, { method: 'PATCH', body }),
  generateReport: (body: { period_start?: string; period_end?: string; strategy_id?: string; model?: string; source?: 'live' | 'backtest' }) =>
    postJson<ReportDetail>(`${base}/report`, body),
  listReports: (limit = 20) => getJson<ReportSummary[]>(`${base}/reports?limit=${limit}`),
  getReport: (id: string) => getJson<ReportDetail>(`${base}/reports/${id}`),
  deleteReport: (id: string) => request(`${base}/reports/${id}`, { method: 'DELETE' }),
  listBacktestAnalyses: (params: { strategy_name?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.strategy_name) q.set('strategy_name', params.strategy_name);
    if (params.limit) q.set('limit', String(params.limit));
    return getJson<BacktestAnalysis[]>(`${base}/backtest-analyses?${q}`);
  },
  getBacktestAnalysis: (id: string) => getJson<BacktestAnalysis>(`${base}/backtest-analyses/${id}`),
  getBacktestAnalysisReport: (id: string) =>
    request<string>(`${base}/backtest-analyses/${id}/report`, { rawText: true }),
  getBacktestAnalysisRuns: (id: string) =>
    getJson<BacktestAnalysisRuns>(`${base}/backtest-analyses/${id}/runs`),
  deleteBacktestAnalysis: (id: string) =>
    request(`${base}/backtest-analyses/${id}`, { method: 'DELETE' }),
};

export interface BacktestRunCurve {
  run_index: number;
  start_date: string | null;
  end_date: string | null;
  total_return_pct: number | null;
  curve: { date: string; pct_return: number }[];
}

export interface BacktestAnalysisRuns {
  strategy_name: string;
  runs: BacktestRunCurve[];
}

export interface BacktestAnalysis {
  id: string;
  strategy_name: string;
  strategy_class_path: string;
  batch_id: string;
  report_path: string | null;
  run_summary: {
    n_runs: number;
    n_completed: number;
    n_trades: number;
    best_return_pct?: number | null;
    worst_return_pct?: number | null;
    median_return_pct?: number | null;
    best_cagr_pct?: number | null;
    worst_cagr_pct?: number | null;
    median_cagr_pct?: number | null;
    median_trades_per_year?: number | null;
    median_avg_winner_pct?: number | null;
    median_avg_loser_pct?: number | null;
    median_profit_factor?: number | null;
    mean_win_rate_pct?: number | null;
    start_date?: string | null;
    end_date?: string | null;
  } | null;
  analysis_md: string;
  suggestions: Record<string, unknown> | null;
  model_id: string;
  n_runs: number;
  n_completed: number;
  n_trades: number;
  created_at: string | null;
}
