/**
 * Central HTTP client for the TradeCraft frontend.
 *
 * WHY THIS EXISTS
 * ---------------
 * Previously every screen hand-rolled `fetch()` with inconsistent error
 * handling (some checked `res.ok`, some didn't; some parsed JSON, some fell
 * back to `.text()`; none shared timeouts or a place to attach auth headers).
 * That is what caused the `null.toFixed()` crashes (guards inconsistent across
 * call sites) and makes it impossible to add auth/retries centrally.
 *
 * This module:
 *  - wraps `fetch` once (base URL, JSON (de)serialization, timeout, abort)
 *  - throws a typed `ApiError` on network errors and non-2xx responses
 *  - exposes typed endpoint helpers under `quantgen.*` (and more as we migrate)
 *  - is the single place to add auth headers / retries later
 *
 * Base URL is configurable at build time via `VITE_API_BASE_URL` (default `/api`).
 */

const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") || "/api";

/** Re-export for code that previously used a literal `"/api"` constant. */
export const API_URL = API_BASE;

/**
 * API auth token, injected at build time from the root .env (API_AUTH_TOKEN)
 * by vite.config.ts. Sent as an `X-API-Token` header on every request so the
 * backend can authenticate the client. Empty in the rare case it isn't set.
 */
export const API_TOKEN: string =
  (import.meta.env.VITE_API_TOKEN as string | undefined) || "";

export class ApiError extends Error {
  readonly status: number;
  readonly data: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

/** Structured error object returned by TradeCraft endpoints on 2xx-with-error. */
export interface ApiErrorShape {
  type?: string;
  category?: string;
  message?: string;
  details?: Record<string, any>;
  [key: string]: unknown;
}

/** Common envelope shape returned by most TradeCraft endpoints. */
export interface ApiEnvelope<T = unknown> {
  success?: boolean;
  data?: T;
  error?: ApiErrorShape;
  output?: string;
  [key: string]: unknown;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
  /** JSON body — serialized automatically. Omit for GET/DELETE with no body. */
  body?: unknown;
  /** Appended to the URL as a query string. Undefined values are skipped. */
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Override the default request timeout (ms). */
  timeoutMs?: number;
  /** Extra headers (e.g. future auth tokens). */
  headers?: Record<string, string>;
  /** External AbortSignal for caller-driven cancellation. Combined with the
   *  internal timeout signal (whichever aborts first wins). */
  signal?: AbortSignal;
  /**
   * Accept a non-JSON (e.g. text) 2xx body. Defaults to false: when the
   * response is not JSON, we throw an `ApiError` instead of guessing.
   */
  rawText?: boolean;
}

/**
 * Core request helper. Throws `ApiError` on network failure, timeout,
 * non-2xx status, or unexpected content-type.
 */
export async function request<T = unknown>(
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const {
    method = "GET",
    body,
    query,
    timeoutMs = 300_000, // 5 min — code generation / WFO runs are slow
    headers,
    rawText = false,
    signal: externalSignal,
  } = opts;

  // Build URL
  let url = `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null) params.set(k, String(v));
    }
    const qs = params.toString();
    if (qs) url += (url.includes("?") ? "&" : "?") + qs;
  }

  // Build init
  const init: RequestInit = { method, headers: { ...(headers ?? {}) } };
  if (API_TOKEN) {
    init.headers = { ...init.headers, "X-API-Token": API_TOKEN };
  }
  if (body !== undefined) {
    init.headers = { ...init.headers, "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }

  // Timeout + external cancellation (whichever aborts first wins).
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  init.signal = externalSignal
    ? AbortSignal.any([controller.signal, externalSignal])
    : controller.signal;

  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    const aborted =
      err instanceof DOMException && err.name === "AbortError";
    if (aborted && externalSignal?.aborted) {
      // Caller cancelled the request (AbortController) — propagate the
      // original AbortError so handlers that check `err.name === "AbortError"`
      // keep working (e.g. TickerDetailDrawer / ChartView).
      throw err;
    }
    throw new ApiError(
      aborted
        ? `Request timed out after ${timeoutMs}ms (${path})`
        : `Network error (${path}): ${err instanceof Error ? err.message : String(err)}`,
      0,
      { path },
    );
  } finally {
    clearTimeout(timer);
  }

  // Empty success
  if (res.status === 204) return undefined as T;

  const contentType = res.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");

  // Non-2xx: try to surface a structured message from the body.
  if (!res.ok) {
    let data: unknown = null;
    try {
      data = isJson ? await res.json() : await res.text();
    } catch {
      /* ignore parse failure */
    }
    const message = extractErrorMessage(data, res.status, res.statusText);
    throw new ApiError(message, res.status, data);
  }

  // 2xx body
  if (rawText) return (await res.text()) as unknown as T;
  if (!isJson) {
    // Mirrors the old code's "Expected JSON but got …" guard.
    throw new ApiError(
      `Expected JSON but got "${contentType}" for ${path}`,
      res.status,
    );
  }
  return (await res.json()) as T;
}

function extractErrorMessage(data: unknown, status: number, statusText: string): string {
  if (data && typeof data === "object") {
    const d = data as Record<string, unknown>;
    const err = d.error;
    if (err && typeof err === "object") {
      const m = (err as Record<string, unknown>).message;
      if (typeof m === "string" && m) return m;
    }
    if (typeof err === "string" && err) return err;
    if (typeof d.detail === "string" && d.detail) return d.detail;
    if (typeof d.message === "string" && d.message) return d.message;
  }
  if (typeof data === "string" && data) return data;
  return `HTTP ${status} ${statusText || ""}`.trim();
}

/* ------------------------------------------------------------------ *
 * Typed endpoints (QuantGen)                                          *
 * ------------------------------------------------------------------ */

export interface GeneratePayload {
  prompt: string;
  tickers: string[];
  start_date: string;
  end_date: string;
}

export interface GenerateResult {
  success?: boolean;
  data?: {
    code?: string;
    output?: string;
    fix_attempts?: number;
    lessons_applied?: string[];
  };
  error?: ApiEnvelope["error"];
}

export interface StrategyParam {
  name: string;
  start: number;
  stop: number;
  step: number;
}

export interface RunPayload {
  code: string;
  tickers: string[];
}
export interface OptimizePayload extends RunPayload {
  strategy_params: Record<string, { start: number; stop: number; step: number }>;
  config: unknown;
}

/** Open result payload for /run and /optimize (fields are backend-defined). */
export interface RunData {
  output?: string;
  stats?: unknown;
  best_equity?: unknown[];
  equity?: unknown[];
  windows?: unknown;
  error?: ApiErrorShape;
  // trades, ohlcv, drawdown, benchmark_drawdown, indicators, mode, heatmap,
  // oos_equity, benchmark_equity, ... are backend-defined; keep them loose.
  [key: string]: any;
}
export type RunResult = ApiEnvelope<RunData>;

export interface LatestDateResult {
  success?: boolean;
  data?: { latest_date?: string };
}

export const quantgen = {
  latestDate: () =>
    request<LatestDateResult>("/latest-date"),

  listStrategies: () =>
    request<ApiEnvelope<{ strategies?: any }>>("/strategies"),

  generate: (payload: GeneratePayload) =>
    request<GenerateResult>("/generate", { method: "POST", body: payload }),

  run: (payload: RunPayload) =>
    request<RunResult>("/run", { method: "POST", body: payload }),

  optimize: (payload: OptimizePayload) =>
    request<RunResult>("/optimize", { method: "POST", body: payload }),

  saveStrategy: (name: string, code: string) =>
    request<ApiEnvelope>("/strategies", {
      method: "POST",
      body: { name, code },
    }),

  loadStrategy: (name: string) =>
    request<ApiEnvelope<{ code?: any }>>(`/strategies/${encodeURIComponent(name)}`),

  deleteStrategy: (name: string) =>
    request<ApiEnvelope>(`/strategies/${encodeURIComponent(name)}`, { method: "DELETE" }),

  strategyCatalog: () =>
    request<ApiEnvelope<{
      strategies_by_category?: any;
      categories?: any;
      indicators?: any;
    }>>("/strategy-catalog"),

  strategyBySlug: (slug: string) =>
    request<ApiEnvelope<{ code?: any; metadata?: any }>>(`/strategy-catalog/${encodeURIComponent(slug)}`),

  tickerInfo: (ticker: string) =>
    request<ApiEnvelope>(`/ticker-info/${encodeURIComponent(ticker)}`),

  researchTicker: (ticker: string, mode: string) =>
    request<ApiEnvelope>(`/research/${encodeURIComponent(ticker)}`, { query: { mode } }),

  indicatorCatalog: () =>
    request<ApiEnvelope<{ indicators?: any }>>("/indicators/catalog"),
};
