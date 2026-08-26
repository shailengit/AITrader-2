import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from 'recharts';
import {
  fetchRegimes, summarizeRegimes, type SectorRegime,
} from '../lib/regime';
import {
  fetchLivePnl, fetchEquityCurve, type LivePnl, type LivePosition, type EquityCurve,
  type AccountLive, type AccountEquity,
} from '../lib/alpaca';
import { request } from '../lib/api';
import { DriftAlertStrip } from '../components/shared/DriftAlertStrip';
import { HypothesisBacklogCard } from '../components/shared/HypothesisBacklogCard';

/* ------------------------------------------------------------------ *
 * Real backend data sources wired into this dashboard:
 *  - /api/alpaca/live         portfolio value, unrealized P&L, positions (all accounts)
 *  - /api/alpaca/equity-curve equity history (portfolio performance, per account)
 *  - /api/markov/regimes      market regime per sector
 *  - /api/sectors             sector ETF momentum
 *  - /api/coach/metrics/overview  win-rate / trade stats (may be empty)
 * ------------------------------------------------------------------ */

const NAV_TOOLS = [
  { to: '/sectors',        label: 'Sector Rotation', desc: 'ETF momentum & leading stocks' },
  { to: '/screener/build', label: 'AI Stock Screener', desc: 'Dormant giants & quant filters' },
  { to: '/markov',         label: 'Markov Trader', desc: 'Regime-aware jump-model signals' },
  { to: '/coach',          label: 'Trade Coach', desc: 'Drift, deploys, and P&L' },
  { to: '/strategy-lab',   label: 'Strategy Lab', desc: 'Natural-language backtests' },
  { to: '/hypotheses',     label: 'Hypothesis Backlog', desc: 'Saved setups awaiting tests' },
  { to: '/terminal',       label: 'AI Terminal', desc: 'Claude Code in your browser' },
  { to: '/earnings',       label: 'Earnings Calendar', desc: 'Upcoming reports & EPS' },
];

interface SectorPerf { ticker: string; name: string; perf_3m: number | null; perf_6m: number | null; }
interface CoachOverview { empty?: boolean; kpis?: { n_trades?: number; win_rate?: number; total_pnl?: number } }

function fmtMoney(n: number | null | undefined, digits = 0): string {
  if (n == null || !isFinite(n)) return '—';
  return '$' + n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}
function fmtPct(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—';
  return (n * 100).toFixed(1) + '%';
}

export default function CommandCenter() {
  const [sectors, setSectors] = useState<SectorRegime[]>([]);
  const [live, setLive] = useState<LivePnl | null>(null);
  const [equity, setEquity] = useState<EquityCurve | null>(null);
  const [sectorPerf, setSectorPerf] = useState<SectorPerf[]>([]);
  const [coach, setCoach] = useState<CoachOverview | null>(null);

  useEffect(() => {
    fetchRegimes().then(setSectors).catch(() => {});
    fetchLivePnl().then(setLive).catch(() => {});
    fetchEquityCurve('3M', '1D').then(setEquity).catch(() => {});
    request<SectorPerf[]>('/sectors').then(setSectorPerf).catch(() => {});
    request<CoachOverview>('/coach/metrics/overview').then(setCoach).catch(() => {});
  }, []);

  const summary = summarizeRegimes(sectors);
  const winRate = coach?.kpis && (coach.kpis.n_trades ?? 0) > 0 ? (coach.kpis.win_rate ?? 0) : null;

  // All accounts returned by the backend (configured or not).
  const accounts: AccountLive[] = live?.accounts ?? [];
  const configuredAccounts = accounts.filter((a) => a.configured);

  // Aggregate KPIs across every configured account.
  const totalEquity = configuredAccounts.reduce((s, a) => s + (a.account?.equity ?? 0), 0);
  const totalPl = configuredAccounts.reduce((s, a) => s + (a.total_unrealized_pl ?? 0), 0);
  const totalPos = configuredAccounts.reduce((s, a) => s + (a.n_positions ?? 0), 0);
  const totalCash = configuredAccounts.reduce((s, a) => s + (a.account?.cash ?? 0), 0);
  const totalBuyingPower = configuredAccounts.reduce((s, a) => s + (a.account?.buying_power ?? 0), 0);

  // Equity curve: use the first configured account for the headline chart.
  const equityAccounts: AccountEquity[] = equity?.accounts ?? [];
  const primaryEquity = equityAccounts.find((a) => a.configured);

  const curveData = primaryEquity?.configured && primaryEquity.equity && primaryEquity.dates
    ? primaryEquity.dates.map((d, i) => ({ date: d, value: primaryEquity.equity![i] ?? 0 }))
        .filter((p) => p.value > 0)
    : [];
  const equityChange = curveData.length >= 2 ? curveData[curveData.length - 1].value - curveData[0].value : null;
  const equityChangePct = curveData.length >= 2 && curveData[0].value > 0
    ? (curveData[curveData.length - 1].value / curveData[0].value - 1) : null;

  const anyConfigured = live?.configured ?? false;

  return (
    <div style={{ maxWidth: 1280, margin: '0 auto', padding: '28px 24px 48px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 22 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-.02em', margin: 0 }}>
            Command Center
          </h1>
          <div style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 4 }}>
            Portfolio &amp; market snapshot · {configuredAccounts.length} Alpaca account{configuredAccounts.length === 1 ? '' : 's'}
          </div>
        </div>
        <span style={{
          fontSize: 11, fontWeight: 600, padding: '4px 12px', borderRadius: 999,
          background: 'var(--accent-glow)', color: 'var(--accent)',
        }}>
          {anyConfigured ? (configuredAccounts[0]?.paper ? 'Paper accounts' : 'Live accounts') : 'Read-only'}
        </span>
      </div>

      <DriftAlertStrip />

      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginTop: 18 }}>
        <Kpi label="Portfolio Value" value={fmtMoney(totalEquity, 2)}
             delta={equityChange != null ? `${equityChange >= 0 ? '▲' : '▼'} ${fmtMoney(Math.abs(equityChange), 2)}` : null}
             deltaCls={equityChange != null && equityChange >= 0 ? 'up' : equityChange != null ? 'down' : 'flat'}
             sub={equityChangePct != null ? `${fmtPct(equityChangePct)} over ${curveData.length} days` : 'loading…'} />
        <Kpi label="Day / Unrealized P&L" value={fmtMoney(totalPl, 2)}
             delta={totalPl >= 0 ? '▲' : '▼'}
             deltaCls={totalPl >= 0 ? 'up' : 'down'}
             sub={anyConfigured ? (live?.strategy_name ?? 'Alpaca') : 'Alpaca not configured'} />
        <Kpi label="Win Rate" value={winRate != null ? winRate.toFixed(1) + '%' : '—'}
             delta={coach?.kpis?.n_trades ? `${coach.kpis.n_trades} closed trades` : null}
             deltaCls="flat"
             sub={coach?.kpis?.n_trades ? fmtMoney(coach.kpis.total_pnl, 2) : 'no logged trades'} />
        <Kpi label="Active Positions" value={String(totalPos)}
             delta={anyConfigured ? `${configuredAccounts.length} account${configuredAccounts.length === 1 ? '' : 's'}` : null}
             deltaCls="flat"
             sub={anyConfigured ? `${fmtMoney(totalCash, 0)} cash` : '—'} />
      </div>

      {/* Main grid: equity curve + regime/sectors */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 14, marginTop: 14 }}>
        <Panel title="Equity Curve" caption={primaryEquity ? `${primaryEquity.label} · trailing 3 months` : 'Portfolio performance, trailing 3 months'}>
          {equity == null ? (
            <Empty>Loading equity history…</Empty>
          ) : !equity.configured ? (
            <Empty>{equity.reason ?? 'Equity history unavailable.'}</Empty>
          ) : curveData.length === 0 ? (
            <Empty>No equity history yet.</Empty>
          ) : (
            <div style={{ width: '100%', height: 240 }}>
              <ResponsiveContainer>
                <AreaChart data={curveData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.28} />
                      <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="var(--border)" vertical={false} strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--subtle)', fontFamily: 'var(--font-sf-text)' }}
                         axisLine={{ stroke: 'var(--border)' }} tickLine={false}
                         minTickGap={40} />
                  <YAxis domain={['dataMin', 'dataMax']} width={64}
                         tick={{ fontSize: 10, fill: 'var(--subtle)', fontFamily: 'var(--font-sf-text)' }}
                         axisLine={false} tickLine={false}
                         tickFormatter={(v: number) => '$' + (v / 1000).toFixed(1) + 'k'} />
                  <Tooltip
                    formatter={(value) => {
                      const v = typeof value === 'number' ? value : Number(value ?? 0);
                      return ['$' + v.toLocaleString(undefined, { maximumFractionDigits: 2 }), 'Equity'];
                    }}
                    labelStyle={{ fontFamily: 'var(--font-sf-text)', fontSize: 11 }}
                    contentStyle={{
                      background: 'var(--surface-overlay)', border: '1px solid var(--border)',
                      borderRadius: 8, color: 'var(--foreground)', fontSize: 12,
                    }}
                  />
                  <Area type="monotone" dataKey="value" stroke="var(--accent)" strokeWidth={2}
                        fill="url(#equityFill)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>

        <Panel title="Market Regime" caption="Macro environment">
          <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
            <div style={{ flex: 1, textAlign: 'center', padding: '12px 8px', borderRadius: 10, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: 10, color: 'var(--subtle)', textTransform: 'uppercase', letterSpacing: '.05em' }}>Overall</div>
              <div style={{ fontWeight: 700, marginTop: 4, color: summary.overall === 'BULL' ? 'var(--good)' : 'var(--bad)' }}>{summary.overall}</div>
            </div>
            <div style={{ flex: 1, textAlign: 'center', padding: '12px 8px', borderRadius: 10, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: 10, color: 'var(--subtle)', textTransform: 'uppercase', letterSpacing: '.05em' }}>Volatility</div>
              <div style={{ fontWeight: 700, marginTop: 4 }}>{summary.vol}</div>
            </div>
          </div>
          {sectors.length === 0 ? (
            <Empty>No regime data yet — run a Markov scan.</Empty>
          ) : (
            <div>
              {sectors.slice(0, 5).map((s) => (
                <div key={s.etf} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 0', borderBottom: '1px solid var(--border)' }}>
                  <div style={{ fontWeight: 600, fontSize: 12.5 }}>{s.etf}
                    <span style={{ display: 'block', fontSize: 10, color: 'var(--subtle)', fontWeight: 400 }}>{(s.bull_probability * 100).toFixed(0)}% bull</span>
                  </div>
                  <span style={{ fontSize: 11, fontWeight: 700, color: s.regime === 'BULL' ? 'var(--good)' : 'var(--bad)' }}>{s.regime}</span>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {/* Per-account cards */}
      <div style={{ marginTop: 14 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>Alpaca Accounts</h2>
          <span style={{ fontSize: 11, color: 'var(--subtle)' }}>{fmtMoney(totalBuyingPower, 0)} total buying power</span>
        </div>
        {!anyConfigured ? (
          <Panel title="Alpaca Accounts">
            <Empty>{live?.reason ?? 'Add Alpaca keys to the root .env to see live positions.'}</Empty>
          </Panel>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 14 }}>
            {accounts.map((a) => (
              <AccountCard key={a.label} account={a} equity={equityAccounts.find((e) => e.label === a.label)} />
            ))}
          </div>
        )}
      </div>

      {/* Sector momentum + positions table */}
      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 14, marginTop: 14 }}>
        <Panel title="Sector Momentum" caption="3-month ETF performance">
          {sectorPerf.length === 0 ? (
            <Empty>No sector data.</Empty>
          ) : (
            sectorPerf.slice(0, 8).map((s) => {
              const p = s.perf_3m ?? 0;
              return (
                <div key={s.ticker} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 0', borderBottom: '1px solid var(--border)' }}>
                  <div style={{ fontWeight: 600, fontSize: 12.5 }}>{s.ticker}
                    <span style={{ display: 'block', fontSize: 10, color: 'var(--subtle)', fontWeight: 400 }}>{s.name}</span>
                  </div>
                  <span style={{ fontSize: 11.5, fontWeight: 700, color: p >= 0 ? 'var(--good)' : 'var(--bad)' }}>
                    {p >= 0 ? '+' : ''}{fmtPct(p / 100)}
                  </span>
                </div>
              );
            })
          )}
        </Panel>

        <Panel title="Active Positions" caption={anyConfigured ? `${totalPos} open across ${configuredAccounts.length} account${configuredAccounts.length === 1 ? '' : 's'}` : 'Alpaca not configured'}>
          {!anyConfigured ? (
            <Empty>{live?.reason ?? 'Add Alpaca keys to the root .env to see live positions.'}</Empty>
          ) : totalPos === 0 ? (
            <Empty>No open positions across any account.</Empty>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
                <thead>
                  <tr>
                    {['Account', 'Symbol', 'Qty', 'Entry', 'Current', 'Market Value', 'P&L'].map((h) => (
                      <th key={h} style={{ textAlign: 'left', fontSize: 10, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--subtle)', padding: '8px 10px', borderBottom: '1px solid var(--border)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {configuredAccounts.flatMap((a) =>
                    (a.positions ?? []).map((p) => (
                      <tr key={a.label + ':' + p.ticker}>
                        <td style={{ padding: '10px', borderBottom: '1px solid var(--border)', color: 'var(--muted)' }}>{a.label}</td>
                        <td style={{ padding: '10px', borderBottom: '1px solid var(--border)', fontWeight: 700 }}>{p.ticker}</td>
                        <td style={{ padding: '10px', borderBottom: '1px solid var(--border)', color: 'var(--muted)' }}>{p.qty}</td>
                        <td style={{ padding: '10px', borderBottom: '1px solid var(--border)', color: 'var(--muted)' }}>{fmtMoney(p.avg_entry_price, 2)}</td>
                        <td style={{ padding: '10px', borderBottom: '1px solid var(--border)', color: 'var(--muted)' }}>{fmtMoney(p.current_price, 2)}</td>
                        <td style={{ padding: '10px', borderBottom: '1px solid var(--border)', color: 'var(--muted)' }}>{fmtMoney(p.market_value, 2)}</td>
                        <td style={{ padding: '10px', borderBottom: '1px solid var(--border)', fontWeight: 700, color: p.unrealized_pl >= 0 ? 'var(--good)' : 'var(--bad)' }}>
                          {fmtMoney(p.unrealized_pl, 2)} <span style={{ fontSize: 10.5, fontWeight: 600 }}>({fmtPct(p.unrealized_pl_pct)})</span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      {/* Secondary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginTop: 14 }}>
        <Panel title="Hypothesis Backlog"><HypothesisBacklogCard /></Panel>
        <Panel title="Recent Journal">
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>
            No journal entries yet. Run a Markov scan or deploy a strategy.
          </div>
        </Panel>
      </div>

      {/* Quick navigation */}
      <Panel title="Quick Navigation" style={{ marginTop: 14 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
          {NAV_TOOLS.map((tool) => (
            <Link
              key={tool.to}
              to={tool.to}
              style={{
                display: 'block', padding: '14px 16px', borderRadius: 10,
                border: '1px solid var(--border)', background: 'transparent',
                textDecoration: 'none', color: 'var(--foreground)',
                transition: 'border-color .15s ease, background .15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--accent)';
                e.currentTarget.style.background = 'var(--accent-glow)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border)';
                e.currentTarget.style.background = 'transparent';
              }}
            >
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{tool.label}</div>
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>{tool.desc}</div>
            </Link>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function AccountCard({ account, equity }: { account: AccountLive; equity?: AccountEquity }) {
  const positions: LivePosition[] = account.positions ?? [];
  const pl = account.total_unrealized_pl ?? 0;
  const plPct = account.total_unrealized_pl_pct;

  const curveData = equity?.configured && equity.equity && equity.dates
    ? equity.dates.map((d, i) => ({ date: d, value: equity.equity![i] ?? 0 })).filter((p) => p.value > 0)
    : [];

  return (
    <div style={{ padding: 20, borderRadius: 14, background: 'var(--surface)', border: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>{account.label}</div>
        {account.configured ? (
          <span style={{ fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 999, background: 'var(--accent-glow)', color: 'var(--accent)' }}>
            {account.paper ? 'Paper' : 'Live'}
          </span>
        ) : (
          <span style={{ fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 999, background: 'var(--surface-raised)', color: 'var(--subtle)' }}>
            Unconfigured
          </span>
        )}
      </div>
      <div style={{ fontSize: 11, color: 'var(--subtle)', marginBottom: 12 }}>
        {account.account_number ?? '—'}
      </div>

      {!account.configured ? (
        <Empty>{account.reason ?? 'Not configured.'}</Empty>
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 12 }}>
            <Stat label="Equity" value={fmtMoney(account.account?.equity, 2)} />
            <Stat label="Cash" value={fmtMoney(account.account?.cash, 0)} />
            <Stat label="Buying Power" value={fmtMoney(account.account?.buying_power, 0)} />
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10 }}>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>Unrealized P&amp;L</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: pl >= 0 ? 'var(--good)' : 'var(--bad)' }}>
              {fmtMoney(pl, 2)}
              {plPct != null && <span style={{ fontSize: 11, fontWeight: 600, marginLeft: 6 }}>({fmtPct(plPct)})</span>}
            </div>
          </div>

          {curveData.length > 0 && (
            <div style={{ width: '100%', height: 90, marginBottom: 12 }}>
              <ResponsiveContainer>
                <AreaChart data={curveData} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id={`eqFill-${account.label}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.25} />
                      <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <YAxis hide domain={['dataMin', 'dataMax']} />
                  <Tooltip
                    formatter={(value) => {
                      const v = typeof value === 'number' ? value : Number(value ?? 0);
                      return ['$' + v.toLocaleString(undefined, { maximumFractionDigits: 2 }), 'Equity'];
                    }}
                    labelStyle={{ fontFamily: 'var(--font-sf-text)', fontSize: 11 }}
                    contentStyle={{
                      background: 'var(--surface-overlay)', border: '1px solid var(--border)',
                      borderRadius: 8, color: 'var(--foreground)', fontSize: 12,
                    }}
                  />
                  <Area type="monotone" dataKey="value" stroke="var(--accent)" strokeWidth={1.5} fill={`url(#eqFill-${account.label})`} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          <div style={{ fontSize: 10, color: 'var(--subtle)', textTransform: 'uppercase', letterSpacing: '.08em', fontWeight: 600, marginBottom: 6 }}>
            Open Positions ({positions.length})
          </div>
          {positions.length === 0 ? (
            <Empty>No open positions.</Empty>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr>
                    {['Symbol', 'Qty', 'Entry', 'Current', 'Mkt Val', 'P&L'].map((h) => (
                      <th key={h} style={{ textAlign: 'left', fontSize: 9.5, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--subtle)', padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr key={p.ticker}>
                      <td style={{ padding: '8px', borderBottom: '1px solid var(--border)', fontWeight: 700 }}>{p.ticker}</td>
                      <td style={{ padding: '8px', borderBottom: '1px solid var(--border)', color: 'var(--muted)' }}>{p.qty}</td>
                      <td style={{ padding: '8px', borderBottom: '1px solid var(--border)', color: 'var(--muted)' }}>{fmtMoney(p.avg_entry_price, 2)}</td>
                      <td style={{ padding: '8px', borderBottom: '1px solid var(--border)', color: 'var(--muted)' }}>{fmtMoney(p.current_price, 2)}</td>
                      <td style={{ padding: '8px', borderBottom: '1px solid var(--border)', color: 'var(--muted)' }}>{fmtMoney(p.market_value, 2)}</td>
                      <td style={{ padding: '8px', borderBottom: '1px solid var(--border)', fontWeight: 700, color: p.unrealized_pl >= 0 ? 'var(--good)' : 'var(--bad)' }}>
                        {fmtMoney(p.unrealized_pl, 2)} <span style={{ fontSize: 10, fontWeight: 600 }}>({fmtPct(p.unrealized_pl_pct)})</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ padding: '10px 12px', borderRadius: 10, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
      <div style={{ fontSize: 9.5, color: 'var(--subtle)', textTransform: 'uppercase', letterSpacing: '.06em' }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700, marginTop: 3 }}>{value}</div>
    </div>
  );
}

function Kpi({ label, value, delta, deltaCls, sub }: {
  label: string; value: string; delta: string | null; deltaCls: string; sub: string;
}) {
  return (
    <div style={{
      position: 'relative', overflow: 'hidden', padding: 18, borderRadius: 14,
      background: 'var(--surface)', border: '1px solid var(--border)',
    }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: 'linear-gradient(90deg, transparent, var(--accent), transparent)', opacity: .35 }} />
      <div style={{ fontSize: 10, color: 'var(--subtle)', textTransform: 'uppercase', letterSpacing: '.08em', fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-.02em', marginTop: 7 }}>{value}</div>
      {delta && (
        <div style={{ fontSize: 12, fontWeight: 600, marginTop: 6, color: deltaCls === 'up' ? 'var(--good)' : deltaCls === 'down' ? 'var(--bad)' : 'var(--muted)' }}>
          {delta}
        </div>
      )}
      <div style={{ fontSize: 10.5, color: 'var(--subtle)', marginTop: 2 }}>{sub}</div>
    </div>
  );
}

function Panel({ title, caption, children, style }: {
  title: string; caption?: string; children: React.ReactNode; style?: React.CSSProperties;
}) {
  return (
    <div style={{ padding: 20, borderRadius: 14, background: 'var(--surface)', border: '1px solid var(--border)', ...style }}>
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
        {caption && <div style={{ fontSize: 11, color: 'var(--subtle)', marginTop: 3 }}>{caption}</div>}
      </div>
      {children}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: '28px 8px', textAlign: 'center', fontSize: 12.5, color: 'var(--subtle)' }}>
      {children}
    </div>
  );
}
