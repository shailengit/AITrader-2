import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Card } from '../../components/ui/Card';
import { coachApi, type BacktestAnalysis } from '../../lib/coach';
import { ReportView } from './ReportView';
import { BacktestEquityCurve } from './BacktestEquityCurve';

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  });
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;
}

function fmtRange(a: BacktestAnalysis): string {
  const s = a.run_summary?.start_date;
  const e = a.run_summary?.end_date;
  if (s && e) return `${s.slice(0, 10)} → ${e.slice(0, 10)}`;
  return '—';
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'bad' | 'neutral' }) {
  const color =
    tone === 'good' ? 'var(--good)' : tone === 'bad' ? 'var(--bad)' : 'var(--foreground)';
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-[color:var(--subtle)]">{label}</span>
      <span className="text-sm font-semibold" style={{ color }}>
        {value}
      </span>
    </div>
  );
}

function ExperimentRow({
  a,
  onOpen,
  selectable,
  selected,
  onToggle,
  onDelete,
}: {
  a: BacktestAnalysis;
  onOpen: (a: BacktestAnalysis) => void;
  selectable?: boolean;
  selected?: boolean;
  onToggle?: (id: string) => void;
  onDelete?: (a: BacktestAnalysis) => void;
}) {
  const rs = a.run_summary;
  const [opening, setOpening] = useState(false);

  const openReport = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!a.report_path) return;
    setOpening(true);
    // Open the window SYNCHRONOUSLY in the click gesture — an `await` before
    // window.open() breaks the user-gesture context and the popup blocker
    // silently swallows it (that's why "View Report" appeared to do nothing).
    const win = window.open('', '_blank');
    if (!win) {
      // Popup blocked — fall back to the in-app detail view.
      setOpening(false);
      onOpen(a);
      return;
    }
    try {
      const html = await coachApi.getBacktestAnalysisReport(a.id);
      win.document.open();
      win.document.write(html);
      win.document.close();
    } catch {
      win.close();
      // fall back to the in-app detail view if the fetch fails
      onOpen(a);
    } finally {
      setOpening(false);
    }
  };

  return (
    <div
      className={`flex items-start gap-3 rounded-lg border bg-[color:var(--surface-raised)] p-4 transition-colors ${
        selected ? 'border-[color:var(--accent)]' : 'border-[color:var(--border)]'
      }`}
    >
      {selectable && (
        <input
          type="checkbox"
          checked={!!selected}
          onChange={() => onToggle?.(a.id)}
          className="mt-1 h-4 w-4 accent-[color:var(--accent)]"
          aria-label={`Select ${a.strategy_name}`}
        />
      )}
      <button onClick={() => onOpen(a)} className="w-full text-left">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-sm font-semibold text-[color:var(--foreground)]">{a.strategy_name}</div>
          <div className="text-xs text-[color:var(--subtle)]">{fmtDate(a.created_at)}</div>
        </div>
        <div className="mb-3 text-xs text-[color:var(--subtle)]">
          {a.n_completed} completed / {a.n_runs} runs · {a.n_trades.toLocaleString()} trades · {fmtRange(a)}
        </div>
        <div className="grid grid-cols-4 gap-3">
          <Stat label="Best CAGR" value={fmtPct(rs?.best_cagr_pct)} tone="good" />
          <Stat label="Worst CAGR" value={fmtPct(rs?.worst_cagr_pct)} tone="bad" />
          <Stat label="Median CAGR" value={fmtPct(rs?.median_cagr_pct)} tone="neutral" />
          <Stat label="Win rate" value={rs?.mean_win_rate_pct != null ? `${rs.mean_win_rate_pct.toFixed(1)}%` : '—'} tone="neutral" />
        </div>
      </button>
      {a.report_path && (
        <button
          onClick={openReport}
          disabled={opening}
          title="Open the HTML performance report in a new tab"
          className="mt-1 shrink-0 rounded-md border border-[color:var(--accent)] px-3 py-1 text-xs font-medium text-[color:var(--accent-light)] transition-opacity hover:bg-[color:var(--accent-glow)] disabled:opacity-50"
        >
          {opening ? 'Opening…' : 'View Report ↗'}
        </button>
      )}
      {onDelete && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete(a);
          }}
          title="Delete this experiment"
          className="mt-1 shrink-0 rounded-md border border-[color:var(--border)] px-3 py-1 text-xs font-medium text-[color:var(--subtle)] transition-colors hover:border-[color:var(--bad)] hover:text-[color:var(--bad)]"
        >
          Delete
        </button>
      )}
    </div>
  );
}

function ReportFrame({ html }: { html: string }) {
  return (
    <iframe
      title="Backtest report"
      srcDoc={html}
      className="h-full w-full rounded-md border border-[color:var(--border)] bg-white"
      sandbox="allow-scripts"
    />
  );
}

function DetailView({ a, onBack }: { a: BacktestAnalysis; onBack: () => void }) {
  const { data: reportHtml, isLoading } = useQuery({
    queryKey: ['backtest-analysis-report', a.id],
    queryFn: () => coachApi.getBacktestAnalysisReport(a.id),
    enabled: true,
  });

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <button onClick={onBack} className="text-xs text-[color:var(--accent-light)] hover:underline">
          ← Back to experiments
        </button>
        <div className="text-sm font-semibold text-[color:var(--foreground)]">
          {a.strategy_name} · {a.n_completed} runs
        </div>
      </div>
      <div className="mb-4 rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-raised)] p-4">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-[color:var(--subtle)]">
          Per-Run Equity (% return)
        </div>
        <BacktestEquityCurve analysisId={a.id} />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-raised)] p-4">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-[color:var(--subtle)]">
            AI Analysis
          </div>
          <div className="max-h-[70vh] overflow-y-auto">
            <ReportView markdown={a.analysis_md} />
          </div>
        </div>
        <div className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-raised)] p-4">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-[color:var(--subtle)]">
            HTML Report
          </div>
          <div className="h-[70vh]">
            {isLoading ? (
              <div className="text-[color:var(--subtle)]">Loading report…</div>
            ) : reportHtml ? (
              <ReportFrame html={reportHtml} />
            ) : (
              <div className="text-[color:var(--subtle)]">No report available.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function CompareView({ items, onBack }: { items: BacktestAnalysis[]; onBack: () => void }) {
  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <button onClick={onBack} className="text-xs text-[color:var(--accent-light)] hover:underline">
          ← Back to experiments
        </button>
        <div className="text-sm font-semibold text-[color:var(--foreground)]">
          Comparing {items.length} experiments
        </div>
      </div>

      {/* Summary comparison table */}
      <div className="mb-4 overflow-x-auto rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-raised)] p-4">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-[color:var(--subtle)]">
              <th className="py-1 pr-4">Metric</th>
              {items.map((a) => (
                <th key={a.id} className="py-1 pr-4 font-semibold text-[color:var(--foreground)]">
                  {a.strategy_name}
                  <div className="text-[10px] font-normal text-[color:var(--subtle)]">{fmtDate(a.created_at)}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {([
              ['Runs', (a: BacktestAnalysis) => `${a.n_completed}/${a.n_runs}`],
              ['Trades', (a: BacktestAnalysis) => a.n_trades.toLocaleString()],
              ['Best CAGR', (a: BacktestAnalysis) => fmtPct(a.run_summary?.best_cagr_pct)],
              ['Worst CAGR', (a: BacktestAnalysis) => fmtPct(a.run_summary?.worst_cagr_pct)],
              ['Median CAGR', (a: BacktestAnalysis) => fmtPct(a.run_summary?.median_cagr_pct)],
              ['Win rate', (a: BacktestAnalysis) => (a.run_summary?.mean_win_rate_pct != null ? `${a.run_summary.mean_win_rate_pct.toFixed(1)}%` : '—')],
              ['Date range', (a: BacktestAnalysis) => fmtRange(a)],
            ] as [string, (a: BacktestAnalysis) => string][]).map(([label, fn]) => (
              <tr key={label as string} className="border-t border-[color:var(--border)]">
                <td className="py-2 pr-4 text-[color:var(--subtle)]">{label as string}</td>
                {items.map((a) => (
                  <td key={a.id} className="py-2 pr-4 font-medium text-[color:var(--foreground)]">
                    {(fn as (x: BacktestAnalysis) => string)(a)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Side-by-side AI analyses */}
      <div className={`grid gap-4 ${items.length > 1 ? 'lg:grid-cols-2' : ''}`}>
        {items.map((a) => (
          <div key={a.id} className="rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-raised)] p-4">
            <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-[color:var(--subtle)]">
              AI Analysis — {a.strategy_name}
            </div>
            <div className="max-h-[70vh] overflow-y-auto">
              <ReportView markdown={a.analysis_md} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function BacktestLearnings({ strategyName }: { strategyName?: string }) {
  const [selected, setSelected] = useState<BacktestAnalysis | null>(null);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [filter, setFilter] = useState<string>('all');
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['backtest-analyses', strategyName],
    queryFn: () => coachApi.listBacktestAnalyses({ strategy_name: strategyName, limit: 100 }),
    enabled: true,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => coachApi.deleteBacktestAnalysis(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['backtest-analyses'] });
      qc.invalidateQueries({ queryKey: ['coach-overview'] });
    },
  });

  const handleDelete = (a: BacktestAnalysis) => {
    if (!window.confirm(`Delete this experiment?\n\n${a.strategy_name} · ${a.n_completed} runs · ${fmtDate(a.created_at)}\n\nThis removes the analysis and its backtest batch from the Coach.`)) {
      return;
    }
    deleteMutation.mutate(a.id);
  };

  const strategies = useMemo(() => {
    if (!data) return [];
    return Array.from(new Set(data.map((a) => a.strategy_name))).sort();
  }, [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    return filter === 'all' ? data : data.filter((a) => a.strategy_name === filter);
  }, [data, filter]);

  const compareItems = useMemo(
    () => (data ? data.filter((a) => compareIds.includes(a.id)) : []),
    [data, compareIds],
  );

  const toggleCompare = (id: string) =>
    setCompareIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  if (selected) {
    return (
      <Card className="p-6">
        <DetailView a={selected} onBack={() => setSelected(null)} />
      </Card>
    );
  }

  if (compareItems.length >= 2) {
    return (
      <Card className="p-6">
        <CompareView items={compareItems} onBack={() => setCompareIds([])} />
      </Card>
    );
  }

  return (
    <Card className="p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-[color:var(--muted)]">Backtest Experiments (AI)</div>
        <div className="flex items-center gap-3">
          {strategies.length > 1 && (
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="rounded-md border border-[color:var(--border)] bg-[color:var(--surface-raised)] px-2 py-1 text-xs text-[color:var(--foreground)]"
            >
              <option value="all">All strategies</option>
              {strategies.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          )}
          {compareIds.length > 0 && (
            <button
              onClick={() => setCompareIds([])}
              className="text-xs text-[color:var(--subtle)] hover:underline"
            >
              Clear selection ({compareIds.length})
            </button>
          )}
          <button
            onClick={() => setCompareIds([])}
            disabled={compareIds.length < 2}
            className="rounded-md border border-[color:var(--accent)] px-3 py-1 text-xs font-medium text-[color:var(--accent-light)] transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          >
            Compare ({compareIds.length})
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="text-[color:var(--subtle)]">Loading experiments…</div>
      ) : !filtered || filtered.length === 0 ? (
        <div className="text-[color:var(--subtle)]">
          {filter !== 'all'
            ? `No experiments for "${filter}" yet.`
            : 'No backtest experiments yet. Run a multi-run backtest in Strategy Lab and the AI will analyze its per-trade data here.'}
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((a) => (
            <ExperimentRow
              key={a.id}
              a={a}
              onOpen={setSelected}
              selectable
              selected={compareIds.includes(a.id)}
              onToggle={toggleCompare}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}
    </Card>
  );
}
