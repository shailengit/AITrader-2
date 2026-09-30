// Strategy list for the Backtest tab: shows every Library strategy that has
// accumulated experiment data (from the Trading Brain), so the user can see,
// switch between, and compare strategies without leaving the Backtest page.
import { useQuery } from "@tanstack/react-query";
import { Layers, TrendingUp } from "lucide-react";
import { brainApi, type BrainStrategyStat } from "../../lib/brain";

interface BrainStrategyListProps {
  activePath: string;
  onSelect: (path: string) => void;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function BrainStrategyList({ activePath, onSelect }: BrainStrategyListProps) {
  const { data: strategies, isLoading } = useQuery({
    queryKey: ["brain-strategies"],
    queryFn: () => brainApi.listStrategies(),
  });

  // Filter out the "unknown" bucket (legacy experiments with no class path)
  const list = (strategies || []).filter((s) => s.strategy_name !== "unknown");

  return (
    <div className="slab-panel" style={{ maxWidth: 1280 }}>
      <div className="slab-panel__head">
        <span className="slab-eyebrow slab-eyebrow--gold">// Strategy Library</span>
        <span className="slab-mono slab-mono--xs slab-mono--dim">
          {isLoading ? "loading…" : `${list.length} strategies with backtest data`}
        </span>
      </div>
      <div className="slab-panel__body">
        {list.length === 0 ? (
          <div className="slab-mono slab-mono--sm slab-mono--dim" style={{ padding: 12 }}>
            No strategies with backtests yet. Run a batch in the Backtest tab to start feeding the Brain.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {list.map((s: BrainStrategyStat) => {
              const active = s.strategy_class_path === activePath;
              return (
                <button
                  key={s.strategy_class_path}
                  type="button"
                  onClick={() => onSelect(s.strategy_class_path)}
                  style={{
                    display: "flex", alignItems: "center", gap: 12, textAlign: "left",
                    padding: "10px 12px", borderRadius: 8, width: "100%",
                    background: active ? "var(--accent-glow)" : "var(--surface-raised)",
                    border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
                    color: "var(--foreground)", cursor: "pointer",
                  }}
                >
                  <Layers size={14} style={{ opacity: 0.6, flexShrink: 0 }} />
                  <span style={{ flex: 1, fontWeight: 600, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {s.strategy_name}
                  </span>
                  <span className="slab-mono slab-mono--xs slab-mono--dim" style={{ whiteSpace: "nowrap" }}>
                    {s.n_runs} runs
                  </span>
                  <span className="slab-mono slab-mono--xs slab-mono--dim" style={{ whiteSpace: "nowrap" }}>
                    {s.n_trades.toLocaleString()} trades
                  </span>
                  <span style={{ fontSize: 12, whiteSpace: "nowrap", color: "var(--subtle)" }}>
                    WR {s.win_rate.toFixed(1)}%
                  </span>
                  <span style={{ fontSize: 12, whiteSpace: "nowrap", color: (s.best_return_pct ?? 0) >= 0 ? "var(--good)" : "var(--bad)", fontWeight: 600 }}>
                    best {fmtPct(s.best_return_pct)}
                  </span>
                  {active && <TrendingUp size={13} style={{ color: "var(--accent)", flexShrink: 0 }} />}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
