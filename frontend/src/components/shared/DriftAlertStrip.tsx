import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { request } from '@/lib/api';

interface DriftHit {
  strategy_path: string;
  drift: { max_divergence_pct: number; alert: boolean };
}

// Shape of GET /api/strategy-lab/strategy-classes items (StrategyClassItem)
interface StrategyClassItem {
  name: string;
  path: string; // e.g. "backend/app/services/strategies/<file>.py"
  deployed: boolean;
}

export function DriftAlertStrip() {
  const [hits, setHits] = useState<DriftHit[]>([]);

  useEffect(() => {
    // List strategies via the Strategy Lab class registry, then reuse the Coach
    // summary endpoint per strategy to detect live-equity drift.
    request<StrategyClassItem[]>('/strategy-lab/strategy-classes')
      .then(async (classes) => {
        // Coach summary expects a relative "strategies/<file>.py" path; derive it
        // from the absolute class path (same as StrategyCoachBadge in StepLibrary).
        const settled = await Promise.allSettled(
          classes.map((item) => {
            const rel = item.path.split('/services/')[1] ?? item.path;
            return request<any>(`/coach/strategy/${encodeURIComponent(rel)}/summary`);
          })
        );
        const drifted = settled
          .filter((r): r is PromiseFulfilledResult<any> => r.status === 'fulfilled')
          .map(r => r.value)
          .filter((s: any) => s?.drift?.alert);
        setHits(drifted);
      })
      .catch(() => setHits([]));
  }, []);

  if (hits.length === 0) {
    return (
      <div style={{
        padding: 12, marginBottom: 16, borderRadius: 10,
        border: '1px solid rgba(255,255,255,.08)',
        background: 'rgba(255,255,255,.02)',
        fontSize: 13, opacity: .6,
      }}>
        All strategies within tolerance.
      </div>
    );
  }

  return (
    <div style={{
      padding: 12, marginBottom: 16, borderRadius: 10,
      border: '1px solid rgba(245,158,11,.4)',
      background: 'rgba(245,158,11,.08)',
      display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13,
    }}>
      <div style={{ fontWeight: 600, color: '#F59E0B' }}>
        ⚠ {hits.length} {hits.length === 1 ? 'strategy' : 'strategies'} drifted outside tolerance
      </div>
      {hits.map(h => (
        <div key={h.strategy_path}>
          <Link to={`/coach?strategy=${encodeURIComponent(h.strategy_path)}`}>
            {h.strategy_path}
          </Link>
          <span style={{ opacity: .6, marginLeft: 8 }}>
            divergence {(h.drift.max_divergence_pct * 100).toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  );
}
