import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { strategyLabApi, type ExperimentRow } from "../../lib/strategyLab";

/* ------------------------------------------------------------------ *
 * Live Activity — keeps the user engaged while a backtest batch runs.
 * All data comes from the existing 2s poll of listBatchExperiments:
 *   A. "Now processing" — which window is currently being crunched
 *   B. Live leaderboard — completed runs ranked by the winner metric
 *   C. Leader equity curve — the current champion's curve, live
 *   D. Distribution stats — best / median / worst return so far
 *   E. Progress timeline — the n_runs windows, done/running/pending
 *   F. Live trades — top winners/losers aggregated across completed runs
 * ------------------------------------------------------------------ */

function toNum(v: unknown): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") { const n = parseFloat(v); return isNaN(n) ? 0 : n; }
  return 0;
}
function bearRobustScore(r: ExperimentRow): number {
  const k = r.kpis || {};
  const bearRet = toNum(k.bear_return_pct);
  const dd = Math.abs(toNum(k.max_drawdown_pct));
  return dd > 0 ? bearRet / dd : bearRet;
}
function meanSharpe(r: ExperimentRow): number { return toNum(r.kpis?.sharpe_ratio); }
function score(r: ExperimentRow, metric: "bear" | "mean"): number {
  return metric === "bear" ? bearRobustScore(r) : meanSharpe(r);
}
function fmtMoney(n: number): string {
  const s = n >= 0 ? "+" : "−";
  return s + "$" + Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}
function fmtPct(n: number): string { return (n >= 0 ? "+" : "") + n.toFixed(1) + "%"; }

interface Trade { ticker: string; return_pct: number; pnl_dollars: number; exit_reason: string; run: number; }

export function LiveActivity({ rows, nRuns, isRunning, winnerMetric }: {
  rows: ExperimentRow[]; nRuns: number; isRunning: boolean; winnerMetric: "bear" | "mean";
}) {
  const completed = useMemo(() => rows.filter((r) => r.status === "completed"), [rows]);
  const running = useMemo(() => rows.find((r) => r.status === "running"), [rows]);
  const failed = rows.filter((r) => r.status === "failed").length;

  // A — now processing
  const nowProcessing = running
    ? `Run ${(running.run_index ?? 0) + 1}/${nRuns} · ${(running.start_date ?? "…").slice(0, 10)} window`
    : null;

  // B — leaderboard
  const ranked = useMemo(
    () => [...completed].sort((a, b) => score(b, winnerMetric) - score(a, winnerMetric)),
    [completed, winnerMetric],
  );
  const leader = ranked[0];

  // C — leader equity curve
  const leaderCurve = useQuery({
    queryKey: ["leader-equity", leader?.id],
    queryFn: () => strategyLabApi.getEquityCurve(leader!.id),
    enabled: !!leader,
  });
  const curve = leaderCurve.data?.equity_curve ?? [];

  // D — distribution
  const returns = useMemo(
    () => completed.map((r) => toNum(r.kpis?.total_return_pct)).filter((v) => isFinite(v)),
    [completed],
  );
  const best = returns.length ? Math.max(...returns) : null;
  const worst = returns.length ? Math.min(...returns) : null;
  const median = (() => {
    if (!returns.length) return null;
    const s = [...returns].sort((a, b) => a - b);
    const mid = Math.floor(s.length / 2);
    return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
  })();

  // F — live trades (aggregate top winners/losers across completed runs)
  const trades = useMemo(() => {
    const map = new Map<string, Trade>();
    for (const r of completed) {
      const k = r.kpis || {};
      const items: Array<{ ticker: string; return_pct: number; pnl_dollars: number; exit_reason: string }> = [
        ...(k.top_winners || []), ...(k.top_losers || []),
      ];
      for (const t of items) {
        const key = t.ticker || "?";
        const cur = map.get(key) || { ticker: key, return_pct: 0, pnl_dollars: 0, exit_reason: "", run: r.run_index ?? 0 };
        cur.pnl_dollars += toNum(t.pnl_dollars);
        cur.return_pct = toNum(t.return_pct);
        cur.exit_reason = t.exit_reason || cur.exit_reason;
        map.set(key, cur);
      }
    }
    return [...map.values()].sort((a, b) => Math.abs(b.pnl_dollars) - Math.abs(a.pnl_dollars)).slice(0, 8);
  }, [completed]);

  // E — progress timeline
  const timeline = useMemo(() => {
    const arr: Array<{ idx: number; status: string }> = [];
    for (let i = 0; i < nRuns; i++) {
      const row = rows.find((r) => (r.run_index ?? 0) === i);
      arr.push({ idx: i, status: row ? row.status : "pending" });
    }
    return arr;
  }, [rows, nRuns]);

  const done = completed.length + failed;

  return (
    <div className="slab-panel" style={{ maxWidth: 1280, marginTop: 16 }}>
      <div className="slab-panel__head">
        <span className="slab-eyebrow slab-eyebrow--gold">// Live Activity</span>
        <span className="slab-mono slab-mono--xs slab-mono--dim">{done}/{nRuns} done</span>
      </div>
      <div style={{ padding: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>

        {/* Left column */}
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {/* A — now processing */}
          <div>
            <div className="slab-ticker__label">Now processing</div>
            <div className="slab-mono slab-mono--md" style={{ color: "var(--accent)", marginTop: 4 }}>
              {isRunning ? (nowProcessing ?? "precomputing signals…") : "batch complete"}
            </div>
          </div>

          {/* D — distribution */}
          <div>
            <div className="slab-ticker__label">Return distribution (so far)</div>
            <div style={{ display: "flex", gap: 24, marginTop: 8 }}>
              <Dist label="Best" value={best != null ? fmtPct(best) : "—"} color="var(--good)" />
              <Dist label="Median" value={median != null ? fmtPct(median) : "—"} color="var(--foreground)" />
              <Dist label="Worst" value={worst != null ? fmtPct(worst) : "—"} color="var(--bad)" />
            </div>
          </div>

          {/* E — progress timeline */}
          <div>
            <div className="slab-ticker__label">Batch timeline</div>
            <div style={{ display: "flex", gap: 3, marginTop: 8, flexWrap: "wrap" }}>
              {timeline.map((t) => (
                <div
                  key={t.idx}
                  title={`Run ${t.idx + 1}: ${t.status}`}
                  style={{
                    width: 14, height: 14, borderRadius: 3,
                    background:
                      t.status === "completed" ? "var(--good)"
                      : t.status === "running" ? "var(--accent)"
                      : t.status === "failed" ? "var(--bad)"
                      : "var(--surface-overlay)",
                    boxShadow: t.status === "running" ? "0 0 8px var(--accent-glow)" : "none",
                  }}
                />
              ))}
            </div>
          </div>

          {/* F — live trades */}
          <div>
            <div className="slab-ticker__label">Top trades (aggregated)</div>
            {trades.length === 0 ? (
              <div className="slab-mono slab-mono--xs slab-mono--faint" style={{ marginTop: 6 }}>
                No completed trades yet.
              </div>
            ) : (
              <div style={{ marginTop: 6 }}>
                {trades.map((t) => (
                  <div key={t.ticker} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
                    <span className="slab-mono slab-mono--sm" style={{ fontWeight: 600 }}>{t.ticker}</span>
                    <span className="slab-mono slab-mono--xs slab-mono--faint">{t.exit_reason || "—"}</span>
                    <span className="slab-mono slab-mono--sm" style={{ color: t.pnl_dollars >= 0 ? "var(--good)" : "var(--bad)" }}>
                      {fmtMoney(t.pnl_dollars)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right column — leaderboard + leader equity curve */}
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {/* B — leaderboard */}
          <div>
            <div className="slab-ticker__label">Live leaderboard</div>
            {ranked.length === 0 ? (
              <div className="slab-mono slab-mono--xs slab-mono--faint" style={{ marginTop: 6 }}>
                Waiting for the first run to complete…
              </div>
            ) : (
              <div style={{ marginTop: 6 }}>
                {ranked.slice(0, 5).map((r, i) => (
                  <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
                    <span className="slab-mono slab-mono--xs" style={{ color: i === 0 ? "var(--accent)" : "var(--subtle)", width: 16 }}>{i + 1}</span>
                    <span className="slab-mono slab-mono--sm" style={{ flex: 1, color: i === 0 ? "var(--accent)" : "var(--foreground)" }}>
                      {i === 0 ? "★ " : ""}Run {(r.run_index ?? 0) + 1}
                    </span>
                    <span className="slab-mono slab-mono--xs slab-mono--faint">{fmtPct(toNum(r.kpis?.total_return_pct))}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* C — leader equity curve */}
          <div>
            <div className="slab-ticker__label">Leader equity curve</div>
            {curve.length === 0 ? (
              <div className="slab-mono slab-mono--xs slab-mono--faint" style={{ marginTop: 6 }}>
                {leader ? "Loading curve…" : "No leader yet."}
              </div>
            ) : (
              <EquitySparkline data={curve} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Dist({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div className="slab-mono slab-mono--xs slab-mono--faint">{label}</div>
      <div className="slab-mono slab-mono--lg" style={{ color, marginTop: 2 }}>{value}</div>
    </div>
  );
}

function EquitySparkline({ data }: { data: Array<{ date: string; value: number }> }) {
  const w = 420, h = 120, pad = 6;
  const vals = data.map((d) => d.value);
  const min = Math.min(...vals), max = Math.max(...vals);
  const range = max - min || 1;
  const pts = vals.map((v, i) => {
    const x = pad + (i / (vals.length - 1 || 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const line = pts.join(" ");
  const area = `${pad},${h - pad} ${line} ${w - pad},${h - pad}`;
  const up = vals[vals.length - 1] >= vals[0];
  const color = up ? "var(--good)" : "var(--bad)";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: 120, display: "block" }}>
      <polygon points={area} fill={color} opacity={0.12} />
      <polyline points={line} fill="none" stroke={color} strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
