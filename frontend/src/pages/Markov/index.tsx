import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { request } from "@/lib/api";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useTheme } from "../../context/ThemeContext";
import ControlPanel, { ScanParams } from "./components/ControlPanel";
import SectorRegimeGrid from "./components/SectorRegimeGrid";
import SignalsTable from "./components/SignalsTable";
import TickerDetailDrawer from "../app/ScreenerBuilder/TickerDetailDrawer";
import { recordAppReferrer } from "../../components/layout/Layout";
import type { IndicatorDescriptor } from "../../types/indicators";

interface SectorRegime {
  etf: string;
  regime: string;
  bull_probability: number;
  vol_regime: string;
}

interface Signal {
  ticker: string;
  sector: string;
  signal: string;
  conviction: number;
  price: number;
  regime: string;
  vol_regime: string;
  etf: string;
}

interface ScanProgress {
  running: boolean;
  progress_pct: number;
  current_ticker: string;
  current_action: string;
  tickers_completed: number;
  tickers_total: number;
  elapsed_seconds: number;
  estimated_remaining_seconds: number;
  started_at: number | null;
  stale?: boolean;
}

export default function MarkovPage() {
  const { isDarkMode } = useTheme();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [drawerTicker, setDrawerTicker] = useState<string | null>(() => {
    const t = searchParams.get('ticker');
    return t ? t.toUpperCase() : null;
  });
  const [loading, setLoading] = useState(false);
  const [sectors, setSectors] = useState<SectorRegime[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [totalScanned, setTotalScanned] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ScanProgress | null>(null);
  const [lastMinConviction, setLastMinConviction] = useState(0.6);
  const [lastAsOfDate, setLastAsOfDate] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const progressRef = useRef<ScanProgress | null>(null);
  // Keep the ref in sync so the interval callback can read the latest progress
  // without re-creating the interval on every progress update.
  useEffect(() => { progressRef.current = progress; }, [progress]);

  // Theme-aware colors
  const colors = {
    error: "#EF4444",
    muted: isDarkMode ? "rgba(255,255,255,0.7)" : "#6e6e73",
    surface: isDarkMode ? "#1A1D21" : "#f5f5f7",
    border: isDarkMode ? "rgba(255,255,255,0.12)" : "#d2d2d7",
    accent: "#10B981",
    accentMuted: isDarkMode ? "rgba(16,185,129,0.15)" : "rgba(16,185,129,0.1)",
  };

  // Poll scan progress while loading
  useEffect(() => {
    if (loading) {
      pollRef.current = setInterval(async () => {
        try {
          const data = await request<ScanProgress>("/markov/scan-status");
          setProgress(data);
          // Stale detection: if the backend stopped responding or
          // the process crashed (SIGSEGV in PyTorch LSTM kernels),
          // the status is frozen at running=true with zero progress.
          // Reset so the user gets an actionable error.
          if (data.stale) {
            setLoading(false);
            setError(
              "The scan process stopped responding — " +
              "LSTM training crashed the backend (OpenMP / PyTorch segfault). " +
              "Please try again; the server should have auto-restarted."
            );
          }
        } catch {
          // Connection refused / server restarting — check if we went idle
          // but the progress never completed (e.g. server segfaulted)
          const p = progressRef.current;
          if (p && p.running && p.elapsed_seconds > 300) {
            setLoading(false);
            setError(
              "The backend server appears to have crashed during the scan. " +
              "Please refresh the page and try again with XGBoost instead of LSTM."
            );
          }
        }
      }, 2000);  // Poll every 2s (less aggressive than 1s for production)
    } else {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      setProgress(null);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loading]);

  // Restore scan results from sessionStorage on mount
  useEffect(() => {
    try {
      const cached = sessionStorage.getItem('markov:scan:results');
      if (cached) {
        const parsed = JSON.parse(cached);
        const age = Date.now() - (parsed.timestamp || 0);
        // Only restore if less than 5 minutes old
        if (age < 5 * 60 * 1000 && Array.isArray(parsed.signals)) {
          setSignals(parsed.signals);
          if (parsed.sectors) setSectors(parsed.sectors);
          if (parsed.totalScanned != null) setTotalScanned(parsed.totalScanned);
        } else {
          sessionStorage.removeItem('markov:scan:results');
        }
      }
    } catch {
      sessionStorage.removeItem('markov:scan:results');
    }
  }, []);

  // Sync drawerTicker to ?ticker= URL param
  useEffect(() => {
    if (drawerTicker) {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('ticker', drawerTicker);
          return next;
        },
        { replace: true },
      );
    } else {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('ticker');
          return next;
        },
        { replace: true },
      );
    }
  }, [drawerTicker, setSearchParams]);

  const handleScan = useCallback(async (params: ScanParams) => {
    setLoading(true);
    setDrawerTicker(null);
    setError(null);
    setSignals([]);
    setSectors([]);
    setProgress(null);
    setLastMinConviction(params.minConviction);
    setLastAsOfDate(params.asOfDate);

    // Write scan params to URL for state persistence
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set('model', params.model);
        next.set('threshold', String(params.threshold));
        next.set('minConviction', String(params.minConviction));
        next.set('maxResults', String(params.maxResults));
        if (params.asOfDate) next.set('asOfDate', params.asOfDate);
        return next;
      },
      { replace: true },
    );

    try {
      const data = await request<any>("/markov/scan", {
        method: "POST",
        body: {
          model: params.model,
          threshold: params.threshold,
          min_conviction: params.minConviction,
          max_results: params.maxResults,
          end_date: params.asOfDate || undefined,
        },
      });
      if (data.signals != null) setSignals(data.signals);
      if (data.sector_status != null) setSectors(data.sector_status);
      if (data.total_scanned != null) setTotalScanned(data.total_scanned);
      // Cache results in sessionStorage for navigation persistence
      try {
        sessionStorage.setItem('markov:scan:results', JSON.stringify({
          signals: data.signals,
          sectors: data.sector_status,
          totalScanned: data.total_scanned,
          params: { model: params.model, threshold: params.threshold, minConviction: params.minConviction, maxResults: params.maxResults, asOfDate: params.asOfDate },
          timestamp: Date.now(),
        }));
      } catch { /* sessionStorage may be full; ignore */ }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setLoading(false);
    }
  }, [setSearchParams]);

  const openTicker = useCallback((ticker: string) => {
    setDrawerTicker(ticker.toUpperCase());
  }, []);

  const closeDrawer = useCallback(() => {
    setDrawerTicker(null);
  }, []);

  // Format elapsed time
  const formatTime = (seconds: number): string => {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  };

  const defaultIndicators: IndicatorDescriptor[] = useMemo(() => [
    { id: 'trend_ema_fast__window20', label: 'EMA 20', params: { window: 20 } },
    { id: 'trend_ema_slow__window200', label: 'EMA 200', params: { window: 200 } },
  ], []);

  const handleOpenInChart = useCallback((ticker: string) => {
    recordAppReferrer('/markov', 'Markov Chain Trader');
    const params = new URLSearchParams();
    if (lastAsOfDate) params.set('from', lastAsOfDate);
    // Pass default indicators as overlay params so the full-page chart
    // renders EMA20 and EMA200 by default.
    const overlayIds = defaultIndicators.map((d) => d.id).join(',');
    const overlayLabels = defaultIndicators.map((d) => d.label).join(',');
    const paramMap: Record<string, Record<string, number>> = {};
    for (const d of defaultIndicators) {
      if (d.params && Object.keys(d.params).length > 0) {
        paramMap[d.id] = d.params;
      }
    }
    params.set('overlays', overlayIds);
    params.set('labels', overlayLabels);
    if (Object.keys(paramMap).length > 0) {
      params.set('params', JSON.stringify(paramMap));
    }
    navigate(`/markov/chart/${encodeURIComponent(ticker)}?${params.toString()}`);
  }, [navigate, lastAsOfDate, defaultIndicators]);

  const handleExportToLab = useCallback((ticker: string) => {
    recordAppReferrer('/markov', 'Markov Chain Trader');
    const fromDate = lastAsOfDate || new Date().toISOString().split('T')[0];
    navigate(`/quantgen/build?tickers=${encodeURIComponent(ticker)}&from_date=${fromDate}`);
  }, [navigate, lastAsOfDate]);

  const cachedParams = useMemo(() => {
    try {
      const cached = sessionStorage.getItem('markov:scan:results');
      if (cached) {
        const parsed = JSON.parse(cached);
        return parsed.params || {};
      }
    } catch { /* ignore */ }
    return {};
  }, []);

  return (
    <div style={{ maxWidth: 1280, margin: "0 auto" }}>
      <ControlPanel
        onScan={handleScan}
        loading={loading}
        initialValues={{
          model: (['xgboost', 'lstm'].includes(searchParams.get('model') ?? '')
            ? searchParams.get('model') as 'xgboost' | 'lstm'
            : cachedParams.model) || undefined,
          threshold: searchParams.get('threshold') ? parseFloat(searchParams.get('threshold')!) : (cachedParams.threshold ?? undefined),
          minConviction: searchParams.get('minConviction') ? parseFloat(searchParams.get('minConviction')!) : (cachedParams.minConviction ?? undefined),
          maxResults: searchParams.get('maxResults') ? parseInt(searchParams.get('maxResults')!, 10) : (cachedParams.maxResults ?? undefined),
          asOfDate: searchParams.get('asOfDate') || cachedParams.asOfDate || undefined,
        }}
      />

      {error && (
        <div style={{ padding: "12px 24px", color: colors.error, fontSize: 14 }}>
          Error: {error}
        </div>
      )}

      {/* Progress Bar — shown during scan */}
      {loading && progress && (
        <div style={{ padding: "16px 24px" }}>
          <div style={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            borderRadius: 12,
            padding: "20px 24px",
          }}>
            {/* Status header */}
            <div style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 12,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                {/* Pulsing dot */}
                <div style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  backgroundColor: colors.accent,
                  animation: "pulse-dot 1.2s ease-in-out infinite",
                }} />
                <span style={{ fontWeight: 600, fontSize: 15 }}>
                  {progress.current_action || "Scanning..."}
                </span>
              </div>
              <div style={{ textAlign: "right", fontSize: 13, color: colors.muted }}>
                <div>{formatTime(progress.elapsed_seconds)} elapsed</div>
                {progress.estimated_remaining_seconds > 0 && (
                  <div>~{formatTime(progress.estimated_remaining_seconds)} remaining</div>
                )}
              </div>
            </div>

            {/* Progress bar */}
            <div style={{
              width: "100%",
              height: 8,
              borderRadius: 4,
              background: isDarkMode ? "rgba(255,255,255,0.1)" : "#e5e7eb",
              overflow: "hidden",
              marginBottom: 8,
            }}>
              <div style={{
                width: `${Math.max(progress.progress_pct, 2)}%`,
                height: "100%",
                borderRadius: 4,
                background: `linear-gradient(90deg, ${colors.accent}, #34D399, ${colors.accent})`,
                backgroundSize: "200% 100%",
                animation: "shimmer 1.5s ease-in-out infinite",
                transition: "width 0.5s ease",
              }} />
            </div>

            {/* Ticker count and current ticker */}
            <div style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 13,
              color: colors.muted,
            }}>
              <span>
                {progress.current_ticker ? (
                  <>Processing <strong style={{ color: colors.accent }}>{progress.current_ticker}</strong> ({progress.tickers_completed}/{progress.tickers_total})</>
                ) : (
                  <>{progress.tickers_completed}/{progress.tickers_total} tickers</>
                )}
              </span>
              <span>{progress.progress_pct.toFixed(0)}%</span>
            </div>
          </div>
        </div>
      )}

      {/* Loading skeleton for signals table */}
      {loading && !progress && (
        <div style={{ padding: "24px", textAlign: "center" }}>
          <div style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 10,
            padding: "16px 24px",
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            borderRadius: 10,
          }}>
            <div style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              backgroundColor: colors.accent,
              animation: "pulse-dot 1.2s ease-in-out infinite",
            }} />
            <span style={{ color: colors.muted, fontSize: 14 }}>
              Initializing scan...
            </span>
          </div>
        </div>
      )}

      {sectors.length > 0 && <SectorRegimeGrid sectors={sectors} isDarkMode={isDarkMode} />}
      <SignalsTable signals={signals} totalScanned={totalScanned} loading={loading} isDarkMode={isDarkMode} minConviction={lastMinConviction} asOfDate={lastAsOfDate} onTickerClick={openTicker} />
      <TickerDetailDrawer
        ticker={drawerTicker}
        asOfDate={lastAsOfDate || undefined}
        indicators={defaultIndicators}
        scoreRow={null}
        onClose={closeDrawer}
        onOpenInChart={handleOpenInChart}
        onExportToLab={handleExportToLab}
      />
    </div>
  );
}
