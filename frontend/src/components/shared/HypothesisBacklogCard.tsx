import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { request } from '@/lib/api';

interface H {
  id: string;
  source: string;
  why: string;
  created_at: string;
  ticker?: string;
}

export function HypothesisBacklogCard() {
  const [rows, setRows] = useState<H[]>([]);

  useEffect(() => {
    request<H[]>('/hypotheses?status=open&limit=5')
      .then(setRows)
      .catch(() => {});
  }, []);

  if (rows.length === 0) {
    return (
      <div style={{ fontSize: 14, opacity: .6 }}>
        Save a setup from Sectors / Screener / Markov to start a backlog.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {rows.map(h => (
        <div key={h.id} style={{ fontSize: 13 }}>
          <span style={{ opacity: .55 }}>{h.source}</span>
          {h.ticker && <span style={{ marginLeft: 6, fontWeight: 600 }}>{h.ticker}</span>}
          <span style={{ marginLeft: 6 }}>{h.why}</span>
        </div>
      ))}
      <Link to="/hypotheses" style={{ fontSize: 12, marginTop: 6 }}>View all →</Link>
    </div>
  );
}
