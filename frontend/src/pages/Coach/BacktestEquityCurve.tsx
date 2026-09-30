import { useQuery } from '@tanstack/react-query';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from 'recharts';
import { coachApi, type BacktestRunCurve } from '../../lib/coach';

interface Point {
  date: string;
  [key: string]: string | number;
}

/**
 * Per-run backtest equity overlay. Each independent backtest run (own $100k,
 * own randomized start date) is plotted as its own cumulative %-return line.
 * This matches what Strategy Lab shows — unlike the old single summed line,
 * which merged dollar P&L across all independent runs into a meaningless
 * ±billions figure (that's why the backtest tab appeared to show "only loss"
 * while Strategy Lab showed +436%+ returns).
 */
export function BacktestEquityCurve({ analysisId }: { analysisId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['backtest-analysis-runs', analysisId],
    queryFn: () => coachApi.getBacktestAnalysisRuns(analysisId),
    enabled: true,
  });

  if (isLoading) {
    return <div className="text-[color:var(--subtle)] text-sm">Loading per-run equity curves…</div>;
  }

  const runs = data?.runs ?? [];
  if (runs.length === 0) {
    return (
      <div className="text-[color:var(--subtle)] text-sm">
        No per-run equity data available for this batch.
      </div>
    );
  }

  // Build one combined point series keyed by date, one column per run.
  const byDate = new Map<string, Point>();
  runs.forEach((r: BacktestRunCurve) => {
    for (const p of r.curve) {
      if (!p.date) continue;
      const row = byDate.get(p.date) ?? ({ date: p.date } as Point);
      row[`run_${r.run_index}`] = p.pct_return;
      byDate.set(p.date, row);
    }
  });
  const chartData: Point[] = Array.from(byDate.values());

  // Downsample to one line per run; color via a small palette cycling.
  const palette = ['#10b981', '#22d3ee', '#a78bfa', '#f59e0b', '#3b82f6', '#ef4444', '#ec4899', '#14b8a6'];
  return (
    <div>
      <div className="mb-2 text-xs text-[color:var(--subtle)]">
        {runs.length} independent backtest runs · each plotted as its own % return
      </div>
      <div className="h-72 w-full">
        <ResponsiveContainer>
          <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-hover)" />
            <XAxis dataKey="date" stroke="var(--muted)" tick={{ fontSize: 10 }} />
            <YAxis stroke="var(--muted)" tick={{ fontSize: 10 }} />
            <Tooltip
              contentStyle={{ background: 'var(--surface-overlay)', border: '1px solid var(--border)' }}
              formatter={(value, name) => [`${Number(value).toFixed(2)}%`, `Run ${String(name).replace('run_', '')}`]}
            />
            {runs.length <= 20 && <Legend />}
            {runs.map((r: BacktestRunCurve, i) => (
              <Line
                key={r.run_index}
                type="monotone"
                dataKey={`run_${r.run_index}`}
                stroke={palette[i % palette.length]}
                dot={false}
                strokeWidth={1.25}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
