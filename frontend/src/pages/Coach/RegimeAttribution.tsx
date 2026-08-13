import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts';

const COLORS = ['var(--accent)', 'var(--bad)', 'var(--accent-light)', 'var(--muted)'];

export function RegimeAttribution({
  data,
}: {
  data: Record<string, { n: number; pnl: number; pnl_pct: number }>;
}) {
  const rows = Object.entries(data).map(([regime, v]) => ({ regime, ...v }));
  if (rows.length === 0) {
    return <div className="text-[color:var(--subtle)] text-sm">No closed trades in this period.</div>;
  }
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-hover)" />
          <XAxis dataKey="regime" stroke="var(--muted)" tick={{ fontSize: 11 }} />
          <YAxis stroke="var(--muted)" tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={{ background: 'var(--surface-overlay)', border: '1px solid var(--border)' }} />
          <Bar dataKey="pnl">
            {rows.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
