import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts';

const COLORS = ['var(--accent)', 'var(--bad)', 'var(--accent-light)', 'var(--muted)'];

// Format a fraction (e.g. -0.0938) as a percentage for the y-axis ticks.
const pctTick = (v: number) => `${(v * 100).toFixed(0)}%`;

export function RegimeAttribution({
  data,
}: {
  data: Record<string, { n: number; pnl: number; pnl_pct: number }>;
}) {
  const all = Object.entries(data).map(([regime, v]) => ({ regime, ...v }));
  const total = all.reduce((s, r) => s + r.n, 0);
  // Hide the "unknown" bucket when it's a negligible share of trades (<1%).
  // It's usually a handful of delisted/renamed tickers the regime classifier
  // can't map, and its near-empty average is noise, not signal.
  const rows = all.filter((r) => r.regime !== 'unknown' || (total > 0 && r.n / total >= 0.01));
  if (rows.length === 0) {
    return <div className="text-[color:var(--subtle)] text-sm">No closed trades in this period.</div>;
  }
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-hover)" />
          <XAxis dataKey="regime" stroke="var(--muted)" tick={{ fontSize: 11 }} />
          <YAxis
            stroke="var(--muted)"
            tick={{ fontSize: 11 }}
            tickFormatter={pctTick}
            label={{ value: 'Avg Return / Trade', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle', fill: 'var(--muted)', fontSize: 11 } }}
          />
          <Tooltip
            contentStyle={{ background: 'var(--surface-overlay)', border: '1px solid var(--border)' }}
            formatter={(value, name) => {
              if (name === 'pnl_pct') return [`${(Number(value) * 100).toFixed(2)}%`, 'Avg Return'];
              return [value, name];
            }}
          />
          <Bar dataKey="pnl_pct" name="Avg Return">
            {rows.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
