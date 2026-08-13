import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';

export function WinRateByStrategy({
  data,
}: {
  data: { name: string; n: number; win_rate: number }[];
}) {
  if (!data || data.length === 0) {
    return <div className="text-[color:var(--subtle)] text-sm">No strategies with closed trades in this period.</div>;
  }
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, bottom: 8, left: 64 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-hover)" />
          <XAxis type="number" domain={[0, 1]} stroke="var(--muted)" tick={{ fontSize: 11 }} />
          <YAxis type="category" dataKey="name" stroke="var(--muted)" tick={{ fontSize: 11 }} width={120} />
          <Tooltip contentStyle={{ background: 'var(--surface-overlay)', border: '1px solid var(--border)' }} />
          <Bar dataKey="win_rate" fill="var(--accent)" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
