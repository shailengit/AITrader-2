import { useEffect, useState } from 'react';

interface Summary {
  strategy_path: string;
  is_deployed: boolean;
  n_live_trades: number;
  live_pnl: number;
  live_sharpe_30d: number;
  current_regime: string;
  regime_attribution: Record<string, { n_trades: number; win_rate: number; total_pnl: number }>;
  drift: { alert: boolean; max_divergence_pct: number };
  coach_insight: string;
  backtested: { total_return?: number; sharpe?: number };
}

export function StrategyCoachBadge({ strategyPath }: { strategyPath: string }) {
  const [s, setS] = useState<Summary | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    fetch(`/api/coach/strategy/${encodeURIComponent(strategyPath)}/summary`)
      .then(r => r.json())
      .then(setS)
      .catch(() => setS(null));
  }, [strategyPath]);

  if (!s) return <div style={{ fontSize: 12, opacity: .6 }}>Coach: unavailable</div>;

  const deployedBadge = s.is_deployed
    ? <span style={{ padding: '2px 8px', borderRadius: 6, background: 'rgba(16,185,129,.15)', color: '#10B981', fontSize: 11, fontWeight: 600 }}>DEPLOYED</span>
    : <span style={{ padding: '2px 8px', borderRadius: 6, background: 'rgba(255,255,255,.05)', color: 'inherit', fontSize: 11, opacity: .7 }}>BACKTESTED</span>;

  const pnlColor = s.live_pnl >= 0 ? '#10B981' : '#EF4444';
  const pnlText = s.is_deployed
    ? `${s.live_pnl >= 0 ? '+' : ''}${(s.live_pnl * 100).toFixed(1)}% live`
    : s.backtested?.total_return != null
      ? `${s.backtested.total_return >= 0 ? '+' : ''}${(s.backtested.total_return * 100).toFixed(1)}% backtested`
      : 'no data';

  return (
    <div style={{ marginTop: 8 } as any}>
      <div onClick={() => setExpanded(e => !e)} style={{
        display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, cursor: 'pointer',
        padding: 6, borderRadius: 6, background: 'rgba(255,255,255,.02)',
      }}>
        {deployedBadge}
        <span style={{ color: pnlColor, fontWeight: 600 }}>{pnlText}</span>
        <span style={{ opacity: .6 }}>· {s.n_live_trades} trades</span>
        <span style={{ opacity: .6 }}>· regime: {s.current_regime}</span>
        {s.drift.alert && <span style={{ color: '#F59E0B' }}>⚠ drift</span>}
      </div>
      {expanded && (
        <div style={{ padding: 12, marginTop: 6, borderRadius: 8, background: 'rgba(255,255,255,.02)', fontSize: 12 }}>
          {Object.keys(s.regime_attribution).length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>Regime attribution</div>
              {Object.entries(s.regime_attribution).map(([regime, agg]) => (
                <div key={regime} style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>{regime}</span>
                  <span>{agg.n_trades} trades · {(agg.win_rate * 100).toFixed(0)}% win · {(agg.total_pnl * 100).toFixed(1)}% P&L</span>
                </div>
              ))}
            </div>
          )}
          {s.coach_insight && (
            <div style={{ opacity: .8, fontStyle: 'italic' }}>
              💡 {s.coach_insight}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
