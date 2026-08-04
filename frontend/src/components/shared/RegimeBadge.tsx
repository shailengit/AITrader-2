import { useEffect, useState } from 'react';
import { fetchRegimes, summarizeRegimes, type SectorRegime } from '../../lib/regime';

const COLORS = {
  BULL: '#10B981',
  BEAR: '#EF4444',
  UNKNOWN: '#8b94a5',
  LOW: '#10B981',
  HIGH: '#F59E0B',
};

export function RegimeBadge() {
  const [sectors, setSectors] = useState<SectorRegime[]>([]);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await fetchRegimes();
        if (!cancelled) {
          setSectors(data);
          setError(false);
        }
      } catch {
        if (!cancelled) setError(true);
      }
    };
    load();
    const t = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const summary = summarizeRegimes(sectors);
  const dotColor = error ? COLORS.UNKNOWN : COLORS[summary.overall];
  const label = error
    ? 'STALE'
    : `${summary.overall} ${summary.vol}-vol · ${sectors.length} sectors`;

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '6px 12px', borderRadius: 8,
          border: '1px solid rgba(255,255,255,.1)',
          background: 'transparent', color: 'inherit',
          cursor: 'pointer', fontSize: 13, fontWeight: 500,
        }}
      >
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: dotColor, display: 'inline-block',
        }} />
        {label}
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: '100%', right: 0, marginTop: 8,
          background: 'var(--panel, #11151c)', border: '1px solid rgba(255,255,255,.1)',
          borderRadius: 10, padding: 16, minWidth: 320, zIndex: 50,
          boxShadow: '0 8px 24px rgba(0,0,0,.4)',
        }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, opacity: .7 }}>
            SECTOR REGIMES
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6 }}>
            {sectors.map(s => (
              <div key={s.etf} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '4px 8px', borderRadius: 6, background: 'rgba(255,255,255,.03)',
                fontSize: 12,
              }}>
                <span style={{ fontWeight: 600 }}>{s.etf}</span>
                <span style={{ color: COLORS[s.regime] }}>{s.regime}</span>
                <span style={{ color: COLORS[s.vol_regime], fontSize: 10 }}>
                  {s.vol_regime}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
