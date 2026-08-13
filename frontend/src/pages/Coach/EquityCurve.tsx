import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';

export function EquityCurve({ data }: { data: { date: string; equity: number }[] }) {
  if (!data || data.length === 0) {
    return <div className="text-[color:var(--subtle)] text-sm">No closed trades in this period.</div>;
  }
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-hover)" />
          <XAxis dataKey="date" stroke="var(--muted)" tick={{ fontSize: 11 }} />
          <YAxis stroke="var(--muted)" tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={{ background: 'var(--surface-overlay)', border: '1px solid var(--border)' }} />
          <Line type="monotone" dataKey="equity" stroke="var(--accent)" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
