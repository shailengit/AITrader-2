import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchRegimes, summarizeRegimes, type SectorRegime } from '../lib/regime';
import { fetchLivePnl, type LivePnl } from '../lib/alpaca';
import { DriftAlertStrip } from '../components/shared/DriftAlertStrip';
import { HypothesisBacklogCard } from '../components/shared/HypothesisBacklogCard';
import { useTheme } from '../context/ThemeContext';

const NAV_TOOLS = [
  { to: '/sectors',        label: 'Sector Rotation',  desc: 'ETF momentum & leading stocks' },
  { to: '/screener/build', label: 'AI Stock Screener', desc: 'Dormant giants & quant filters' },
  { to: '/markov',         label: 'Markov Trader',     desc: 'Regime-aware jump-model signals' },
  { to: '/coach',          label: 'Trade Coach',       desc: 'Drift, deploys, and P&L' },
  { to: '/strategy-lab',   label: 'Strategy Lab',      desc: 'Natural-language backtests' },
  { to: '/hypotheses',     label: 'Hypothesis Backlog',desc: 'Saved setups awaiting tests' },
  { to: '/terminal',       label: 'AI Terminal',       desc: 'Claude Code in your browser' },
  { to: '/earnings',       label: 'Earnings Calendar', desc: 'Upcoming reports & EPS' },
];

export default function CommandCenter() {
  const { isDarkMode } = useTheme();
  const [sectors, setSectors] = useState<SectorRegime[]>([]);
  const [live, setLive] = useState<LivePnl | null>(null);

  useEffect(() => {
    fetchRegimes().then(setSectors).catch(() => {});
  }, []);

  useEffect(() => {
    fetchLivePnl().then(setLive).catch(() => {});
  }, []);

  const summary = summarizeRegimes(sectors);
  const livePl = live?.total_unrealized_pl ?? 0;
  const livePlColor = livePl >= 0 ? '#10B981' : '#EF4444';

  return (
    <div style={{ maxWidth: 1280, margin: '0 auto', padding: '32px 24px' }}>
      <h1 style={{
        fontSize: 32, fontWeight: 700, letterSpacing: '-.02em', marginBottom: 24,
        color: isDarkMode ? '#ffffff' : '#1d1d1f',
      }}>
        Command Center
      </h1>

      <DriftAlertStrip />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16, marginBottom: 16 }}>
        <Card title="Today's Regime" isDarkMode={isDarkMode}>
          <div style={{ fontSize: 24, fontWeight: 700, color: summary.overall === 'BULL' ? '#10B981' : '#EF4444' }}>
            {summary.overall}
          </div>
          <div style={{ fontSize: 14, opacity: .7 }}>
            Vol: {summary.vol} · {sectors.length} sectors trained
          </div>
        </Card>

        <Card title="Live P&L" isDarkMode={isDarkMode}>
          {live == null ? (
            <div style={{ fontSize: 14, opacity: .7 }}>Loading live P&L…</div>
          ) : !live.configured ? (
            <div style={{ fontSize: 14, opacity: .7 }}>
              Alpaca not configured — add keys to the root .env
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 600 }}>{live.strategy_name}</span>
                <span style={{
                  fontSize: 11, padding: '1px 8px', borderRadius: 999,
                  background: isDarkMode ? 'rgba(16,185,129,.15)' : 'rgba(16,185,129,.1)',
                  color: '#10B981',
                }}>
                  {live.paper ? 'Paper' : 'Live'}
                </span>
              </div>
              <div style={{ fontSize: 24, fontWeight: 700 }}>
                ${(live.account?.equity ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: 14, opacity: .7 }}>
                Cash: ${(live.account?.cash ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                {' · '}{live.n_positions} position{live.n_positions === 1 ? '' : 's'}
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, color: livePlColor, marginTop: 8 }}>
                P&L: ${livePl.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                {live.total_unrealized_pl_pct != null && (
                  <> ({((live.total_unrealized_pl_pct) * 100).toFixed(1)}%)</>
                )}
              </div>
            </>
          )}
        </Card>

        <Card title="Hypothesis Backlog" isDarkMode={isDarkMode}>
          <HypothesisBacklogCard />
        </Card>

        <Card title="Recent Journal" isDarkMode={isDarkMode}>
          <div style={{ fontSize: 14, opacity: .7 }}>
            No journal entries yet. Run a Markov scan or deploy a strategy.
          </div>
        </Card>
      </div>

      <Card title="Quick Navigation" isDarkMode={isDarkMode}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
          gap: 12,
        }}>
          {NAV_TOOLS.map((tool) => (
            <Link
              key={tool.to}
              to={tool.to}
              style={{
                display: 'block',
                padding: '14px 16px',
                borderRadius: 10,
                border: `1px solid ${isDarkMode ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.08)'}`,
                background: isDarkMode ? 'rgba(255,255,255,.02)' : 'rgba(0,0,0,.02)',
                textDecoration: 'none',
                color: isDarkMode ? '#ffffff' : '#1d1d1f',
                transition: 'border-color .15s ease, background .15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = '#10B981';
                e.currentTarget.style.background = isDarkMode ? 'rgba(16,185,129,.08)' : 'rgba(16,185,129,.06)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = isDarkMode ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.08)';
                e.currentTarget.style.background = isDarkMode ? 'rgba(255,255,255,.02)' : 'rgba(0,0,0,.02)';
              }}
            >
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{tool.label}</div>
              <div style={{ fontSize: 12, opacity: .6 }}>{tool.desc}</div>
            </Link>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Card({ title, children, isDarkMode }: { title: string; children: React.ReactNode; isDarkMode: boolean }) {
  return (
    <div style={{
      padding: 24, borderRadius: 16,
      border: `1px solid ${isDarkMode ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.08)'}`,
      background: isDarkMode ? 'rgba(255,255,255,.02)' : 'rgba(0,0,0,.02)',
    }}>
      <div style={{
        fontSize: 11, textTransform: 'uppercase', letterSpacing: '.05em',
        opacity: .55, marginBottom: 12,
        color: isDarkMode ? '#ffffff' : '#1d1d1f',
      }}>
        {title}
      </div>
      {children}
    </div>
  );
}
