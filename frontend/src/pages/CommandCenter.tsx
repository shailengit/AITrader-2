import { useEffect, useState } from 'react';
import { fetchRegimes, summarizeRegimes, type SectorRegime } from '../lib/regime';
import { DriftAlertStrip } from '../components/shared/DriftAlertStrip';
import { HypothesisBacklogCard } from '../components/shared/HypothesisBacklogCard';

export default function CommandCenter() {
  const [sectors, setSectors] = useState<SectorRegime[]>([]);

  useEffect(() => {
    fetchRegimes().then(setSectors).catch(() => {});
  }, []);

  const summary = summarizeRegimes(sectors);

  return (
    <div style={{ maxWidth: 1280, margin: '0 auto', padding: '32px 24px' }}>
      <h1 style={{ fontSize: 32, fontWeight: 700, letterSpacing: '-.02em', marginBottom: 24 }}>
        Command Center
      </h1>

      <DriftAlertStrip />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16, marginBottom: 16 }}>
        <Card title="Today's Regime">
          <div style={{ fontSize: 24, fontWeight: 700, color: summary.overall === 'BULL' ? '#10B981' : '#EF4444' }}>
            {summary.overall}
          </div>
          <div style={{ fontSize: 14, opacity: .7 }}>
            Vol: {summary.vol} · {sectors.length} sectors trained
          </div>
        </Card>

        <Card title="Live P&L">
          <div style={{ fontSize: 14, opacity: .7 }}>
            Deploy a strategy in Strategy Lab to track live P&L here.
          </div>
        </Card>

        <Card title="Hypothesis Backlog">
          <HypothesisBacklogCard />
        </Card>

        <Card title="Recent Journal">
          <div style={{ fontSize: 14, opacity: .7 }}>
            No journal entries yet. Run a Markov scan or deploy a strategy.
          </div>
        </Card>
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      padding: 24, borderRadius: 16,
      border: '1px solid rgba(255,255,255,.08)',
      background: 'rgba(255,255,255,.02)',
    }}>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.05em', opacity: .55, marginBottom: 12 }}>
        {title}
      </div>
      {children}
    </div>
  );
}
