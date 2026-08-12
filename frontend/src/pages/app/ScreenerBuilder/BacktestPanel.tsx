import { useState, useEffect, useCallback } from "react";
import { request } from "@/lib/api";
import { useTheme } from "../../../context/ThemeContext";
import { Card } from "../../../components/ui/Card";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { ChevronDown, ChevronRight, RefreshCw, AlertCircle, TrendingUp } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TickerBacktestResult {
  ticker: string;
  buy_price: number;
  current_price: number;
  return_pct: number;
  buy_date: string;
}

interface BacktestAggregate {
  avg_return_pct: number;
  median_return_pct: number;
  best: { ticker: string; return_pct: number };
  worst: { ticker: string; return_pct: number };
  equal_weight_portfolio_return_pct: number;
}

interface BenchmarkResult {
  ticker: string;
  buy_price: number;
  current_price: number;
  return_pct: number;
}

interface BacktestResponse {
  as_of_date: string;
  as_of_actual: string;
  latest_date: string;
  days_held: number;
  ticker_results: TickerBacktestResult[];
  aggregate: BacktestAggregate;
  benchmark: BenchmarkResult;
  alpha_pct: number;
}

// New endpoint response shape (POST /api/screener/backtest-exit)
interface PerTradeEntry {
  ticker: string;
  sector?: string | null;
  entry_date: string;
  entry_price: number;
  exit_date: string;
  exit_price: number;
  exit_reason: string;
  holding_days: number;
  pnl_dollars: number;
  pnl_pct: number;
  mfe_pct: number;
  mae_pct: number;
}

interface BacktestExitResponse {
  config: Record<string, unknown>;
  warnings: string[];
  per_trade: PerTradeEntry[];
  summary: {
    total_return_pct: number;
    annualized_return_pct: number;
    sharpe: number;
    sortino: number;
    max_drawdown_pct: number;
    win_rate_pct: number;
    profit_factor: number;
    avg_winner_pct: number;
    avg_loser_pct: number;
    avg_holding_days: number;
    n_trades: number;
    n_winners: number;
    n_losers: number;
  };
  equity_curve: Array<{ time: number; value: number }>;
  drawdown_curve: Array<{ time: number; dd_pct: number }>;
  benchmark: {
    spy_return_pct: number;
    alpha_pct: number;
    spy_equity_curve: Array<{ time: number; value: number }>;
  };
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface BacktestPanelProps {
  tickers: string[];
  asOfDate: string; // ISO date string, e.g. "2024-01-15"
  customFilters?: Record<string, any>; // Flat backend-format filters from the user's
                                       // current Custom Screener. Required when the
                                       // user picks Screener="Custom" in this panel;
                                       // without it, the backend runs the custom
                                       // screener with no filter set and returns
                                       // a totally different stock list.
  onClose?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatCurrency(value: number): string {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatReturn(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

function isFutureDate(isoDate: string): boolean {
  if (!isoDate) return false;
  const d = new Date(isoDate);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return d >= today;
}

// ---------------------------------------------------------------------------
// BacktestPanel
// ---------------------------------------------------------------------------

export default function BacktestPanel({ tickers, asOfDate, customFilters }: BacktestPanelProps) {
  const { isDarkMode } = useTheme();
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<BacktestResponse | null>(null);

  // Exit-rule backtest state
  const [mode, setMode] = useState<"hold" | "exit">("hold");
  const [exitLoading, setExitLoading] = useState(false);
  const [exitError, setExitError] = useState<string | null>(null);
  const [exitData, setExitData] = useState<BacktestExitResponse | null>(null);
  const [exitRules, setExitRules] = useState({
    stop_loss_pct: 0.08,
    take_profit_pct: 0.20,
    trailing_stop_pct: 0.0,
    trend_break_sma: 20,
    max_holding_days: 0,
    max_lookback_days: 120,
  });
  const [exitTopN, setExitTopN] = useState(20);
  const [exitScreenerKind, setExitScreenerKind] = useState<"dormant_giant" | "custom">("dormant_giant");

  // Theme-aware colors
  const colors = {
    text: isDarkMode ? "#ffffff" : "#1d1d1f",
    muted: isDarkMode ? "rgba(255,255,255,0.6)" : "#6e6e73",
    subtle: isDarkMode ? "rgba(255,255,255,0.4)" : "#86868b",
    border: isDarkMode ? "rgba(255,255,255,0.08)" : "#e5e5ea",
    surface: isDarkMode ? "#0a0a0a" : "#ffffff",
    cardBg: isDarkMode ? "#272729" : "#ffffff",
    positive: "#10B981",
    negative: "#EF4444",
    accent: "#10B981",
    rowEven: isDarkMode ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.02)",
    rowHover: isDarkMode ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.04)",
  };

  const fetchBacktest = useCallback(async () => {
    if (tickers.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const json = await request<BacktestResponse>("/screener/backtest-hold", {
        method: "POST",
        body: { tickers, as_of_date: asOfDate },
      });
      setData(json);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backtest unavailable — backend offline");
    } finally {
      setLoading(false);
    }
  }, [tickers, asOfDate]);

  // Fetch when expanded for the first time
  useEffect(() => {
    if (expanded && !data && !loading && !error) {
      fetchBacktest();
    }
  }, [expanded, data, loading, error, fetchBacktest]);

  const runExitBacktest = useCallback(async () => {
    setExitLoading(true);
    setExitError(null);
    // If the user picked "Custom" but the parent never threaded the
    // current screener's filter set down to us, refuse to run with a
    // clear message. Without this guard, the backend would run the
    // custom screener with an empty filter set and return an unrelated
    // batch of stocks.
    if (exitScreenerKind === "custom" && (!customFilters || Object.keys(customFilters).length === 0)) {
      setExitLoading(false);
      setExitError("Custom Screener requires at least one filter in the main builder. Add a filter to the screener above before running With Exit Rules.");
      return;
    }
    const screenerPayload =
      exitScreenerKind === "custom"
        ? { kind: "custom", filters: customFilters ?? {} }
        : { kind: "dormant_giant" };
    try {
      const json = await request<BacktestExitResponse>("/screener/backtest-exit", {
        method: "POST",
        body: {
          as_of_date: asOfDate,
          top_n: exitTopN,
          sizing: { mode: "equal_weight" },
          screener: screenerPayload,
          exit_rules: exitRules,
        },
      });
      setExitData(json);
    } catch (err) {
      setExitError(err instanceof Error ? err.message : "Exit-rule backtest unavailable — backend offline");
    } finally {
      setExitLoading(false);
    }
  }, [asOfDate, exitTopN, exitScreenerKind, exitRules, customFilters]);

  // Validation
  const noTickers = tickers.length === 0;
  const futureDate = isFutureDate(asOfDate);

  if (noTickers) {
    return (
      <Card variant="base" className="p-6">
        <div style={{ display: "flex", alignItems: "center", gap: 12, color: colors.muted, fontSize: 14 }}>
          <TrendingUp size={18} style={{ color: colors.subtle, flexShrink: 0 }} />
          <span>No tickers to backtest</span>
        </div>
      </Card>
    );
  }

  if (futureDate) {
    return (
      <Card variant="base" className="p-6">
        <div style={{ display: "flex", alignItems: "center", gap: 12, color: colors.muted, fontSize: 14 }}>
          <AlertCircle size={18} style={{ color: colors.negative, flexShrink: 0 }} />
          <span>As-Of Date must be in the past</span>
        </div>
      </Card>
    );
  }

  return (
    <Card variant="base" className="overflow-hidden">
      {/* Collapsible header */}
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          width: "100%",
          padding: "16px 20px",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          color: colors.text,
          fontSize: 14,
          fontWeight: 600,
          textAlign: "left",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <TrendingUp size={18} style={{ color: colors.accent, flexShrink: 0 }} />
          <span>
            Buy &amp; Hold from {asOfDate}
            {data ? (
              <span style={{ color: colors.muted, fontWeight: 400, marginLeft: 8 }}>
                to {data.latest_date} ({data.days_held}d)
              </span>
            ) : null}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {data && (
            <Badge variant={data.aggregate.avg_return_pct >= 0 ? "emerald" : "red"} size="sm">
              {formatReturn(data.aggregate.avg_return_pct)}
            </Badge>
          )}
          {expanded ? <ChevronDown size={16} style={{ color: colors.subtle }} /> : <ChevronRight size={16} style={{ color: colors.subtle }} />}
        </div>
      </button>

      {/* Collapsible content */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${colors.border}` }}>
          {/* Loading state */}
          {loading && (
            <div style={{ padding: 32, textAlign: "center" }}>
              <div
                style={{
                  width: 24,
                  height: 24,
                  border: `2px solid ${colors.border}`,
                  borderTopColor: colors.accent,
                  borderRadius: "50%",
                  margin: "0 auto 12px",
                  animation: "spin 0.8s linear infinite",
                }}
              />
              <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
              <div style={{ color: colors.muted, fontSize: 13 }}>Running backtest for {tickers.length} ticker{tickers.length !== 1 ? "s" : ""}...</div>
            </div>
          )}

          {/* Error state */}
          {error && !loading && (
            <div style={{ padding: 24, textAlign: "center" }}>
              <AlertCircle size={24} style={{ color: colors.negative, margin: "0 auto 8px", display: "block" }} />
              <div style={{ color: colors.muted, fontSize: 13, marginBottom: 16 }}>{error}</div>
              <Button variant="secondary" size="sm" leftIcon={<RefreshCw size={14} />} onClick={fetchBacktest}>
                Retry
              </Button>
            </div>
          )}

          {/* Results */}
          {data && !loading && (
            <div style={{ padding: "16px 20px 20px" }}>
              {/* Ticker results table */}
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: "8px 12px", color: colors.subtle, fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: `1px solid ${colors.border}` }}>
                        Ticker
                      </th>
                      <th style={{ textAlign: "right", padding: "8px 12px", color: colors.subtle, fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: `1px solid ${colors.border}` }}>
                        Buy Price
                      </th>
                      <th style={{ textAlign: "right", padding: "8px 12px", color: colors.subtle, fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: `1px solid ${colors.border}` }}>
                        Current
                      </th>
                      <th style={{ textAlign: "right", padding: "8px 12px", color: colors.subtle, fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: `1px solid ${colors.border}` }}>
                        Return
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.ticker_results.map((result, idx) => {
                      const positive = result.return_pct >= 0;
                      return (
                        <tr
                          key={result.ticker}
                          style={{
                            backgroundColor: idx % 2 === 1 ? colors.rowEven : "transparent",
                            transition: "background-color 0.1s ease",
                          }}
                          onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = colors.rowHover; }}
                          onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = idx % 2 === 1 ? colors.rowEven : "transparent"; }}
                        >
                          <td style={{ padding: "10px 12px", fontWeight: 600, color: colors.text }}>
                            {result.ticker}
                          </td>
                          <td style={{ padding: "10px 12px", textAlign: "right", color: colors.text, fontVariantNumeric: "tabular-nums" }}>
                            {formatCurrency(result.buy_price)}
                          </td>
                          <td style={{ padding: "10px 12px", textAlign: "right", color: colors.text, fontVariantNumeric: "tabular-nums" }}>
                            {formatCurrency(result.current_price)}
                          </td>
                          <td
                            style={{
                              padding: "10px 12px",
                              textAlign: "right",
                              fontWeight: 600,
                              color: positive ? colors.positive : colors.negative,
                              fontVariantNumeric: "tabular-nums",
                            }}
                          >
                            {formatReturn(result.return_pct)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Aggregate stats */}
              <div
                style={{
                  marginTop: 16,
                  padding: "14px 16px",
                  borderRadius: 10,
                  backgroundColor: isDarkMode ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.02)",
                  border: `1px solid ${colors.border}`,
                }}
              >
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 24px", fontSize: 13 }}>
                  <StatRow label="Avg Return" value={formatReturn(data.aggregate.avg_return_pct)} positive={data.aggregate.avg_return_pct >= 0} colors={colors} />
                  <StatRow label="Median Return" value={formatReturn(data.aggregate.median_return_pct)} positive={data.aggregate.median_return_pct >= 0} colors={colors} />
                  <StatRow
                    label="Best"
                    value={`${data.aggregate.best.ticker} ${formatReturn(data.aggregate.best.return_pct)}`}
                    positive={true}
                    colors={colors}
                  />
                  <StatRow
                    label="Worst"
                    value={`${data.aggregate.worst.ticker} ${formatReturn(data.aggregate.worst.return_pct)}`}
                    positive={false}
                    colors={colors}
                  />
                  <StatRow label="SPY" value={formatReturn(data.benchmark.return_pct)} positive={data.benchmark.return_pct >= 0} colors={colors} />
                  <StatRow label="Alpha" value={formatReturn(data.alpha_pct)} positive={data.alpha_pct >= 0} colors={colors} />
                </div>
              </div>
            </div>
          )}

          {/* Exit-rule backtest (mode toggle + form + results) */}
          <div
            style={{
              padding: "16px 20px 20px",
              borderTop: `1px solid ${colors.border}`,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
              <label style={{ fontSize: 12, color: colors.muted, fontWeight: 600 }}>Mode:</label>
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as "hold" | "exit")}
                style={{
                  border: `1px solid ${colors.border}`,
                  borderRadius: 6,
                  padding: "4px 8px",
                  fontSize: 12,
                  background: colors.surface,
                  color: colors.text,
                }}
              >
                <option value="hold">Buy and Hold (above)</option>
                <option value="exit">With Exit Rules</option>
              </select>
            </div>

            {mode === "exit" && (
              <>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(2, 1fr)",
                    gap: 10,
                    marginBottom: 12,
                    padding: 12,
                    border: `1px solid ${colors.border}`,
                    borderRadius: 8,
                    backgroundColor: isDarkMode ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.01)",
                  }}
                >
                  <ExitField label="Screener" colors={colors}>
                    <select
                      value={exitScreenerKind}
                      onChange={(e) => setExitScreenerKind(e.target.value as "dormant_giant" | "custom")}
                      style={inputStyle(colors)}
                    >
                      <option value="dormant_giant">Dormant Giant</option>
                      <option value="custom">Custom</option>
                    </select>
                  </ExitField>
                  <ExitField label="Top N" colors={colors}>
                    <input
                      type="number"
                      min={1}
                      max={200}
                      value={exitTopN}
                      onChange={(e) => setExitTopN(Math.max(1, Number(e.target.value)))}
                      style={inputStyle(colors)}
                    />
                  </ExitField>
                  <ExitField label="Stop Loss (%)" colors={colors}>
                    <input
                      type="number"
                      step={0.01}
                      min={0}
                      max={1}
                      value={exitRules.stop_loss_pct}
                      onChange={(e) => setExitRules({ ...exitRules, stop_loss_pct: Number(e.target.value) })}
                      style={inputStyle(colors)}
                    />
                  </ExitField>
                  <ExitField label="Take Profit (%)" colors={colors}>
                    <input
                      type="number"
                      step={0.01}
                      min={0}
                      max={5}
                      value={exitRules.take_profit_pct}
                      onChange={(e) => setExitRules({ ...exitRules, take_profit_pct: Number(e.target.value) })}
                      style={inputStyle(colors)}
                    />
                  </ExitField>
                  <ExitField label="Trailing Stop (%)" colors={colors}>
                    <input
                      type="number"
                      step={0.01}
                      min={0}
                      max={1}
                      value={exitRules.trailing_stop_pct}
                      onChange={(e) => setExitRules({ ...exitRules, trailing_stop_pct: Number(e.target.value) })}
                      style={inputStyle(colors)}
                    />
                  </ExitField>
                  <ExitField label="Trend Break SMA N (0=off)" colors={colors}>
                    <input
                      type="number"
                      step={1}
                      min={0}
                      max={200}
                      value={exitRules.trend_break_sma}
                      onChange={(e) => setExitRules({ ...exitRules, trend_break_sma: Number(e.target.value) })}
                      style={inputStyle(colors)}
                    />
                  </ExitField>
                  <ExitField label="Max Holding Days (0=off)" colors={colors}>
                    <input
                      type="number"
                      step={1}
                      min={0}
                      max={365}
                      value={exitRules.max_holding_days}
                      onChange={(e) => setExitRules({ ...exitRules, max_holding_days: Number(e.target.value) })}
                      style={inputStyle(colors)}
                    />
                  </ExitField>
                  <ExitField label="Forward Lookback Days (1-365)" colors={colors}>
                    <input
                      type="number"
                      step={1}
                      min={1}
                      max={365}
                      value={exitRules.max_lookback_days}
                      onChange={(e) => setExitRules({ ...exitRules, max_lookback_days: Number(e.target.value) })}
                      style={inputStyle(colors)}
                    />
                  </ExitField>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={runExitBacktest}
                    disabled={exitLoading}
                    leftIcon={exitLoading ? <RefreshCw size={14} className="animate-spin" /> : <TrendingUp size={14} />}
                  >
                    {exitLoading ? "Running..." : "Run Exit-Rule Backtest"}
                  </Button>
                  <span style={{ fontSize: 12, color: colors.muted }}>
                    Equal-weight sizing on $100,000; close-to-close, no slippage.
                  </span>
                </div>

                {exitError && (
                  <div style={{ padding: 16, textAlign: "center", color: colors.negative, fontSize: 13 }}>
                    <AlertCircle size={20} style={{ display: "block", margin: "0 auto 6px" }} />
                    {exitError}
                  </div>
                )}

                {exitData && !exitLoading && (
                  <div>
                    {exitData.warnings && exitData.warnings.length > 0 && (
                      <div
                        style={{
                          marginBottom: 12,
                          padding: "8px 12px",
                          border: `1px solid ${colors.border}`,
                          borderRadius: 6,
                          fontSize: 12,
                          color: colors.muted,
                        }}
                      >
                        {exitData.warnings.map((w, i) => (
                          <div key={i}>⚠ {w}</div>
                        ))}
                      </div>
                    )}

                    {/* Summary stats */}
                    <div
                      style={{
                        marginBottom: 12,
                        padding: "12px 14px",
                        borderRadius: 8,
                        border: `1px solid ${colors.border}`,
                        backgroundColor: isDarkMode ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.01)",
                      }}
                    >
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 24px", fontSize: 12 }}>
                        <StatRow label="Total Return" value={formatReturn(exitData.summary.total_return_pct)} positive={exitData.summary.total_return_pct >= 0} colors={colors} />
                        <StatRow label="Win Rate" value={`${exitData.summary.win_rate_pct.toFixed(1)}%`} positive={exitData.summary.win_rate_pct >= 50} colors={colors} />
                        <StatRow label="Sharpe" value={exitData.summary.sharpe.toFixed(2)} positive={exitData.summary.sharpe >= 0} colors={colors} />
                        <StatRow label="Profit Factor" value={exitData.summary.profit_factor === Infinity ? "∞" : exitData.summary.profit_factor.toFixed(2)} positive={exitData.summary.profit_factor >= 1} colors={colors} />
                        <StatRow label="Max Drawdown" value={`${exitData.summary.max_drawdown_pct.toFixed(1)}%`} positive={exitData.summary.max_drawdown_pct >= 0} colors={colors} />
                        <StatRow label="SPY Alpha" value={formatReturn(exitData.summary.total_return_pct - exitData.benchmark.spy_return_pct)} positive={exitData.summary.total_return_pct - exitData.benchmark.spy_return_pct >= 0} colors={colors} />
                        <StatRow label="Avg Holding" value={`${exitData.summary.avg_holding_days.toFixed(1)}d`} positive={true} colors={colors} />
                        <StatRow label="Trades" value={`${exitData.summary.n_trades} (${exitData.summary.n_winners}W/${exitData.summary.n_losers}L)`} positive={true} colors={colors} />
                      </div>
                    </div>

                    {/* Per-trade table */}
                    {exitData.per_trade.length > 0 ? (
                      <div style={{ overflowX: "auto" }}>
                        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                          <thead>
                            <tr>
                              {["Ticker", "Entry", "Exit", "Reason", "Days", "P&L $", "P&L %", "MFE", "MAE"].map((h) => (
                                <th
                                  key={h}
                                  style={{
                                    textAlign: h === "Ticker" || h === "Reason" ? "left" : "right",
                                    padding: "6px 10px",
                                    color: colors.subtle,
                                    fontWeight: 600,
                                    fontSize: 10,
                                    textTransform: "uppercase",
                                    borderBottom: `1px solid ${colors.border}`,
                                  }}
                                >
                                  {h}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {exitData.per_trade.map((t, idx) => {
                              const positive = t.pnl_pct >= 0;
                              return (
                                <tr
                                  key={t.ticker}
                                  style={{
                                    backgroundColor: idx % 2 === 1 ? colors.rowEven : "transparent",
                                  }}
                                >
                                  <td style={{ padding: "8px 10px", fontWeight: 600, color: colors.text }}>{t.ticker}</td>
                                  <td style={{ padding: "8px 10px", textAlign: "right", color: colors.text, fontVariantNumeric: "tabular-nums" }}>{t.entry_price.toFixed(2)}</td>
                                  <td style={{ padding: "8px 10px", textAlign: "right", color: colors.text, fontVariantNumeric: "tabular-nums" }}>{t.exit_price.toFixed(2)}</td>
                                  <td style={{ padding: "8px 10px", color: colors.muted, fontSize: 11 }}>{t.exit_reason}</td>
                                  <td style={{ padding: "8px 10px", textAlign: "right", color: colors.text, fontVariantNumeric: "tabular-nums" }}>{t.holding_days}</td>
                                  <td style={{ padding: "8px 10px", textAlign: "right", color: positive ? colors.positive : colors.negative, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{t.pnl_dollars.toFixed(0)}</td>
                                  <td style={{ padding: "8px 10px", textAlign: "right", color: positive ? colors.positive : colors.negative, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{(t.pnl_pct * 100).toFixed(2)}%</td>
                                  <td style={{ padding: "8px 10px", textAlign: "right", color: colors.muted, fontVariantNumeric: "tabular-nums" }}>{(t.mfe_pct * 100).toFixed(1)}%</td>
                                  <td style={{ padding: "8px 10px", textAlign: "right", color: colors.muted, fontVariantNumeric: "tabular-nums" }}>{(t.mae_pct * 100).toFixed(1)}%</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div style={{ padding: 16, textAlign: "center", color: colors.muted, fontSize: 13 }}>
                        No trades to display.
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// StatRow helper
// ---------------------------------------------------------------------------

function StatRow({
  label,
  value,
  positive,
  colors,
}: {
  label: string;
  value: string;
  positive: boolean;
  colors: Record<string, string>;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ color: colors.muted }}>{label}</span>
      <span style={{ fontWeight: 600, color: positive ? colors.positive : colors.negative, fontVariantNumeric: "tabular-nums" }}>
        {value}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exit-rule form helpers
// ---------------------------------------------------------------------------

function inputStyle(colors: Record<string, string>): React.CSSProperties {
  return {
    width: "100%",
    border: `1px solid ${colors.border}`,
    borderRadius: 6,
    padding: "4px 8px",
    fontSize: 12,
    background: colors.surface,
    color: colors.text,
  };
}

function ExitField({ label, colors, children }: { label: string; colors: Record<string, string>; children: React.ReactNode }) {
  return (
    <div>
      <label style={{ display: "block", fontSize: 10, color: colors.muted, marginBottom: 3, textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {label}
      </label>
      {children}
    </div>
  );
}
