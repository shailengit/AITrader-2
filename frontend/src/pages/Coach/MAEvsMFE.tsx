import { ScatterChart, Scatter, XAxis, YAxis, ZAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts';

interface Point {
  mae: number | null;
  mfe: number | null;
  pnl: number | null;
  ticker: string;
  entry_at?: string | null;
}

export function MAEvsMFE({ data }: { data: Point[] }) {
  const points = data.filter((d) => d.mae != null && d.mfe != null);
  if (points.length === 0) {
    return <div className="text-[color:var(--subtle)] text-sm">No MAE/MFE data yet (close some trades to populate).</div>;
  }
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-hover)" />
          <XAxis type="number" dataKey="mae" name="MAE" stroke="var(--muted)" tick={{ fontSize: 11 }} />
          <YAxis type="number" dataKey="mfe" name="MFE" stroke="var(--muted)" tick={{ fontSize: 11 }} />
          <ZAxis range={[40, 80]} />
          <Tooltip contentStyle={{ background: 'var(--surface-overlay)', border: '1px solid var(--border)' }} cursor={{ strokeDasharray: '3 3' }} />
          <Scatter data={points}>
            {points.map((p, i) => (
              <Cell key={i} fill={(p.pnl ?? 0) > 0 ? 'var(--good)' : 'var(--bad)'} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
