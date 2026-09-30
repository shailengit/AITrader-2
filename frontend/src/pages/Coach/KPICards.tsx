import { Card } from '../../components/ui/Card';
import type { KPISet } from '../../lib/coach';

function fmt(n: number | null | undefined, digits = 0): string {
  if (n == null) return '—';
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—';
  return `${(n * 100).toFixed(1)}%`;
}

// Renders a value that is ALREADY in percent units (e.g. 12202.3 -> "12202.3%").
function fmtPctVal(n: number | null | undefined): string {
  if (n == null) return '—';
  return `${n.toFixed(1)}%`;
}

export function KPICards({ k }: { k: KPISet }) {
  const pct = k.kpi_mode === 'pct';
  const items = [
    { label: pct ? 'Median CAGR' : 'Total P&L', value: pct ? fmtPctVal(k.total_pnl) : `$${fmt(k.total_pnl, 2)}`, accent: k.total_pnl >= 0 ? 'text-[color:var(--good)]' : 'text-[color:var(--bad)]' },
    { label: 'Win Rate', value: fmtPct(k.win_rate) },
    { label: pct ? 'Best CAGR' : 'Expectancy', value: pct ? fmtPctVal(k.expectancy) : `$${fmt(k.expectancy, 2)}` },
    { label: '# Trades', value: String(k.n_trades) },
    { label: 'Open', value: String(k.n_open) },
    { label: pct ? 'Worst CAGR' : 'Max DD', value: pct ? fmtPctVal(k.max_dd) : `$${fmt(k.max_dd, 2)}`, accent: 'text-[color:var(--bad)]' },
  ];
  return (
    <div>
      {k.label && (
        <div className="mb-2 text-xs text-[color:var(--subtle)]">Backtest Experiments: {k.label}</div>
      )}
      <div className="grid grid-cols-6 gap-4">
        {items.map((it) => (
          <Card key={it.label} className="p-6">
            <div className="text-xs uppercase tracking-wide text-[color:var(--subtle)]">{it.label}</div>
            <div className={`mt-2 text-2xl font-semibold ${it.accent ?? 'text-[color:var(--foreground)]'}`}>{it.value}</div>
          </Card>
        ))}
      </div>
    </div>
  );
}
