import { Link } from 'react-router-dom';

export function TerminalRedirectBanner() {
  return (
    <div style={{
      padding: 16, borderRadius: 12, marginBottom: 16,
      border: '1px solid rgba(16,185,129,.3)',
      background: 'rgba(16,185,129,.06)',
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    }}>
      <div style={{ fontSize: 13 }}>
        <strong>Generate strategies from natural language.</strong>{' '}
        <span style={{ opacity: .7 }}>
          Use the AI Terminal with the strategy-crafter skill — it's verified end-to-end.
        </span>
      </div>
      <Link to="/terminal" style={{
        padding: '8px 16px', borderRadius: 8, fontSize: 13, fontWeight: 600,
        background: '#10B981', color: '#050505', textDecoration: 'none',
      }}>
        Open Terminal →
      </Link>
    </div>
  );
}
