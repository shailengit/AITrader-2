import { useState, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen, Code, ArrowUpDown,
  ArrowUp, ArrowDown, CheckCircle, XCircle, Play, Trash2,
} from "lucide-react";
import { strategyLabApi } from "../../lib/strategyLab";
import { useActiveBatch } from "../../hooks/useActiveBatch";
import { StrategyCoachBadge } from "../../components/shared/StrategyCoachBadge";

interface StrategyClassItem {
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

interface StepLibraryProps {
  onSelectStrategy: (path: string) => void;
}

type SortKey = "name" | "created_at" | "cagr_pct" | "sharpe_ratio" | "total_return_pct" | "win_rate" | "total_trades" | "last_backtest" | "deployed";
type SortDir = "asc" | "desc";

export function StepLibrary({ onSelectStrategy }: StepLibraryProps) {
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const qc = useQueryClient();
  const activeBatch = useActiveBatch();

  const { data: classes, isLoading } = useQuery({
    queryKey: ["strategy-classes"],
    queryFn: () => strategyLabApi.listStrategyClasses(),
  });

  const deleteMut = useMutation({
    mutationFn: (path: string) => strategyLabApi.deleteStrategyClass(path),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategy-classes"] });
      setConfirmDelete(null);
    },
  });

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sorted = useMemo(() => {
    if (!classes) return [];
    const copy = [...classes];
    copy.sort((a, b) => {
      let va: any, vb: any;
      if (keyIsString(sortKey)) {
        va = (a as any)[sortKey] || "";
        vb = (b as any)[sortKey] || "";
      } else {
        va = (a as any)[sortKey];
        vb = (b as any)[sortKey];
        if (va == null) va = sortKey === "deployed" ? false : -999999;
        if (vb == null) vb = sortKey === "deployed" ? false : -999999;
      }
      return sortDir === "asc" ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
    });
    return copy;
  }, [classes, sortKey, sortDir]);

  const SortIcon = ({ columnKey }: { columnKey: SortKey }) => {
    if (sortKey !== columnKey) return <ArrowUpDown size={10} style={{ opacity: 0.3, verticalAlign: "middle", marginLeft: 4 }} />;
    return sortDir === "asc"
      ? <ArrowUp size={10} style={{ verticalAlign: "middle", marginLeft: 4 }} />
      : <ArrowDown size={10} style={{ verticalAlign: "middle", marginLeft: 4 }} />;
  };

  const Th = ({ columnKey, children, className }: { columnKey: SortKey; children: React.ReactNode; className?: string }) => (
    <th onClick={() => handleSort(columnKey)} style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }} className={className}>
      {children}<SortIcon columnKey={columnKey} />
    </th>
  );

  return (
    <>
      <div className="slab-page-head">
        <div>
          <div className="slab-eyebrow slab-eyebrow--gold">// Library</div>
          <h1 className="slab-page-head__title">Strategy library.</h1>
          <p className="slab-page-head__lede">
            Select a strategy to backtest and deploy. To create a new strategy,
            open the <span style={{ color: "var(--accent)" }}>terminal</span> and describe your idea to Claude Code.
          </p>
        </div>
        <div className="slab-page-head__meta">
          <span>{classes?.length ?? 0} strategies</span>
          <span className="slab-mono slab-mono--gold">LIBRARY</span>
        </div>
      </div>

      <div className="slab-page-body">
        {isLoading && (
          <div className="slab-mono slab-mono--sm slab-mono--dim">Loading strategies…</div>
        )}

        {classes && classes.length === 0 && (
          <div style={{ textAlign: "center", padding: "64px 16px", color: "var(--subtle)" }}>
            <BookOpen size={32} style={{ marginBottom: 12, opacity: 0.3 }} />
            <p className="slab-prose" style={{ fontSize: 14 }}>
              No strategies found. Open the terminal and use Claude Code to generate one.
            </p>
          </div>
        )}

        {classes && classes.length > 0 && (
          <div className="slab-panel" style={{ maxWidth: 1400 }}>
            <div style={{ maxHeight: 600, overflow: "auto" }}>
              <table className="slab-table">
                <thead>
                  <tr>
                    <Th columnKey="name">Strategy</Th>
                    <Th columnKey="created_at">Created</Th>
                    <Th columnKey="cagr_pct">CAGR%</Th>
                    <Th columnKey="sharpe_ratio">Sharpe</Th>
                    <Th columnKey="total_return_pct">Return</Th>
                    <Th columnKey="win_rate">Win%</Th>
                    <Th columnKey="total_trades">Trades</Th>
                    <Th columnKey="last_backtest">Last Test</Th>
                    <Th columnKey="deployed">Status</Th>
                    <th style={{ textAlign: "center" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((c) => (
                    <StrategyRow
                      key={c.path}
                      entry={c}
                      onBacktest={() => onSelectStrategy(c.path)}
                      onDelete={() => setConfirmDelete(c.path)}
                      isDeleting={deleteMut.isPending && confirmDelete === c.path}
                      running={
                        activeBatch.batch?.strategyClassPath === c.path
                          ? {
                              isRunning: activeBatch.isRunning,
                              completed: activeBatch.completed,
                              failed: activeBatch.failed,
                              total: activeBatch.total,
                              tradesSoFar: activeBatch.tradesSoFar,
                            }
                          : null
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Delete confirmation modal */}
        {confirmDelete && (
          <div
            style={{
              position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
              display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50,
            }}
            onClick={() => setConfirmDelete(null)}
          >
            <div
              className="slab-panel"
              style={{ maxWidth: 440, width: "100%" }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="slab-panel__head">
                <span className="slab-eyebrow slab-eyebrow--gold">// Confirm delete</span>
              </div>
              <div className="slab-panel__body" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <p className="slab-prose">
                  Delete <span className="slab-mono" style={{ color: "var(--accent)" }}>{confirmDelete.split("/").pop()}</span>?
                  This will remove the strategy file and its performance data.
                </p>
                <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                  <button type="button" onClick={() => setConfirmDelete(null)} className="slab-btn">
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteMut.mutate(confirmDelete)}
                    disabled={deleteMut.isPending}
                    className="slab-btn"
                    style={{ borderColor: "var(--bad)", color: "var(--bad)" }}
                  >
                    {deleteMut.isPending ? "Deleting…" : "Delete"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function keyIsString(key: SortKey): boolean {
  return key === "name" || key === "created_at" || key === "last_backtest";
}

interface RunningInfo {
  isRunning: boolean; completed: number; failed: number; total: number; tradesSoFar: number;
}

function StrategyRow({ entry, onBacktest, onDelete, isDeleting, running }: {
  entry: StrategyClassItem; onBacktest: () => void;
  onDelete: () => void; isDeleting: boolean;
  running: RunningInfo | null;
}) {
  const fmtPct = (v: number | null) => {
    if (v == null) return <span className="slab-mono slab-mono--xs slab-mono--faint">N/A</span>;
    const isNeg = v < 0;
    return (
      <span className="slab-mono slab-mono--sm" style={{ color: isNeg ? "var(--bad)" : "var(--good)" }}>
        {v >= 0 ? "+" : ""}{v.toFixed(1)}%
      </span>
    );
  };

  const fmtNum = (v: number | null) => {
    if (v == null) return <span className="slab-mono slab-mono--xs slab-mono--faint">N/A</span>;
    return <span className="slab-mono slab-mono--sm">{v.toLocaleString()}</span>;
  };

  const fmtDate = (v: string | null) => {
    if (!v) return <span className="slab-mono slab-mono--xs slab-mono--faint">—</span>;
    return <span className="slab-mono slab-mono--xs slab-mono--dim">{v.slice(0, 10)}</span>;
  };

  return (
    <tr>
      <td>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Code size={12} style={{ color: "var(--accent)", flexShrink: 0 }} />
          <div>
            <div className="slab-mono slab-mono--sm" style={{ fontWeight: 600, color: "var(--accent)" }}>
              {entry.name}
            </div>
            {entry.description && (
              <div className="slab-mono slab-mono--xs slab-mono--faint" style={{ marginTop: 2, maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {entry.description}
              </div>
            )}
            <StrategyCoachBadge strategyPath={(entry.path.split("/services/")[1] ?? entry.path)} />
          </div>
        </div>
      </td>
      <td>{fmtDate(entry.created_at)}</td>
      <td className="slab-table__num">{fmtPct(entry.cagr_pct)}</td>
      <td className="slab-table__num">
        {entry.sharpe_ratio != null ? (
          <span className="slab-mono slab-mono--sm" style={{ color: entry.sharpe_ratio >= 0.5 ? "var(--good)" : entry.sharpe_ratio >= 0 ? "var(--accent-dark)" : "var(--bad)" }}>
            {entry.sharpe_ratio.toFixed(2)}
          </span>
        ) : (
          <span className="slab-mono slab-mono--xs slab-mono--faint">N/A</span>
        )}
      </td>
      <td className="slab-table__num">{fmtPct(entry.total_return_pct)}</td>
      <td className="slab-table__num">{fmtPct(entry.win_rate)}</td>
      <td className="slab-table__num">{fmtNum(entry.total_trades)}</td>
      <td>{fmtDate(entry.last_backtest)}</td>
      <td>
        {running ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span
              className="slab-tag slab-tag--gold"
              style={{
                display: "inline-flex", alignItems: "center", gap: 5, width: "fit-content",
                borderColor: "var(--accent)", color: "var(--accent)",
                animation: running.isRunning ? "slab-pulse 1.5s ease-in-out infinite" : "none",
              }}
              title={running.isRunning ? "Running in the background" : "Batch complete"}
            >
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--accent)" }} />
              {running.isRunning ? "BACKTESTING" : "COMPLETE"}
            </span>
            <span className="slab-mono slab-mono--xs slab-mono--dim">
              {running.completed + running.failed}/{running.total} runs · {running.tradesSoFar.toLocaleString()} trades
            </span>
          </div>
        ) : entry.deployed ? (
          <span className="slab-tag slab-tag--terminal" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <CheckCircle size={9} /> Active
          </span>
        ) : (
          <span className="slab-tag" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <XCircle size={9} /> Idle
          </span>
        )}
      </td>
      <td style={{ textAlign: "center", whiteSpace: "nowrap" }}>
        <button
          type="button"
          onClick={onBacktest}
          className="slab-btn slab-btn--xs slab-btn--primary"
          title="Backtest this strategy"
          style={{ marginRight: 6 }}
        >
          <Play size={10} />
          Run
        </button>
        <button
          type="button"
          onClick={onDelete}
          disabled={isDeleting}
          className="slab-btn slab-btn--xs"
          title="Delete this strategy"
          style={{ borderColor: "var(--bad)", color: "var(--bad)" }}
        >
          <Trash2 size={10} />
        </button>
      </td>
    </tr>
  );
}
