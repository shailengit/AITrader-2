import { useEffect, useState } from 'react';
import { request } from '@/lib/api';

interface Hypothesis {
  id: string;
  source: string;
  why: string;
  status: string;
  created_at: string;
  ticker?: string;
  sector?: string;
  regime?: string;
  generated_strategy_id?: string;
}

export default function Hypotheses() {
  const [rows, setRows] = useState<Hypothesis[]>([]);
  const [status, setStatus] = useState<string>('');

  useEffect(() => {
    const url = status ? `/hypotheses?status=${status}` : '/hypotheses';
    request<Hypothesis[]>(url).then(setRows);
  }, [status]);

  const archive = async (id: string) => {
    await request(`/hypotheses/${id}`, {
      method: 'PATCH',
      body: { status: 'archived' },
    });
    setRows(rs => rs.filter(r => r.id !== id));
  };

  return (
    <div style={{ maxWidth: 1280, margin: '0 auto', padding: '32px 24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ fontSize: 28, fontWeight: 700 }}>Hypothesis Backlog</h1>
        <select value={status} onChange={e => setStatus(e.target.value)} style={{
          padding: '6px 10px', borderRadius: 6, background: 'var(--surface)',
          border: '1px solid var(--border)', color: 'var(--foreground)', fontSize: 13,
          cursor: 'pointer',
        }}>
          <option value="">All open</option>
          <option value="generated">Generated</option>
          <option value="archived">Archived</option>
        </select>
      </div>

      {rows.length === 0 ? (
        <div style={{ color: 'var(--muted)', fontSize: 14 }}>No hypotheses yet. Save one from Sectors, Screener, or Markov.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map(h => (
            <div key={h.id} style={{
              padding: 16, borderRadius: 10,
              border: '1px solid var(--border)',
              background: 'var(--surface)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
            }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 4 }}>
                  {h.source} · {new Date(h.created_at).toLocaleString()}
                  {h.ticker && ` · ${h.ticker}`}
                  {h.regime && ` · regime: ${h.regime}`}
                </div>
                <div style={{ fontSize: 14, color: 'var(--foreground)' }}>{h.why}</div>
              </div>
              <button onClick={() => archive(h.id)} style={{
                padding: '4px 10px', fontSize: 12, borderRadius: 6,
                background: 'transparent', border: '1px solid var(--border)',
                color: 'var(--muted)', cursor: 'pointer',
              }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--border-hover)'; e.currentTarget.style.color = 'var(--foreground)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--muted)'; }}
              >Archive</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
