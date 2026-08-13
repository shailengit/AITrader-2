import { useState, useMemo, useEffect } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { TrendingDown, Activity, DollarSign, ArrowLeft, Trash2 } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { clearAppReferrer } from '@/components/layout/Layout';
import { quantgen } from '@/lib/api';
import { CandleStickChart } from '@/components/quantgen/CandleStickChart';
import { SectorRegime, fetchRegimes } from '@/lib/regime';
import { IndicatorPanel } from '@/components/quantgen/IndicatorPanel';
import OptimizationResults from '@/components/quantgen/OptimizationResults';
import { TickerIdentityCard, FundamentalsPanel, ResearchPanel } from '@/components/quantgen';

interface Metric {
  label: string;
  value: string;
  vs?: { label: string; value: string; positive: boolean };
}

interface Trade {
  time: number;
  price: number;
  type: 'buy' | 'sell';
  size?: number;
  pnl?: number;
  [key: string]: any;
}

interface OHLCV {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface EquityPoint {
  time: number | string;
  value: number;
}

interface ChartIndicator {
  name: string;
  type: string;
  data: { time: number; value: number }[];
  color?: string;
}

interface PanelIndicator {
  name: string;
  type: string;
  params: Record<string, string | number>;
}

interface OptimizationData {
  mode: 'simple' | 'wfo' | 'true_wfo';
  heatmap?: any[];
  windows?: any[];
  oos_equity?: EquityPoint[];
  max_windows?: number;
  stats?: Record<string, number | string>;
  trades?: Trade[];
  equity?: EquityPoint[];
  ohlcv?: OHLCV[];
  indicators?: PanelIndicator[];
}

interface DashboardData {
  stats: Record<string, number | string>;
  equity: EquityPoint[];
  ohlcv: OHLCV[];
  optimization: OptimizationData | null;
  output: string;
  drawdownData: Array<{ time: number; drawdown: number; bench_drawdown: number }>;
  trades: Trade[];
  indicators: PanelIndicator[];
  benchmark_equity: EquityPoint[];
}

export default function Dashboard() {
  const [data] = useState<DashboardData>(() => {
    try {
      const storedRunData = localStorage.getItem('lastRunData');
      if (storedRunData) {
        const parsed = JSON.parse(storedRunData);
        let drawdownData: DashboardData['drawdownData'] = [];
        if (parsed.drawdown) {
          const dd = parsed.drawdown;
          const bdd = parsed.benchmark_drawdown || {};
          const parseTs = (key: string | number): number => {
            if (typeof key === 'number') return key;
            // Numeric strings from the backend often carry a trailing ".0"
            // (e.g. "1577923200.0") because the drawdown dict is keyed by
            // float timestamps. String(n) !== key in that case, so parse
            // numerically first and only fall back to date parsing otherwise.
            const n = Number(key);
            if (!isNaN(n) && isFinite(n) && n > 0) return n;
            const parsedDate = Date.parse(key);
            return isNaN(parsedDate) ? 0 : Math.floor(parsedDate / 1000);
          };
          const allDates = Array.from(new Set([...Object.keys(dd), ...Object.keys(bdd)]))
            .sort((a, b) => parseTs(a) - parseTs(b));
          drawdownData = allDates.map((dateStr) => {
            const ts = parseTs(dateStr);
            return {
              time: ts,
              dateStr: new Date(ts * 1000).toISOString().split('T')[0],
              drawdown: dd[dateStr] != null ? Number(dd[dateStr]) : 0,
              bench_drawdown: bdd[dateStr] != null ? Number(bdd[dateStr]) : 0,
            };
          });
        }
        return {
          stats: parsed.stats || {},
          equity: parsed.equity || [],
          ohlcv: parsed.ohlcv || [],
          optimization: parsed.optimization || null,
          output: parsed.output || '',
          drawdownData,
          trades: parsed.trades || [],
          indicators: parsed.indicators || [],
          tickers: parsed.tickers || [],
          benchmark_equity: parsed.optimization?.benchmark_equity || parsed.benchmark_equity || [],
        };
      }
      const storedStats = localStorage.getItem('lastRunStats');
      if (storedStats) {
        return {
          stats: JSON.parse(storedStats),
          equity: JSON.parse(localStorage.getItem('lastRunEquity') || '[]'),
          ohlcv: [], optimization: null, output: '', drawdownData: [], trades: [], indicators: [], benchmark_equity: [],
        };
      }
    } catch {}
    return {
      stats: {}, equity: [], ohlcv: [], optimization: null, output: '', drawdownData: [], trades: [], indicators: [], benchmark_equity: [],
    };
  });

  const { stats, equity, ohlcv, drawdownData, optimization, output, trades, indicators, benchmark_equity } = data;

  // Extract primary ticker from stored run data or fallback to output/code parsing
  const primaryTicker = useMemo(() => {
    const stored = (data as any)?.tickers;
    if (stored && Array.isArray(stored) && stored.length > 0) {
      return stored[0].toUpperCase();
    }
    // Fallback: try to extract from output text
    const match = output?.match(/ticker\s*=\s*['"]([A-Z]+)['"]/i);
    if (match) return match[1].toUpperCase();
    return 'AAPL';
  }, [(data as any)?.tickers, output]);

  // Fundamentals state
  const [tickerInfo, setTickerInfo] = useState<any>(null);
  const [tickerInfoLoading, setTickerInfoLoading] = useState(false);

  // Research state
  const [researchData, setResearchData] = useState<any>(null);
  const [researchLoading, setResearchLoading] = useState(false);
  const [researchMode, setResearchMode] = useState<'simulated' | 'live'>('simulated');

  // Regime overlay state. `showRegimeOverlay` gates the chart's green/red
  // regime badge; `regimes` is the SectorRegime[] payload fed to the chart's
  // `regimeBands` prop. Fetched once on mount from /api/markov/regimes.
  const [showRegimeOverlay, setShowRegimeOverlay] = useState(false);
  const [regimes, setRegimes] = useState<SectorRegime[]>([]);
  useEffect(() => {
    fetchRegimes()
      .then(setRegimes)
      .catch(() => setRegimes([]));
  }, []);

  // Load cached research from localStorage on mount
  useEffect(() => {
    if (!primaryTicker) return;
    const cacheKey = `research_${primaryTicker}_${researchMode}`;
    try {
      const cached = localStorage.getItem(cacheKey);
      if (cached) {
        const parsed = JSON.parse(cached);
        if (parsed && parsed.data) {
          setResearchData(parsed.data);
        }
      }
    } catch {
      // ignore corrupt cache
    }
  }, [primaryTicker]);

  // Fetch fundamentals on mount (fast)
  useEffect(() => {
    if (!primaryTicker) return;

    const fetchTickerInfo = async () => {
      setTickerInfoLoading(true);
      try {
        const json = await quantgen.tickerInfo(primaryTicker);
        if (json.success && json.data) {
          setTickerInfo(json.data);
        }
      } catch (e) {
        console.error('Failed to fetch ticker info:', e);
      } finally {
        setTickerInfoLoading(false);
      }
    };

    fetchTickerInfo();
  }, [primaryTicker]);

  const runResearch = (mode: string) => {
    setResearchMode(mode as 'simulated' | 'live');
    setResearchData(null);
    setResearchLoading(true);
    quantgen.researchTicker(primaryTicker, mode)
      .then((json) => {
        if (json.success && json.data) {
          setResearchData(json.data);
          // Cache result in localStorage
          try {
            localStorage.setItem(`research_${primaryTicker}_${mode}`, JSON.stringify({ data: json.data, timestamp: Date.now() }));
          } catch {
            // ignore quota errors
          }
        }
      })
      .catch((e) => console.error('Research fetch failed:', e))
      .finally(() => setResearchLoading(false));
  };

  const handleRegenerateResearch = (mode: string) => {
    runResearch(mode);
  };

  const [selIndicators, setSelIndicators] = useState<Record<string, boolean>>({});

  useState(() => {
    if (indicators?.length) {
      const initial: Record<string, boolean> = {};
      indicators.forEach((ind) => { initial[ind.name] = true; });
      setSelIndicators(initial);
    }
  });

  const handleIndicatorToggle = (name: string) => {
    setSelIndicators((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  const bestTrades = optimization?.trades?.length ? optimization.trades : trades;
  const bestStats = optimization?.stats && Object.keys(optimization.stats).length > 0 ? optimization.stats : stats;

  const equityWithBenchmark = useMemo(() => {
    if (!equity?.length) return equity;

    // Prefer backend-computed benchmark equity (correctly aligned to actual test period)
    if (benchmark_equity?.length > 0) {
      const benchByDay = new Map<number, number>();
      benchmark_equity.forEach((p) => {
        if (p && typeof p.time === 'number' && !isNaN(p.time)) {
          // Normalize to start of day in UTC to handle timezone/time-of-day mismatches
          const dayKey = Math.floor(p.time / 86400) * 86400;
          benchByDay.set(dayKey, p.value);
        }
      });
      return equity.map((item) => {
        const itemTime = typeof item.time === 'number' ? item.time : Date.parse(item.time) / 1000;
        const dayKey = Math.floor(itemTime / 86400) * 86400;
        return {
          time: itemTime,
          value: item.value,
          benchmark: benchByDay.get(dayKey) ?? null,
        };
      });
    }

    // Fallback: recompute from OHLCV (only valid when equity and ohlcv share the same timeline)
    if (!ohlcv?.length) {
      return equity.map((item) => ({
        time: typeof item.time === 'number' ? item.time : Date.parse(item.time) / 1000,
        value: item.value,
        benchmark: null,
      }));
    }
    try {
      const startValue = equity[0]?.value || 10000;
      const closePrices = ohlcv.map((d) => d.close);
      const benchmark = [1];
      for (let i = 1; i < closePrices.length; i++) {
        benchmark.push(benchmark[i - 1] * (1 + (closePrices[i] - closePrices[i - 1]) / closePrices[i - 1]));
      }
      return equity.map((item, index) => {
        const itemTime = typeof item.time === 'number' ? item.time : Date.parse(item.time) / 1000;
        return {
          time: itemTime,
          value: item.value,
          benchmark: benchmark[index] ? benchmark[index] * startValue : null,
        };
      });
    } catch { return equity; }
  }, [equity, benchmark_equity, ohlcv]);

  const getVal = (keys: string[]) => {
    if (!bestStats) return undefined;
    for (const k of keys) { if (bestStats[k] !== undefined) return bestStats[k]; }
    return undefined;
  };

  const fmtPct = (val: number | string | undefined) => {
    if (val === undefined || val === null) return 'N/A';
    if (typeof val === 'string' && val.includes('%')) return val;
    const v = parseFloat(val as string);
    return isNaN(v) ? String(val) : `${v.toFixed(2)}%`;
  };

  const fmtNum = (val: number | string | undefined) =>
    val !== undefined && val !== null ? parseFloat(val as string).toFixed(2) : 'N/A';

  const metrics: Metric[] = [
    {
      label: 'Total Return',
      value: fmtPct(getVal(['Total Return [%]', 'Total Return'])),
      vs: {
        label: 'Benchmark',
        value: fmtPct(getVal(['Benchmark Return [%]', 'Benchmark Return', 'Benchmark Total Return [%]', 'Benchmark Total Return'])),
        positive: parseFloat(getVal(['Total Return [%]', 'Total Return']) as string || '0') > parseFloat(getVal(['Benchmark Return [%]', 'Benchmark Return']) as string || '0'),
      },
    },
    {
      label: 'Sharpe Ratio',
      value: fmtNum(getVal(['Sharpe Ratio', 'Sharpe'])),
      vs: {
        label: 'Benchmark',
        value: fmtNum(getVal(['Benchmark Sharpe Ratio', 'Benchmark Sharpe', 'Benchmark Sharpe Ratio '])),
        positive: parseFloat(getVal(['Sharpe Ratio', 'Sharpe']) as string || '0') > parseFloat(getVal(['Benchmark Sharpe Ratio', 'Benchmark Sharpe']) as string || '0'),
      },
    },
    {
      label: 'Max Drawdown',
      value: fmtPct(getVal(['Max Drawdown [%]', 'Max Drawdown'])),
      vs: {
        label: 'Benchmark',
        value: fmtPct(getVal(['Benchmark Max Drawdown [%]', 'Benchmark Max Drawdown', 'Benchmark Max Drawdown [%] '])),
        positive: parseFloat(getVal(['Max Drawdown [%]', 'Max Drawdown']) as string || '0') < parseFloat(getVal(['Benchmark Max Drawdown [%]', 'Benchmark Max Drawdown']) as string || '0'),
      },
    },
    {
      label: 'Win Rate',
      value: fmtPct(getVal(['Win Rate [%]', 'Win Rate'])),
      vs: { label: 'Trades', value: String(getVal(['Total Trades']) || '0'), positive: parseFloat(getVal(['Win Rate [%]', 'Win Rate']) as string || '0') > 50 },
    },
  ];

  const hasOptimizationData = optimization && (
    (optimization.oos_equity && optimization.oos_equity.length > 0) ||
    (optimization.windows && optimization.windows.length > 0)
  );
  const hasData = (equity && equity.length > 0) || hasOptimizationData;
  const startDt = getVal(['Start', 'Start Date']);
  const endDt = getVal(['End', 'End Date']);

  // Compute unified x-axis range for all charts based on backtest start/end dates.
  // Falls back to the min/max time present in the data if stats are unavailable.
  const allTimes = [
    ...(ohlcv?.map((d) => d.time) || []),
    ...(equity?.map((d) => (typeof d.time === 'number' ? d.time : Date.parse(d.time) / 1000)) || []),
    ...(drawdownData?.map((d) => d.time) || []),
  ].filter((t) => typeof t === 'number' && !isNaN(t));

  const dataMinTime = allTimes.length ? Math.min(...allTimes) : undefined;
  const dataMaxTime = allTimes.length ? Math.max(...allTimes) : undefined;

  const parseStatDate = (dateStr: string | number | undefined): number | undefined => {
    if (dateStr === undefined || dateStr === null || dateStr === '') return undefined;
    const parsed = Date.parse(String(dateStr));
    return isNaN(parsed) ? undefined : Math.floor(parsed / 1000);
  };

  // Prefer data-derived UTC timestamps for the visible range. Candle and
  // equity times are UTC seconds, while stat dates are naive strings that
  // Date.parse() reads as local time — using those shifts the window and
  // clips the first candle(s) in non-UTC timezones (e.g. the price chart
  // starting a day late). Fall back to stat dates only when no data exists.
  const chartStart = dataMinTime ?? parseStatDate(startDt);
  const chartEnd = dataMaxTime ?? parseStatDate(endDt);

  const timeDomain: [number, number] | ['auto', 'auto'] =
    chartStart !== undefined && chartEnd !== undefined
      ? [chartStart, chartEnd]
      : ['auto', 'auto'];

  const clearResults = () => {
    localStorage.removeItem('lastRunData');
    localStorage.removeItem('lastRunStats');
    localStorage.removeItem('lastRunEquity');
    window.location.reload();
  };

  if (!hasData) {
    return (
      <div style={{ minHeight: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'var(--canvas)' }}>
        <div style={{ textAlign: 'center' }}>
          <h2 style={{ fontSize: '22px', fontWeight: 700, color: 'var(--foreground)', marginBottom: '8px' }}>No Results Yet</h2>
          <p style={{ color: 'var(--muted)', marginBottom: '24px', fontSize: '14px' }}>Run a backtest or optimization to see results here.</p>
          <NavLink
            to="/quantgen/build"
            style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '10px 24px', borderRadius: '999px', fontWeight: 600, fontSize: '14px', textDecoration: 'none', backgroundColor: 'var(--accent)', color: 'var(--accent-ink)' }}
          >
            <ArrowLeft size={16} />
            Go to Builder
          </NavLink>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100%', backgroundColor: 'var(--canvas)' }}>
      <div style={{ padding: '24px 80px 64px' }}>
        <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
            <div>
              <h1 style={{ fontSize: '24px', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--foreground)' }}>
                Performance Analysis
              </h1>
              <p style={{ fontSize: '13px', color: 'var(--muted)', marginTop: '2px' }}>
                {startDt ? `${String(startDt).split(' ')[0]}  ${String(endDt || '').split(' ')[0]}` : ''}
              </p>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <NavLink
                to='/quantgen/build'
                onClick={() => clearAppReferrer()}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '6px 12px',
                  fontSize: '12px',
                  borderRadius: '8px',
                  fontWeight: 600,
                  textDecoration: 'none',
                  backgroundColor: 'rgba(16, 185, 129, 0.1)',
                  border: '1px solid rgba(16, 185, 129, 0.2)',
                  color: 'var(--accent)',
                }}
              >
                <ArrowLeft size={14} />
                Back to Builder
              </NavLink>
              <span
                style={{
                  fontSize: '12px',
                  padding: '4px 14px',
                  borderRadius: '999px',
                  fontWeight: 600,
                  backgroundColor: 'rgba(16, 185, 129, 0.1)',
                  border: '1px solid rgba(16, 185, 129, 0.2)',
                  color: 'var(--accent)',
                }}
              >
                {optimization
                  ? optimization.mode === 'true_wfo' ? 'True WFO'
                  : optimization.mode === 'wfo' ? 'WFO'
                  : 'Optimized'
                  : 'Backtest'}
              </span>
              <button
                onClick={clearResults}
                style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 12px', fontSize: '12px', borderRadius: '8px', border: 'none', background: 'none', color: 'var(--bad)', cursor: 'pointer' }}
              >
                <Trash2 size={13} /> Clear
              </button>
            </div>
          </div>

          {/* Ticker Identity Card */}
          <TickerIdentityCard
            ticker={primaryTicker}
            name={tickerInfo?.metadata?.name}
            sector={tickerInfo?.metadata?.sector}
            industry={tickerInfo?.metadata?.industry}
            marketCap={tickerInfo?.metadata?.market_cap}
            beta={tickerInfo?.metadata?.beta}
            latestPrice={tickerInfo?.latest_price}
          />

          {/* Optimization Results */}
          {optimization && (
            <div style={{ marginBottom: '24px' }}>
              <OptimizationResults data={optimization} />
              <div style={{ margin: '24px 0', borderTop: '1px solid var(--border)' }} />
              <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--muted)', marginBottom: '16px', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                Backtest Details (Best / Last Run)
              </h3>
            </div>
          )}

          {/* Compact stat row — replaces hero-metric cards */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: '12px',
              marginBottom: '24px',
            }}
          >
            {metrics.map((m) => (
              <div
                key={m.label}
                style={{
                  padding: '16px 20px',
                  borderRadius: '14px',
                  backgroundColor: 'var(--surface)',
                  border: '1px solid var(--border)',
                }}
              >
                <div style={{ fontSize: '11px', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: '6px' }}>
                  {m.label}
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--foreground)', letterSpacing: '-0.02em', fontVariantNumeric: 'tabular-nums' }}>
                  {m.value}
                </div>
                {m.vs && (
                  <div style={{ fontSize: '12px', marginTop: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span style={{ color: 'var(--subtle)' }}>{m.vs.label}:</span>
                    <span style={{ color: m.vs.positive ? 'var(--accent)' : 'var(--bad)', fontWeight: 600 }}>
                      {m.vs.value}
                    </span>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Fundamentals Panel */}
          <FundamentalsPanel data={tickerInfo} isLoading={tickerInfoLoading} />

          {/* Two-Column: Charts + Stats */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: '20px' }}>
            {/* Left: Charts */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {/* Price Chart */}
              <div
                style={{
                  borderRadius: '14px',
                  padding: '20px',
                  backgroundColor: 'var(--surface)',
                  border: '1px solid var(--border)',
                  display: 'flex',
                  flexDirection: 'column',
                }}
              >
                <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--foreground)', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <DollarSign size={14} style={{ color: 'var(--accent)' }} /> Price Action & Volume
                  <label
                    style={{
                      marginLeft: 'auto',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      cursor: 'pointer',
                      fontSize: '12px',
                      fontWeight: 600,
                      color: 'var(--subtle)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.08em',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={showRegimeOverlay}
                      onChange={(e) => setShowRegimeOverlay(e.target.checked)}
                      style={{ width: '14px', height: '14px', cursor: 'pointer', accentColor: 'var(--accent)' }}
                    />
                    Regime Overlay
                  </label>
                </h3>
                {indicators?.length > 0 && (
                  <IndicatorPanel indicators={indicators} selectedIndicators={selIndicators} onToggle={handleIndicatorToggle} />
                )}
                <div style={{ borderRadius: '10px', overflow: 'hidden', backgroundColor: 'var(--canvas)', height: '360px', position: 'relative' }}>
                  {ohlcv?.length > 0 ? (
                    (() => {
                      const chartTrades = bestTrades.map((t) => ({
                        time: t.time ?? (t.date ? new Date(t.date).getTime() / 1000 : 0),
                        price: t.price,
                        type: t.action === 'BUY' ? 'buy' : t.action === 'SELL' ? 'sell' : t.type,
                        size: t.size || 0,
                        pnl: t.pnl || 0,
                      }));
                      const chartIndicators: ChartIndicator[] = indicators
                        .filter((ind) => selIndicators[ind.name] !== false)
                        .map((ind) => ({ name: ind.name, type: ind.type, data: [], color: `hsl(${(ind.name.length * 137.508) % 360}, 70%, 50%)` }));
                      return (
                        <CandleStickChart
                          data={ohlcv}
                          trades={chartTrades}
                          indicators={chartIndicators}
                          height={360}
                          visibleRange={
                            timeDomain[0] !== 'auto'
                              ? { from: timeDomain[0], to: timeDomain[1] }
                              : undefined
                          }
                          regimeBands={regimes}
                          showRegimeOverlay={showRegimeOverlay}
                        />
                      );
                    })()
                  ) : (
                    <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', fontSize: '13px' }}>
                      No OHLCV data available
                    </div>
                  )}
                </div>
              </div>

              {/* Equity Curve */}
              <div style={{ borderRadius: '14px', padding: '20px', backgroundColor: 'var(--surface)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column' }}>
                <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--foreground)', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Activity size={14} style={{ color: 'var(--accent)' }} /> Equity Curve
                </h3>
                <div style={{ height: '240px' }}>
                  <ResponsiveContainer width="99%" height="100%">
                    <AreaChart data={equityWithBenchmark}>
                      <defs>
                        <linearGradient id="colorVal" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                          <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.3} vertical={false} />
                      <XAxis
                        dataKey="time"
                        type="number"
                        domain={timeDomain}
                        allowDataOverflow
                        tick={{ fontSize: 10, fill: 'var(--muted)' }}
                        tickFormatter={(v) => typeof v === 'number' ? new Date(v * 1000).toISOString().split('T')[0] : String(v).split(' ')[0]}
                        minTickGap={50}
                      />
                      <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10, fill: 'var(--muted)' }} />
                      <Tooltip contentStyle={{ backgroundColor: 'var(--surface)', borderColor: 'var(--border)', borderRadius: '8px' }} labelFormatter={(v) => typeof v === 'number' ? new Date(v * 1000).toISOString().split('T')[0] : String(v).split(' ')[0]} />
                      <Area type="monotone" dataKey="value" stroke="#10b981" strokeWidth={2} fill="url(#colorVal)" name="Strategy" />
                      {(benchmark_equity?.length > 0 || ohlcv?.length > 0) && <Area type="monotone" dataKey="benchmark" stroke="#22c55e" strokeWidth={1.5} fill="none" strokeDasharray="4 3" name="Buy & Hold" opacity={0.6} />}
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Drawdown */}
              <div style={{ borderRadius: '14px', padding: '20px', backgroundColor: 'var(--surface)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column' }}>
                <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--bad)', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <TrendingDown size={14} /> Drawdown Analysis
                </h3>
                <div style={{ height: '200px' }}>
                  <ResponsiveContainer width="99%" height="100%">
                    <AreaChart data={drawdownData}>
                      <defs>
                        <linearGradient id="colorDD" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.1} />
                          <stop offset="95%" stopColor="#f43f5e" stopOpacity={0.3} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.2} vertical={false} />
                      <XAxis
                        dataKey="time"
                        type="number"
                        domain={timeDomain}
                        allowDataOverflow
                        tick={{ fontSize: 10, fill: 'var(--muted)' }}
                        tickFormatter={(v) => new Date((typeof v === 'number' ? v : parseFloat(v)) * 1000).toISOString().split('T')[0]}
                        minTickGap={50}
                      />
                      <YAxis tick={{ fontSize: 10, fill: 'var(--muted)' }} />
                      <Tooltip contentStyle={{ backgroundColor: 'var(--surface)', borderColor: 'var(--border)', borderRadius: '8px' }} />
                      <Area type="monotone" dataKey="drawdown" name="Strategy DD%" stroke="#f43f5e" fill="url(#colorDD)" strokeWidth={2} />
                      <Area type="monotone" dataKey="bench_drawdown" name="Benchmark DD%" stroke="#9ca3af" fill="transparent" strokeDasharray="3 3" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

            {/* Right: Stats Panel */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {/* Detailed Stats */}
              <div style={{ borderRadius: '14px', padding: '20px', backgroundColor: 'var(--surface)', border: '1px solid var(--border)' }}>
                <h3 style={{ fontSize: '12px', fontWeight: 600, color: 'var(--foreground)', marginBottom: '12px', letterSpacing: '0.02em' }}>
                  Detailed Statistics
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  {Object.entries(stats).filter(([k]) => k !== 'Total Return' && k !== 'Sharpe Ratio').map(([k, v], i) => (
                    <div
                      key={k}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        padding: '8px 0',
                        fontSize: '12px',
                        borderBottom: i < Object.keys(stats).length - 1 ? '1px solid var(--border)' : 'none',
                      }}
                    >
                      <span style={{ color: 'var(--muted)' }}>{k}</span>
                      <span style={{ color: 'var(--foreground)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                        {typeof v === 'number' ? v.toFixed(2) : String(v)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Raw Data */}
              <details style={{ borderRadius: '14px', padding: '16px 20px', backgroundColor: 'var(--surface)', border: '1px solid var(--border)' }}>
                <summary style={{ fontSize: '11px', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--muted)', cursor: 'pointer' }}>
                  Raw Data & Logs
                </summary>
                <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div>
                    <h4 style={{ fontSize: '11px', fontWeight: 600, color: 'var(--muted)', marginBottom: '6px' }}>Stats JSON</h4>
                    <pre style={{ padding: '12px', borderRadius: '8px', overflow: 'auto', fontSize: '11px', lineHeight: 1.5, backgroundColor: 'var(--canvas)', color: 'var(--muted)', maxHeight: '200px' }}>
                      {JSON.stringify(stats || {}, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <h4 style={{ fontSize: '11px', fontWeight: 600, color: 'var(--muted)', marginBottom: '6px' }}>Execution Log</h4>
                    <pre style={{ padding: '12px', borderRadius: '8px', overflow: 'auto', fontSize: '11px', lineHeight: 1.5, backgroundColor: 'var(--canvas)', color: 'var(--accent)', maxHeight: '200px', whiteSpace: 'pre-wrap' }}>
                      {output || 'No output logs captured.'}
                    </pre>
                  </div>
                </div>
              </details>
            </div>
          </div>

          {/* Research Intelligence Panel */}
          <ResearchPanel
            data={researchData}
            isLoading={researchLoading}
            onRegenerate={handleRegenerateResearch}
          />
        </div>
      </div>
    </div>
  );
}
