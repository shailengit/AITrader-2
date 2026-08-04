// Typed client for /api/coach/*

export interface KPISet {
  total_pnl: number;
  win_rate: number;
  expectancy: number;
  n_trades: number;
  n_open: number;
  max_dd: number;
  current_dd: number;
  sharpe_proxy: number;
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
}

const base = '/api/coach';

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`GET ${url} -> ${res.status}`);
  return res.json() as Promise<T>;
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST ${url} -> ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const coachApi = {
  overview: (params: { period_start?: string; period_end?: string; strategy_id?: string; strategy_path?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.period_start) q.set('period_start', params.period_start);
    if (params.period_end) q.set('period_end', params.period_end);
    if (params.strategy_id) q.set('strategy_id', params.strategy_id);
    if (params.strategy_path) q.set('strategy_path', params.strategy_path);
    return getJson<OverviewResponse>(`${base}/metrics/overview?${q}`);
  },
  maeMfe: (params: { period_start?: string; period_end?: string; strategy_id?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.period_start) q.set('period_start', params.period_start);
    if (params.period_end) q.set('period_end', params.period_end);
    if (params.strategy_id) q.set('strategy_id', params.strategy_id);
    return getJson<MAEMFEPoint[]>(`${base}/metrics/mae-mfe?${q}`);
  },
  winRateByStrategy: (params: { period_start?: string; period_end?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.period_start) q.set('period_start', params.period_start);
    if (params.period_end) q.set('period_end', params.period_end);
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
    fetch(`${base}/trades/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => r.json() as Promise<Trade>),
  closeTrade: (id: string, body: { exit_px?: number; exit_at?: string } = {}) =>
    postJson<Trade>(`${base}/trades/${id}/close`, body),
  deleteTrade: (id: string) => fetch(`${base}/trades/${id}`, { method: 'DELETE' }),
  listStrategies: () => getJson<Strategy[]>(`${base}/strategies`),
  createStrategy: (body: {
    kind: Strategy['kind'];
    name: string;
    params?: Record<string, unknown>;
    notes?: string;
  }) => postJson<Strategy>(`${base}/strategies`, body),
  patchStrategy: (id: string, body: Partial<Strategy>) =>
    fetch(`${base}/strategies/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => r.json() as Promise<Strategy>),
  generateReport: (body: { period_start?: string; period_end?: string; strategy_id?: string; model?: string }) =>
    postJson<ReportDetail>(`${base}/report`, body),
  listReports: (limit = 20) => getJson<ReportSummary[]>(`${base}/reports?limit=${limit}`),
  getReport: (id: string) => getJson<ReportDetail>(`${base}/reports/${id}`),
  deleteReport: (id: string) => fetch(`${base}/reports/${id}`, { method: 'DELETE' }),
};
