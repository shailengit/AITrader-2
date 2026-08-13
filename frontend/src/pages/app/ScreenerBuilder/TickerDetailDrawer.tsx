import { useEffect, useMemo, useState, useCallback } from 'react';
import { request } from '@/lib/api';
import {
  X,
  TrendingUp,
  ExternalLink,
  Loader2,
  Maximize2,
  Minimize2,
} from 'lucide-react';
import { CandleStickChart } from '../../../components/quantgen';
import {
  SUB_SCORE_KEYS,
  getSubScoreInputs,
  type SubScoreKey,
} from '../../../lib/subScoreInputs';
import type { IndicatorDescriptor } from '../../../types/indicators';
import {
  isOverlayColumn,
  midlineForColumn,
} from '../../../data/indicatorMap';
import TickerMetadataPanel, { type TickerDetail } from '../../../components/shared/TickerMetadataPanel';

/** Shape of a single bar from /api/screener/chart-data/{ticker}. */
interface ChartBar {
  time: number | string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  indicators?: Record<string, number | null>;
}

interface TickerDetailDrawerProps {
  ticker: string | null;
  asOfDate?: string;
  indicators: IndicatorDescriptor[];
  onClose: () => void;
  onExportToLab: (ticker: string) => void;
  onOpenInChart: (ticker: string) => void;
  /** The scan-result row for this ticker. Used to render the
   *  "Scoring breakdown" section with the 4 sub-scores and their inputs.
   *  Optional: when omitted, the breakdown section is hidden. */
  scoreRow?: ScanResultRow | null;
  /** Current base_weight (0-100). Used in the composite-score label. */
  baseWeight?: number;
}

interface ScanResultRow {
  ticker: string;
  score?: number;
  trend_score?: number;
  momentum_score?: number;
  volatility_score?: number;
  volume_score?: number;
  score_minus_return?: number;
  [key: string]: unknown;
}

const CHART_PALETTE = ['#3B82F6', '#EF4444', '#F59E0B', '#A855F7', '#10B981', '#06B6D4'];

function toEpochSeconds(t: number | string): number {
  if (typeof t === 'number') return t > 1e10 ? Math.floor(t / 1000) : t;
  // ISO yyyy-mm-dd or yyyy-mm-ddThh:mm:ss
  const d = new Date(t);
  return Math.floor(d.getTime() / 1000);
}

function transformBars(bars: ChartBar[]) {
  return bars.map((b) => ({
    time: toEpochSeconds(b.time),
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
    volume: b.volume,
  }));
}

function buildChartIndicators(
  bars: ChartBar[],
  activeIds: Set<string>,
  sourceIndicators: IndicatorDescriptor[],
): unknown[] {
  // Map the active source indicator id → series name in the chart payload.
  // The chart endpoint returns `bar.indicators[col]` keyed by the
  // backend column name (the IndicatorDescriptor.id, which is the
  // payloadKey per the screener builder convention).
  const lookup = new Map<string, IndicatorDescriptor>();
  sourceIndicators.forEach((ind) => lookup.set(ind.id, ind));

  const series: Record<string, { time: number; value: number }[]> = {};
  bars.forEach((b) => {
    if (!b.indicators) return;
    const t = toEpochSeconds(b.time);
    Object.entries(b.indicators).forEach(([key, v]) => {
      if (v == null) return;
      if (!activeIds.has(key)) return;
      if (!series[key]) series[key] = [];
      series[key].push({ time: t, value: v });
    });
  });

  return Object.entries(series).map(([key, data], i) => {
    // Extract the backend column from the payload key
    // (strip trailing __<sig> to get the column name)
    const sep = key.lastIndexOf('__');
    const column = sep > 0 ? key.slice(0, sep) : key;
    const isOverlay = isOverlayColumn(column);
    return {
      name: lookup.get(key)?.label ?? key,
      type: 'line',
      data,
      color: CHART_PALETTE[i % CHART_PALETTE.length],
      pane: isOverlay ? 'overlay' : 'oscillator',
      midline: isOverlay ? null : midlineForColumn(column),
    };
  });
}

export default function TickerDetailDrawer({
  ticker,
  asOfDate,
  indicators,
  onClose,
  onExportToLab,
  onOpenInChart,
  scoreRow = null,
  baseWeight = 60,
}: TickerDetailDrawerProps) {
  const [data, setData] = useState<TickerDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [chartBars, setChartBars] = useState<ChartBar[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [activeIndicators, setActiveIndicators] = useState<Set<string>>(
    () => new Set(indicators.map((i) => i.id)),
  );

  const colors = {
    text: 'var(--foreground)',
    muted: 'var(--muted)',
    subtle: 'var(--subtle)',
    border: 'var(--border)',
    surface: 'var(--surface)',
    surfaceRaised: 'var(--surface-raised)',
    // Card body background — slightly raised above surface for sub-score cards.
    bg: 'var(--surface-overlay)',
    accent: 'var(--accent)',
    danger: 'var(--bad)',
    warning: 'var(--bad)',
  };

  // Fetch the TickerDetail payload. Aborts in-flight request when ticker
  // changes; we never show stale data from a previous ticker.
  useEffect(() => {
    if (!ticker) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData(null);

    const params = new URLSearchParams();
    if (asOfDate) params.set('as_of_date', asOfDate);

    request<TickerDetail>(
      `/screener/ticker/${encodeURIComponent(ticker)}?${params}`,
      { signal: controller.signal },
    )
      .then((json) => {
        setData(json);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (err.name === 'AbortError') return;
        setError(err.message);
        setLoading(false);
      });

    return () => controller.abort();
  }, [ticker, asOfDate]);

  // Fetch chart data separately. Same ticker-driven lifecycle.
  useEffect(() => {
    if (!ticker) {
      setChartBars([]);
      return;
    }
    const controller = new AbortController();
    setChartLoading(true);

    // Translate each indicator's payload key (`<column>__<sig>`) back to
    // a backend column + override params. The chart endpoint expects
    // `indicators` to be a comma-separated list of column names
    // (e.g. `sma_50,sma_200`), and `overrides` to be a JSON map from
    // column → custom params (e.g. `{"sma_50":{"window":50}}`).
    const cols: string[] = [];
    const overrides: Record<string, Record<string, number>> = {};
    let maxWindow = 0;
    for (const ind of indicators) {
      // The id is a payload key: `<column>__<sig>` for tunable params,
      // or just `<column>` for default-param indicators. Strip the
      // trailing sig to recover the column.
      const lastSep = ind.id.lastIndexOf('__');
      const column = lastSep > 0 ? ind.id.slice(0, lastSep) : ind.id;
      if (!cols.includes(column)) cols.push(column);
      if (ind.params && Object.keys(ind.params).length > 0) {
        overrides[column] = ind.params;
        // Track the largest requested window so we can ask the endpoint
        // for enough history to actually compute that SMA/EMA.
        const w = (ind.params as Record<string, number>).window;
        if (typeof w === 'number' && w > maxWindow) maxWindow = w;
      }
    }
    const indicatorIds = cols.join(',');

    // The endpoint needs at least `maxWindow` rows to compute the largest
    // requested indicator (e.g. SMA 200 needs 200 bars). Add some margin
    // for visual context. Floor at 120 to keep the chart scope reasonable
    // for short-window filters (RSI, MACD, etc.).
    const days = Math.max(120, maxWindow + 30);

    const params = new URLSearchParams();
    if (indicatorIds) params.set('indicators', indicatorIds);
    params.set('days', String(days));
    if (Object.keys(overrides).length > 0) {
      params.set('overrides', JSON.stringify(overrides));
    }

    request<ChartBar[]>(
      `/screener/chart-data/${encodeURIComponent(ticker)}?${params.toString()}`,
      { signal: controller.signal },
    )
      .then((json) => {
        setChartBars(Array.isArray(json) ? json : []);
        setChartLoading(false);
      })
      .catch((err: Error) => {
        if (err.name === 'AbortError') return;
        setChartBars([]);
        setChartLoading(false);
      });

    return () => controller.abort();
  }, [ticker, indicators]);

  // Reset active indicators when the prop list changes (e.g. user picked a
  // different template). New list → all-on by default.
  useEffect(() => {
    setActiveIndicators(new Set(indicators.map((i) => i.id)));
  }, [indicators]);

  const chartIndicatorsPayload = useMemo(
    () => buildChartIndicators(chartBars, activeIndicators, indicators),
    [chartBars, activeIndicators, indicators],
  );

  const toggleIndicator = useCallback((id: string) => {
    setActiveIndicators((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  if (!ticker) return null;

  const drawerWidth = expanded ? 800 : 480;
  const chartHeight = expanded ? 260 : 100;

  // Indicator chip row above the chart
  const indicatorChips = indicators.length > 0 && (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 4,
        marginBottom: 6,
      }}
    >
      {indicators.map((ind) => {
        const active = activeIndicators.has(ind.id);
        return (
          <button
            key={ind.id}
            onClick={() => toggleIndicator(ind.id)}
            style={{
              fontSize: 10,
              fontWeight: 600,
              padding: '3px 8px',
              borderRadius: 4,
              border: `1px solid ${active ? colors.accent : colors.border}`,
              backgroundColor: active ? 'var(--accent-glow)' : 'transparent',
              color: active ? colors.accent : colors.muted,
              cursor: 'pointer',
            }}
          >
            {ind.label}
          </button>
        );
      })}
    </div>
  );

  return (
    <div
      role="dialog"
      aria-label={`Detail for ${ticker}`}
      style={{
        position: 'fixed',
        top: 0,
        right: 0,
        bottom: 0,
        width: drawerWidth,
        backgroundColor: colors.surface,
        borderLeft: `1px solid ${colors.border}`,
        zIndex: 40,
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '-8px 0 24px rgba(0,0,0,0.4)',
        transition: 'width 200ms ease',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          padding: '20px 20px 12px',
          borderBottom: `1px solid ${colors.border}`,
        }}
      >
        <div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 20,
              fontWeight: 700,
              color: colors.text,
            }}
          >
            <TrendingUp size={18} color={colors.accent} />
            {ticker.toUpperCase()}
          </div>
          <div style={{ fontSize: 12, color: colors.muted, marginTop: 2 }}>
            {data?.company_name ?? '—'} · {data?.sector ?? '—'}
          </div>
        </div>
        <button
          onClick={onClose}
          aria-label="Close detail"
          style={{
            background: 'none',
            border: `1px solid ${colors.border}`,
            borderRadius: 6,
            color: colors.muted,
            fontSize: 14,
            width: 28,
            height: 28,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <X size={14} />
        </button>
      </div>

      {/* Scrollable body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
        {/* Chart panel */}
        <div
          style={{
            backgroundColor: colors.surfaceRaised,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            padding: 10,
            marginBottom: 16,
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 6,
            }}
          >
            <span
              style={{
                fontSize: 10,
                fontWeight: 600,
                color: colors.muted,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
              }}
            >
              CHART · 120D
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                onClick={() => onOpenInChart(ticker)}
                aria-label="Open in full-page chart"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  fontSize: 10,
                  fontWeight: 600,
                  color: colors.accent,
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                <ExternalLink size={11} />
                Open in chart
              </button>
              <button
                onClick={() => setExpanded((v) => !v)}
                aria-label={expanded ? 'Shrink chart' : 'Expand chart'}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  fontSize: 10,
                  fontWeight: 600,
                  color: colors.accent,
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                {expanded ? <Minimize2 size={11} /> : <Maximize2 size={11} />}
                {expanded ? 'Shrink' : 'Expand'}
              </button>
            </div>
          </div>
          {/* Scoring breakdown — 4 sub-score cards with their raw inputs.
              Only rendered when the parent supplies a scoreRow (i.e. the
              drawer was opened from a scan-results table click). */}
          {scoreRow && (
            <div
              style={{
                padding: '12px 16px',
                borderBottom: `1px solid ${colors.border}`,
                backgroundColor: colors.surface,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  justifyContent: 'space-between',
                  marginBottom: 10,
                }}
              >
                <span style={{ fontSize: 13, fontWeight: 600, color: colors.text }}>
                  Scoring breakdown
                </span>
                <span style={{ fontSize: 11, color: colors.muted }}>
                  Composite:{' '}
                  <strong style={{ color: colors.text }}>
                    {scoreRow.score == null ? '—' : Number(scoreRow.score).toFixed(0)}
                  </strong>
                  {' · '}
                  {baseWeight}% base + {100 - baseWeight}% filter match
                </span>
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                  gap: 12,
                }}
              >
                {SUB_SCORE_KEYS.map((key: SubScoreKey) => {
                  const value = scoreRow[key];
                  const color =
                    value == null
                      ? colors.subtle
                      : Number(value) >= 70
                      ? colors.accent
                      : Number(value) >= 50
                      ? colors.warning
                      : colors.danger;
                  const inputs = getSubScoreInputs(key, scoreRow as Record<string, unknown>);
                  return (
                    <div
                      key={key}
                      style={{
                        backgroundColor: colors.bg,
                        border: `1px solid ${colors.border}`,
                        borderRadius: 8,
                        padding: '8px 10px',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'baseline',
                          justifyContent: 'space-between',
                          marginBottom: 6,
                        }}
                      >
                        <span
                          style={{
                            fontSize: 11,
                            fontWeight: 600,
                            color: colors.muted,
                            textTransform: 'uppercase',
                          }}
                        >
                          {key === 'trend_score'
                            ? 'Trend'
                            : key === 'momentum_score'
                            ? 'Momentum'
                            : key === 'volatility_score'
                            ? 'Volatility'
                            : 'Volume'}
                        </span>
                        <span
                          style={{
                            fontSize: 16,
                            fontWeight: 700,
                            color,
                            fontVariantNumeric: 'tabular-nums',
                          }}
                        >
                          {value == null ? '—' : Number(value).toFixed(0)}
                        </span>
                      </div>
                      {inputs.map((inp) => (
                        <div
                          key={inp.label}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            fontSize: 11,
                            padding: '1px 0',
                          }}
                        >
                          <span style={{ color: colors.muted }}>{inp.label}</span>
                          <span
                            style={{
                              color: colors.text,
                              fontVariantNumeric: 'tabular-nums',
                            }}
                          >
                            {inp.value == null
                              ? '—'
                              : typeof inp.value === 'number'
                              ? inp.value.toFixed(2)
                              : inp.value}
                          </span>
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {indicatorChips}
          {chartLoading && chartBars.length === 0 ? (
            <div
              style={{
                height: chartHeight,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: colors.subtle,
              }}
            >
              <Loader2
                size={20}
                style={{ animation: 'spin 1s linear infinite', marginRight: 8 }}
              />
              Loading chart...
            </div>
          ) : (
            <CandleStickChart
              data={transformBars(chartBars)}
              height={chartHeight}
              indicators={chartIndicatorsPayload as never}
              cutoffDate={asOfDate}
            />
          )}
        </div>

        {/* Metadata — extracted to TickerMetadataPanel so ChartView can share it. */}
        <TickerMetadataPanel data={data} loading={loading} error={error} variant="drawer" />
      </div>

      {/* Footer actions */}
      <div
        style={{
          display: 'flex',
          gap: 8,
          padding: '12px 20px',
          borderTop: `1px solid ${colors.border}`,
        }}
      >
        <button
          onClick={() => onExportToLab(ticker)}
          style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
            backgroundColor: colors.accent,
            color: 'var(--accent-ink)',
            border: 'none',
            padding: '10px 14px',
            borderRadius: 8,
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          <ExternalLink size={13} />
          Export to Lab
        </button>
      </div>
    </div>
  );
}
