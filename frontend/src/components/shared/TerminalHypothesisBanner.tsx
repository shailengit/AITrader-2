import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { request } from '@/lib/api';

interface H {
  id: string;
  source: string;
  why: string;
  ticker?: string;
}

export function TerminalHypothesisBanner() {
  const [rows, setRows] = useState<H[]>([]);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    request<H[]>('/hypotheses?status=open&limit=5')
      .then(setRows)
      .catch(() => {});
  }, []);

  if (dismissed || rows.length === 0) return null;

  const summary = rows.length === 1
    ? `You have 1 open hypothesis.`
    : `You have ${rows.length} open hypotheses.`;
  const ids = rows.map(r => r.id).join(',');

  return (
    <div style={{
      padding: 12, borderRadius: 10,
      border: '1px solid rgba(16,185,129,.3)',
      background: 'rgba(16,185,129,.06)',
      marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      fontSize: 13,
    }}>
      <div>
        <strong>{summary}</strong>
        <span style={{ opacity: .7, marginLeft: 8 }}>
          Run the strategy-crafter skill with <code style={{ background: 'rgba(0,0,0,.2)', padding: '1px 6px', borderRadius: 3 }}>generate from hypotheses {ids}</code>
        </span>
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <Link to="/hypotheses" style={{ fontSize: 12 }}>View</Link>
        <button onClick={() => setDismissed(true)} style={{
          background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: 12,
        }}>Dismiss</button>
      </div>
    </div>
  );
}
