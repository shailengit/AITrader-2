import { useEffect, useState, useRef, useMemo } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Play, RotateCcw, AlertCircle, TrendingUp, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import {
  strategyLabApi,
  type ExperimentRow,
} from "../../lib/strategyLab";
import { LiveActivity } from "./LiveActivity";

interface StepBacktestProps {
  strategyClassPath: string;
  onWinnerPicked: (experimentId: string) => void;
}

type WinnerMetric = "bear" | "mean";

function toNum(v: unknown): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const n = parseFloat(v);
    return isNaN(n) ? 0 : n;
  }
  return 0;
}

// BEAR-robust score: BEAR return per unit of drawdown risk. Mirrors the
// backend's existing sharpe_proxy convention (return / abs(drawdown)) but
// uses the BEAR-leg return specifically, so strategies that make money
// during bear regimes win. Falls back to raw BEAR return when drawdown is 0.
function bearRobustScore(r: ExperimentRow): number {
  const k = r.kpis || {};
  const bearRet = toNum(k.bear_return_pct);
  const dd = Math.abs(toNum(k.max_drawdown_pct));
  return dd > 0 ? bearRet / dd : bearRet;
}

// Mean (total-period) Sharpe, from the backend's annualized sharpe_ratio.
function meanSharpe(r: ExperimentRow): number {
  return toNum(r.kpis?.sharpe_ratio);
}

function scoreByMetric(r: ExperimentRow, metric: WinnerMetric): number {
  return metric === "bear" ? bearRobustScore(r) : meanSharpe(r);
}

const STORAGE_KEY_BATCH = "strategy_lab_active_batch";

function loadBatchState() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY_BATCH);
    if (!raw) return null;
    return JSON.parse(raw) as {
      batchId: string;
      strategyClassPath: string;
      nRuns: number;
      endDate: string;
      startDateMin: string;
      startDateMax: string;
    };
  } catch { return null; }
}

function saveBatchState(batchId: string, strategyClassPath: string, nRuns: number, endDate: string, startDateMin: string, startDateMax: string) {
  sessionStorage.setItem(STORAGE_KEY_BATCH, JSON.stringify({ batchId, strategyClassPath, nRuns, endDate, startDateMin, startDateMax }));
}

function clearBatchState() {
  sessionStorage.removeItem(STORAGE_KEY_BATCH);
}

export function StepBacktest({ strategyClassPath, onWinnerPicked }: StepBacktestProps) {
  const savedBatch = loadBatchState();
  const isResumed = savedBatch !== null && savedBatch.strategyClassPath === strategyClassPath;

  const [nRuns, setNRuns] = useState(isResumed ? savedBatch!.nRuns : 10);
  const [endDate, setEndDate] = useState(isResumed ? savedBatch!.endDate : "2026-06-01");
  const [startDateMin, setStartDateMin] = useState(isResumed ? savedBatch!.startDateMin : "2000-01-01");
  const [startDateMax, setStartDateMax] = useState(isResumed ? savedBatch!.startDateMax : "2020-01-01");
  const [batchId, setBatchId] = useState<string | null>(isResumed ? savedBatch!.batchId : null);
  const [experiments, setExperiments] = useState<ExperimentRow[]>([]);
  const [progress, setProgress] = useState(isResumed ? { completed: 0, total: savedBatch!.nRuns, failed: 0 } : { completed: 0, total: 0, failed: 0 });
  const [selectedWinner, setSelectedWinner] = useState<string | null>(null);
  const [equityExperimentId, setEquityExperimentId] = useState<string | null>(null);
  // When the batch first shows progress, record the wall-clock start so we
  // can estimate time remaining from the observed completion rate.
  const [batchStartTime, setBatchStartTime] = useState<number | null>(null);
  const [winnerMetric, setWinnerMetric] = useState<WinnerMetric>("bear");
  const winnerMetricRef = useRef<WinnerMetric>("bear");
  const hasAutoPicked = useRef(false);

  useEffect(() => { winnerMetricRef.current = winnerMetric; }, [winnerMetric]);

  const pickBest = (rows: ExperimentRow[], metric: WinnerMetric) => {
    const completed = rows.filter((r) => r.status === "completed");
    if (completed.length === 0) return;
    const best = completed.reduce((a, b) =>
      scoreByMetric(b, metric) > scoreByMetric(a, metric) ? b : a
    );
    setSelectedWinner(best.id);
    onWinnerPicked(best.id);
  };

  const equityCurve = useQuery({
    queryKey: ["equity-curve", equityExperimentId],
    queryFn: () => strategyLabApi.getEquityCurve(equityExperimentId!),
    enabled: !!equityExperimentId,
  });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const start = useMutation({
    mutationFn: () => strategyLabApi.startExperimentsWithClass(strategyClassPath, {
      n_runs: nRuns,
      end_date: endDate,
      start_date_min: startDateMin,
      start_date_max: startDateMax,
    }),
    onSuccess: (r) => {
      setBatchId(r.batch_id);
      setExperiments([]);
      setSelectedWinner(null);
      setProgress({ completed: 0, total: nRuns, failed: 0 });
      // Record the wall-clock start immediately so the ETA shows an
      // "estimating…" state during the initial (slower) data precompute,
      // then a rate-based estimate once runs begin completing.
      setBatchStartTime(Date.now());
      hasAutoPicked.current = false;
      saveBatchState(r.batch_id, strategyClassPath, nRuns, endDate, startDateMin, startDateMax);
    },
  });

  useEffect(() => {
    if (!batchId) return;
    const poll = async () => {
      try {
        const rows = await strategyLabApi.listBatchExperiments("_", batchId);
        setExperiments(rows);
        const completed = rows.filter((r) => r.status === "completed").length;
        const failed = rows.filter((r) => r.status === "failed").length;
        if (batchStartTime === null && (completed + failed) > 0) {
          setBatchStartTime(Date.now());
        }
        setProgress({ completed, total: nRuns, failed });
        if (completed + failed >= nRuns) {
          if (pollRef.current) clearInterval(pollRef.current);
          // Auto-select the default winner once the batch completes.
          if (!hasAutoPicked.current) {
            hasAutoPicked.current = true;
            pickBest(rows, winnerMetricRef.current);
          }
        }
      } catch {
        // ignore transient poll errors
      }
    };
    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [batchId, nRuns]);

  const isRunning = !!batchId && progress.completed + progress.failed < nRuns;
  const isDone = !!batchId && !isRunning;

  return (
    <>
      <div className="slab-page-head">
        <div>
          <div className="slab-eyebrow slab-eyebrow--gold">// 01 · Backtest</div>
          <h1 className="slab-page-head__title">Validate it.</h1>
          <p className="slab-page-head__lede">
            Run randomized as-of-date windows to see how the strategy holds
            up across regimes. Pick the best run, then deploy.
          </p>
        </div>
        <div className="slab-page-head__meta">
          <span>{strategyClassPath.split("/").pop()}</span>
          <span
            className={
              isRunning
                ? "slab-status slab-status--live"
                : isDone
                  ? "slab-status slab-status--terminal"
                  : "slab-status slab-status--dim"
            }
          >
            <span className="slab-status__dot" />
            {isRunning ? "RUNNING" : isDone ? "COMPLETE" : "IDLE"}
          </span>
        </div>
      </div>

      <div className="slab-page-body">
        {!batchId && (
          <ConfigForm
            nRuns={nRuns}
            setNRuns={setNRuns}
            endDate={endDate}
            setEndDate={setEndDate}
            startDateMin={startDateMin}
            setStartDateMin={setStartDateMin}
            startDateMax={startDateMax}
            setStartDateMax={setStartDateMax}
            onStart={() => start.mutate()}
            isStarting={start.isPending}
            error={start.error as Error | null}
          />
        )}

        {batchId && (
          <>
            {isResumed && (
              <div
                className="slab-panel"
                style={{ maxWidth: 1280, marginBottom: 16, borderColor: "var(--accent)" }}
              >
                <div style={{ padding: "8px 16px", display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ color: "var(--accent)", fontSize: 13 }}>⏺</span>
                  <span className="slab-mono slab-mono--sm" style={{ color: "var(--accent)" }}>
                    Resumed — batch is running in the background
                  </span>
                </div>
              </div>
            )}
            <LiveTicker
              completed={progress.completed}
              total={progress.total}
              failed={progress.failed}
              isRunning={isRunning}
              batchId={batchId}
              startTime={batchStartTime}
            />

            <LiveActivity
              rows={experiments}
              nRuns={nRuns}
              isRunning={isRunning}
              winnerMetric={winnerMetric}
            />

            {isDone && progress.failed > 0 && progress.completed === 0 && (
              <div
                className="slab-panel"
                style={{ maxWidth: 1280, marginTop: 16, borderColor: "var(--bad)", backgroundColor: "color-mix(in srgb, var(--bad) 8%, transparent)" }}
              >
                <div style={{ padding: 16, display: "flex", alignItems: "flex-start", gap: 12 }}>
                  <AlertCircle size={18} style={{ color: "var(--bad)", flexShrink: 0, marginTop: 2 }} />
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 14, color: "var(--bad)", marginBottom: 4 }}>
                      All {progress.total} experiments failed
                    </div>
                    <p style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.5 }}>
                      Every run returned an error. Check the error messages in the Status column for details.
                      Use the terminal to debug the strategy with Claude Code.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {experiments.length > 0 && (
              <ExperimentTable
                rows={experiments}
                selectedWinner={selectedWinner}
                onPick={(id) => {
                  setSelectedWinner(id);
                  onWinnerPicked(id);
                }}
                onShowEquity={(id) => setEquityExperimentId(id)}
                winnerMetric={winnerMetric}
                onChangeMetric={(m) => {
                  setWinnerMetric(m);
                  // Re-select the default winner for the newly chosen metric.
                  pickBest(experiments, m);
                }}
              />
            )}

            {equityCurve.data && equityCurve.data.equity_curve.length > 0 && (
              <div className="slab-panel" style={{ maxWidth: 1280, marginTop: 16 }}>
                <div className="slab-panel__head">
                  <span className="slab-eyebrow slab-eyebrow--gold">
                    <TrendingUp size={11} style={{ verticalAlign: "middle", marginRight: 6 }} />
                    Equity Curve
                  </span>
                  <button
                    type="button"
                    onClick={() => setEquityExperimentId(null)}
                    className="slab-btn slab-btn--xs slab-btn--ghost"
                  >
                    Close
                  </button>
                </div>
                <div style={{ padding: 16 }}>
                  <svg viewBox="0 0 800 240" style={{ width: "100%", height: 240 }}>
                    {(() => {
                      const pts = equityCurve.data.equity_curve;
                      const values = pts.map((p: any) => p.value);
                      const min = Math.min(...values);
                      const max = Math.max(...values);
                      const range = max - min || 1;
                      const w = 800;
                      const h = 220;
                      const pad = 10;
                      const path = pts
                        .map((p: any, i: number) => {
                          const x = pad + (i / (pts.length - 1)) * (w - 2 * pad);
                          const y = pad + h - ((p.value - min) / range) * (h - 2 * pad);
                          return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
                        })
                        .join(" ");
                      const color = values[values.length - 1] >= values[0] ? "var(--good)" : "var(--bad)";
                      return <path d={path} fill="none" stroke={color} strokeWidth={2} />;
                    })()}
                  </svg>
                </div>
              </div>
            )}

            {isDone && (
              <div style={{ maxWidth: 1280, marginTop: 24, display: "flex", gap: 12 }}>
                <button
                  type="button"
                  onClick={() => { clearBatchState(); setBatchId(null); }}
                  className="slab-btn"
                >
                  <RotateCcw size={11} />
                  New batch
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

// ── Configuration form ─────────────────────────────────────────────────
function ConfigForm(props: {
  nRuns: number; setNRuns: (n: number) => void;
  endDate: string; setEndDate: (s: string) => void;
  startDateMin: string; setStartDateMin: (s: string) => void;
  startDateMax: string; setStartDateMax: (s: string) => void;
  onStart: () => void; isStarting: boolean; error: Error | null;
}) {
  return (
    <div style={{ maxWidth: 920 }}>
      <div
        className="slab-eyebrow"
        style={{ marginBottom: 16, color: "var(--subtle)" }}
      >
        // Batch parameters
      </div>
      <div className="slab-grid-4">
        <div className="slab-field">
          <label className="slab-field__label">Runs</label>
          <input
            type="number"
            min={1}
            max={500}
            value={props.nRuns}
            onChange={(e) => props.setNRuns(Math.max(1, Math.min(500, parseInt(e.target.value) || 1)))}
            className="slab-input"
            style={{ fontSize: 16 }}
          />
        </div>
        <div className="slab-field">
          <label className="slab-field__label">End date</label>
          <input
            type="date"
            value={props.endDate}
            onChange={(e) => props.setEndDate(e.target.value)}
            className="slab-input"
          />
        </div>
        <div className="slab-field">
          <label className="slab-field__label">Start min</label>
          <input
            type="date"
            value={props.startDateMin}
            onChange={(e) => props.setStartDateMin(e.target.value)}
            className="slab-input"
          />
        </div>
        <div className="slab-field">
          <label className="slab-field__label">Start max</label>
          <input
            type="date"
            value={props.startDateMax}
            onChange={(e) => props.setStartDateMax(e.target.value)}
            className="slab-input"
          />
        </div>
      </div>

      <div style={{ marginTop: 28, display: "flex", alignItems: "center", gap: 16 }}>
        <button
          type="button"
          onClick={props.onStart}
          disabled={props.isStarting}
          className="slab-btn slab-btn--terminal"
          style={{ padding: "12px 24px" }}
        >
          <Play size={12} fill="currentColor" />
          {props.isStarting ? "Starting…" : `Start ${props.nRuns}-run batch`}
        </button>
        {props.error && (
          <span className="slab-mono slab-mono--sm slab-mono--rose" style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <AlertCircle size={12} />
            {String(props.error?.message ?? "Failed to start")}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Live ticker ──────────────────────────────────────────────────────
function formatEta(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return "estimating…";
  const s = Math.round(seconds);
  if (s < 60) return `~${s}s left`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r > 0 ? `~${m}m ${r}s left` : `~${m}m left`;
}

function LiveTicker({ completed, total, failed, isRunning, batchId, startTime }: {
  completed: number; total: number; failed: number; isRunning: boolean; batchId: string;
  startTime: number | null;
}) {
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  // Estimate time remaining from the observed completion rate. The first
  // run includes data precompute (slower), so the estimate is conservative
  // early and refines as runs complete. Earlier start dates mean more data
  // to precompute, which the observed rate naturally accounts for.
  const done = completed + failed;
  const remaining = total - done;
  let etaLabel: string | null = null;
  if (isRunning && startTime != null) {
    const elapsedSec = (Date.now() - startTime) / 1000;
    const rate = elapsedSec > 0 ? done / elapsedSec : 0; // runs per second
    if (rate > 0 && remaining > 0) {
      etaLabel = formatEta(remaining / rate);
    } else if (done === 0) {
      etaLabel = "estimating…";
    }
  }

  return (
    <div className="slab-panel" style={{ maxWidth: 1280 }}>
      <div className="slab-panel__head">
        <span className="slab-eyebrow slab-eyebrow--gold">// Live</span>
        <span className="slab-mono slab-mono--xs slab-mono--dim">batch · {batchId.slice(0, 8)}</span>
      </div>
      <div style={{ padding: 24, display: "grid", gridTemplateColumns: "repeat(3, 1fr) auto", gap: 32, alignItems: "center" }}>
        <div>
          <div className="slab-ticker__label">Completed</div>
          <div className="slab-ticker">
            <span className="slab-ticker--gold">{String(completed).padStart(3, "0")}</span>
            <span className="slab-mono slab-mono--lg slab-mono--faint">/{total}</span>
          </div>
        </div>
        <div>
          <div className="slab-ticker__label">Failed</div>
          <div className="slab-ticker">
            <span style={{ color: failed > 0 ? "var(--bad)" : "var(--subtle)" }}>
              {String(failed).padStart(3, "0")}
            </span>
          </div>
        </div>
        <div>
          <div className="slab-ticker__label">Progress</div>
          <div className="slab-ticker">
            {String(pct).padStart(2, "0")}<span className="slab-mono slab-mono--lg slab-mono--faint">%</span>
          </div>
        </div>
        <div>
          <span className={isRunning ? "slab-status slab-status--live" : "slab-status slab-status--terminal"}>
            <span className="slab-status__dot" />
            {isRunning ? "Running" : "Complete"}
          </span>
          {isRunning && etaLabel && (
            <div className="slab-mono slab-mono--xs slab-mono--dim" style={{ marginTop: 6, whiteSpace: "nowrap" }}>
              {etaLabel} · {done}/{total} done
            </div>
          )}
        </div>
      </div>
      <div style={{ height: 2, background: "var(--border)" }}>
        <motion.div
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.4 }}
          style={{
            height: "100%",
            background: isRunning ? "var(--accent)" : "var(--good)",
            boxShadow: isRunning ? "0 0 12px var(--accent-glow)" : "none",
          }}
        />
      </div>
    </div>
  );
}

// ── Experiments table ────────────────────────────────────────────────
type SortKey = "run_index" | "start_date" | "total_return_pct" | "alpha_pct" | "win_rate" | "cagr_pct" | "sharpe_ratio" | "total_trades" | "bull_return_pct" | "bear_return_pct";
type SortDir = "asc" | "desc";

function ExperimentTable({ rows, selectedWinner, onPick, onShowEquity, winnerMetric, onChangeMetric }: {
  rows: ExperimentRow[]; selectedWinner: string | null;
  onPick: (id: string) => void;
  onShowEquity: (id: string) => void;
  winnerMetric: WinnerMetric;
  onChangeMetric: (m: WinnerMetric) => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("run_index");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sorted = useMemo(() => {
    const copy = [...rows];
    const k = sortKey;
    const d = sortDir;
    copy.sort((a, b) => {
      let va: any, vb: any;
      if (k === "run_index") { va = a.run_index; vb = b.run_index; }
      else if (k === "start_date") { va = a.start_date || ""; vb = b.start_date || ""; }
      else { va = a.kpis?.[k]; vb = b.kpis?.[k]; }
      if (va == null) va = k === "run_index" ? 9999 : -999999;
      if (vb == null) vb = k === "run_index" ? 9999 : -999999;
      return d === "asc" ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  const SortIcon = ({ columnKey }: { columnKey: SortKey }) => {
    if (sortKey !== columnKey) return <ArrowUpDown size={10} style={{ opacity: 0.3, verticalAlign: "middle", marginLeft: 4 }} />;
    return sortDir === "asc"
      ? <ArrowUp size={10} style={{ verticalAlign: "middle", marginLeft: 4 }} />
      : <ArrowDown size={10} style={{ verticalAlign: "middle", marginLeft: 4 }} />;
  };

  const Th = ({ columnKey, children }: { columnKey: SortKey; children: React.ReactNode }) => (
    <th className="slab-table__num" onClick={() => handleSort(columnKey)} style={{ cursor: "pointer", userSelect: "none" }}>
      {children}<SortIcon columnKey={columnKey} />
    </th>
  );

  return (
    <div className="slab-panel" style={{ maxWidth: 1280, marginTop: 24 }}>
      <div className="slab-panel__head">
        <span className="slab-eyebrow slab-eyebrow--gold">// Runs</span>
        <span className="slab-mono slab-mono--xs slab-mono--dim">
          click <span style={{ color: "var(--accent)" }}>pick</span> to mark the winner · click <span style={{ color: "var(--accent)" }}>chart</span> for equity curve
        </span>
        <span style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
          <span className="slab-mono slab-mono--xs slab-mono--dim" style={{ alignSelf: "center", marginRight: 4 }}>
            default winner
          </span>
          <button
            type="button"
            onClick={() => onChangeMetric("bear")}
            className={`slab-btn slab-btn--xs ${winnerMetric === "bear" ? "slab-btn--primary" : "slab-btn--ghost"}`}
            title="Pick the run with the best BEAR-robust Sharpe (BEAR return per unit of drawdown)"
          >
            BEAR-robust
          </button>
          <button
            type="button"
            onClick={() => onChangeMetric("mean")}
            className={`slab-btn slab-btn--xs ${winnerMetric === "mean" ? "slab-btn--primary" : "slab-btn--ghost"}`}
            title="Pick the run with the best mean (total-period) Sharpe"
          >
            Mean Sharpe
          </button>
        </span>
      </div>
      <div style={{ maxHeight: 480, overflow: "auto" }}>
        <table className="slab-table">
          <thead>
            <tr>
              <th onClick={() => handleSort("run_index")} style={{ cursor: "pointer" }}>
                #<SortIcon columnKey="run_index" />
              </th>
              <th onClick={() => handleSort("start_date")} style={{ cursor: "pointer" }}>
                Start<SortIcon columnKey="start_date" />
              </th>
              <Th columnKey="total_return_pct">Return</Th>
              <Th columnKey="alpha_pct">Alpha</Th>
              <Th columnKey="win_rate">Win%</Th>
              <Th columnKey="cagr_pct">CAGR%</Th>
              <Th columnKey="total_trades">Trades</Th>
              <Th columnKey="sharpe_ratio">Sharpe</Th>
              <Th columnKey="bull_return_pct">BULL%</Th>
              <Th columnKey="bear_return_pct">BEAR%</Th>
              <th>Status</th>
              <th></th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <ExperimentRowView
                key={row.id}
                row={row}
                isSelected={selectedWinner === row.id}
                onPick={() => onPick(row.id)}
                onShowEquity={() => onShowEquity(row.id)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ExperimentRowView({ row, isSelected, onPick, onShowEquity }: {
  row: ExperimentRow; isSelected: boolean; onPick: () => void; onShowEquity: () => void;
}) {
  const k = row.kpis;
  const ret = k?.total_return_pct;
  return (
    <tr className={isSelected ? "slab-table__row--selected" : ""}>
      <td>{String(row.run_index).padStart(3, "0")}</td>
      <td>{row.start_date?.slice(0, 10) ?? "—"}</td>
      <td className="slab-table__num" style={{ color: ret != null && ret >= 0 ? "var(--good)" : "var(--bad)" }}>
        {ret != null ? `${ret >= 0 ? "+" : ""}${ret.toFixed(1)}%` : "—"}
      </td>
      <td className="slab-table__num">{k?.alpha_pct != null ? `${k.alpha_pct >= 0 ? "+" : ""}${k.alpha_pct.toFixed(1)}%` : "—"}</td>
      <td className="slab-table__num">{k?.win_rate != null ? `${k.win_rate.toFixed(1)}%` : "—"}</td>
      <td className="slab-table__num">{k?.cagr_pct != null ? `${k.cagr_pct.toFixed(1)}%` : "—"}</td>
      <td className="slab-table__num">{k?.total_trades ?? "—"}</td>
      <td className="slab-table__num">{k?.sharpe_ratio != null ? k.sharpe_ratio.toFixed(2) : "—"}</td>
      <td
        className="slab-table__num"
        style={{ color: k?.bull_return_pct != null && k.bull_return_pct >= 0 ? "var(--good)" : "var(--bad)" }}
      >
        {k?.bull_return_pct != null ? `${k.bull_return_pct >= 0 ? "+" : ""}${k.bull_return_pct.toFixed(1)}%` : "—"}
      </td>
      <td
        className="slab-table__num"
        style={{ color: k?.bear_return_pct != null && k.bear_return_pct >= 0 ? "var(--good)" : "var(--bad)" }}
      >
        {k?.bear_return_pct != null ? `${k.bear_return_pct >= 0 ? "+" : ""}${k.bear_return_pct.toFixed(1)}%` : "—"}
      </td>
      <td>
        {row.status === "completed" ? (
          <span className="slab-tag slab-tag--terminal">OK</span>
        ) : (
          <span className="slab-tag slab-tag--rose" title={row.error_message ?? ""}>
            FAIL
            {row.error_message && (
              <span style={{ display: "block", fontSize: 10, fontWeight: 400, marginTop: 2, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {row.error_message}
              </span>
            )}
          </span>
        )}
      </td>
      <td>
        {row.status === "completed" && (
          <button
            type="button"
            onClick={onShowEquity}
            className="slab-btn slab-btn--xs slab-btn--ghost"
            title="Show equity curve"
          >
            <TrendingUp size={11} />
          </button>
        )}
      </td>
      <td>
        {row.status === "completed" && (
          <button
            type="button"
            onClick={onPick}
            className={`slab-btn slab-btn--xs ${isSelected ? "slab-btn--primary" : ""}`}
          >
            {isSelected ? "✓ Winner" : "Pick"}
          </button>
        )}
      </td>
    </tr>
  );
}
