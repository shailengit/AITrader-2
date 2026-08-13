import { useState, useEffect, useCallback, useMemo } from 'react';
import { request } from '@/lib/api';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { recordAppReferrer } from '../../../components/layout/Layout';
import type { TickerDetail } from '../../../components/shared/TickerMetadataPanel';
import {
  catalogEntryToColumn,
  catalogParamsToBackendParams,
  chartPayloadKey,
  isOverlayColumn,
  midlineForColumn,
} from '../../../data/indicatorMap';
import type { IndicatorDescriptor } from '../../../types/indicators';
import { CandleStickChart } from '../../../components/quantgen';
import MetadataRail from './ChartView/MetadataRail';
import IndicatorPickerPanel from './ChartView/IndicatorPickerPanel';
import DateRangeBar, { type RangeMode } from './ChartView/DateRangeBar';
import OverlaysList from './ChartView/OverlaysList';

interface ChartBar {
  time: number | string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  indicators?: Record<string, number | null>;
}

const RANGE_DAYS: Record<Exclude<RangeMode, 'custom'>, number> = {
  '1y': 365,
  '2y': 730,
  '3y': 1095,
  '5y': 1825,
  max: 10000,
};

const CHART_PALETTE = ['#3B82F6', '#EF4444', '#F59E0B', '#A855F7', '#10B981', '#06B6D4', '#EC4899', '#84CC16'];

function toEpochSeconds(t: number | string): number {
  if (typeof t === 'number') return t > 1e10 ? Math.floor(t / 1000) : t;
  return Math.floor(new Date(t).getTime() / 1000);
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

/**
 * Parse the `overlays`, `labels`, and `params` query params back into
 * IndicatorDescriptors. `labels` is a parallel comma-separated array
 * of the friendly column headers (e.g. "SMA 50", "SMA 200") and takes
 * precedence over the column-derived fallback. `params` is a JSON map
 * from overlay id → params dict, and is also used to derive a label
 * for catalog-style ids (`ta__<Name>__<sig>`).
 */
function parseOverlaysFromUrl(
  overlaysParam: string | null,
  labelsParam: string | null,
  paramsParam: string | null,
): IndicatorDescriptor[] {
  if (!overlaysParam) return [];
  const ids = overlaysParam.split(',').filter(Boolean);
  const labels = labelsParam ? labelsParam.split(',') : [];
  let paramMap: Record<string, Record<string, number>> = {};
  if (paramsParam) {
    try {
      paramMap = JSON.parse(paramsParam);
    } catch {
      paramMap = {};
    }
  }
  return ids.map((id, i) => {
    // 1) Parallel-array label wins (preferred — matches the column
    //    header the user saw in the screener results table).
    // 2) params map entry (caller may have supplied a label there).
    // 3) Catalog-style id: derive a label from the params.
    // 4) Fallback: derive a label from the id itself.
    const fromParams = paramMap[id];
    const label =
      labels[i] ||
      (fromParams ? deriveLabel(id, fromParams) : deriveLabel(id, {}));
    return {
      id,
      label,
      params: fromParams,
    };
  });
}

/** Best-effort label for an id+params pair, e.g. "EMA (200)" or "MACD (12,26,9)".
 *  Falls back to the column name formatted for display if the id is
 *  not a catalog id (e.g. "trend_sma_slow" → "SMA"). */
const COLUMN_FRIENDLY: Record<string, string> = {
  trend_sma_slow: 'SMA',
  trend_sma_fast: 'SMA',
  trend_ema_fast: 'EMA',
  trend_ema_slow: 'EMA',
  sma_50: 'SMA 50',
  sma_100: 'SMA 100',
  sma_200: 'SMA 200',
  ema_20: 'EMA 20',
  ema_50: 'EMA 50',
  ema_200: 'EMA 200',
  momentum_rsi: 'RSI',
  trend_macd: 'MACD',
  trend_adx: 'ADX',
  momentum_wr: 'Williams %R',
  momentum_stoch_rsi: 'Stoch RSI',
  momentum_roc: 'ROC',
  momentum_ao: 'AO',
  momentum_kama: 'KAMA',
  volatility_bbm: 'BB Middle',
  volatility_atr: 'ATR',
};

function deriveLabel(id: string, params: Record<string, number>): string {
  // The id may be a catalog id (ta__<Name>__<sig>) or a payload key
  // (sma_50__window50) or a plain backend column (trend_sma_slow).
  // 1. Catalog id: use the catalog name.
  const catMatch = /^ta__([^_]+(?:_[^_]+?)*?)__/.exec(id);
  if (catMatch) {
    const paramList = Object.values(params);
    return paramList.length > 0
      ? `${catMatch[1]} (${paramList.join(',')})`
      : catMatch[1];
  }
  // 2. Strip the trailing __<sig> to get the column.
  const sep = id.lastIndexOf('__');
  const column = sep > 0 ? id.slice(0, sep) : id;
  const friendly = COLUMN_FRIENDLY[column];
  if (friendly) {
    // If the params specify a window, append it.
    if (params.window != null) return `${friendly} (${params.window})`;
    return friendly;
  }
  // 3. Fallback: humanize the column name.
  return column.replace(/_/g, ' ').toUpperCase();
}

interface ChartViewProps {
  /** Label for the back button. Default: "Back to results" */
  backLabel?: string;
  /** Path the back button navigates to. Default: "/screener/build" */
  backPath?: string;
  /** Referrer path for the Layout's back-navigation. Default: "/screener/build" */
  referrerPath?: string;
  /** Referrer label for the Layout's back-navigation. Default: "Custom Screener" */
  referrerLabel?: string;
}

/**
 * Full-page chart view for a single ticker. Reached from the drawer's
 * "Open in chart" button. URL is the source of truth for overlays and
 * date range; the chart refetches whenever either changes.
 */
export default function ChartView({
  backLabel = 'Back to results',
  backPath = '/screener/build',
  referrerPath = '/screener/build',
  referrerLabel = 'Custom Screener',
}: ChartViewProps) {
  const { ticker: tickerParam } = useParams<{ ticker: string }>();
  const ticker = (tickerParam ?? '').toUpperCase();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  // URL-driven state
  const rangeMode = (searchParams.get('range') ?? '1y') as RangeMode;
  const customStart = searchParams.get('start') ?? '';
  const customEnd = searchParams.get('end') ?? '';
  const fromDate = searchParams.get('from') ?? undefined;

  const overlays: IndicatorDescriptor[] = useMemo(
    () => parseOverlaysFromUrl(
      searchParams.get('overlays'),
      searchParams.get('labels'),
      searchParams.get('params'),
    ),
    [searchParams],
  );

  // Per-overlay visibility. Each overlay starts visible. Toggling does
  // not affect the URL — it's a transient view-state. The set is
  // re-seeded when the overlay list changes (e.g. user adds a new
  // overlay from the picker or removes one).
  const [activeIds, setActiveIds] = useState<Set<string>>(
    () => new Set(overlays.map((o) => o.id)),
  );
  useEffect(() => {
    setActiveIds((prev) => {
      const next = new Set<string>();
      for (const o of overlays) {
        if (prev.has(o.id)) next.add(o.id);
        else next.add(o.id); // new overlays default to visible
      }
      return next;
    });
  }, [overlays]);

  // Metadata (left rail)
  const [metaData, setMetaData] = useState<TickerDetail | null>(null);
  const [metaLoading, setMetaLoading] = useState(false);
  const [metaError, setMetaError] = useState<string | null>(null);

  // Chart
  const [chartBars, setChartBars] = useState<ChartBar[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);

  const colors = {
    text: 'var(--foreground)',
    muted: 'var(--muted)',
    subtle: 'var(--subtle)',
    border: 'var(--border)',
    surface: 'var(--surface)',
    surfaceRaised: 'var(--surface-raised)',
    canvas: 'var(--canvas)',
    accent: 'var(--accent)',
  };

  // Record this page's parent as the back-navigation target. The
  // Layout's header "Back to Custom Screener" button uses the value
  // here to return to /screener/build with the same scan state. We do
  // NOT clear on unmount — the chart view is part of the screener
  // subtree, so the referrer is the same whether the user is on
  // /screener/build or /screener/build/chart/:ticker.
  useEffect(() => {
    recordAppReferrer(referrerPath, referrerLabel);
  }, []);

  // Metadata fetch
  useEffect(() => {
    if (!ticker) return;
    const controller = new AbortController();
    setMetaLoading(true);
    setMetaError(null);
    setMetaData(null);
    const params = new URLSearchParams();
    if (fromDate) params.set('as_of_date', fromDate);
    request<TickerDetail>(
      `/screener/ticker/${encodeURIComponent(ticker)}?${params}`,
      { signal: controller.signal },
    )
      .then((json) => {
        setMetaData(json);
        setMetaLoading(false);
      })
      .catch((err: Error) => {
        if (err.name === 'AbortError') return;
        setMetaError(err.message);
        setMetaLoading(false);
      });
    return () => controller.abort();
  }, [ticker, fromDate]);

  // Chart fetch — keyed on ticker, range, and overlays
  useEffect(() => {
    if (!ticker) return;
    const controller = new AbortController();
    setChartLoading(true);
    setChartError(null);

    const cols: string[] = [];
    const overrides: Record<string, Record<string, number>> = {};
    for (const ov of overlays) {
      // Resolve id → column + params. The id may be:
      //  - a catalog id (`ta__<Name>__<sig>`) — translate the catalog name
      //    to its backend column via `catalogEntryToColumn`.
      //  - a plain backend column name (the new openChartView URL format).
      let column = ov.id;
      let params = ov.params;
      const m = /^ta__(.+)__/.exec(ov.id);
      if (m) {
        const catalogName = m[1];
        column = catalogEntryToColumn(catalogName);
        if (params) {
          params = catalogParamsToBackendParams(catalogName, params);
        }
      } else {
        // Strip trailing __<sig> to get the bare column name
        // (e.g. "trend_ema_fast__window20" → "trend_ema_fast").
        // The id may already be a sig-suffixed payload key from
        // the Markov page's defaultIndicators or from a URL param.
        const lastSep = ov.id.lastIndexOf('__');
        if (lastSep > 0) {
          column = ov.id.slice(0, lastSep);
        }
      }
      if (!cols.includes(column)) cols.push(column);
      if (params && Object.keys(params).length > 0) {
        // Use sig-suffixed override key so multiple param variants
        // of the same column can coexist (e.g. EMA20 + EMA200).
        // The backend's get_chart_data already supports this format.
        const overrideKey = chartPayloadKey(column, params);
        overrides[overrideKey] = params;
      }
    }

    const params = new URLSearchParams();
    if (rangeMode === 'custom' && customStart && customEnd) {
      params.set('start', customStart);
      params.set('end', customEnd);
    } else {
      params.set('days', String(RANGE_DAYS[rangeMode as Exclude<RangeMode, 'custom'>] ?? 365));
    }
    if (cols.length) params.set('indicators', cols.join(','));
    if (Object.keys(overrides).length) params.set('overrides', JSON.stringify(overrides));

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
        setChartError(err.message);
        setChartLoading(false);
      });
    return () => controller.abort();
  }, [ticker, rangeMode, customStart, customEnd, overlays]);

  const updateUrl = useCallback(
    (partial: Record<string, string | null>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(partial)) {
            if (v == null || v === '') next.delete(k);
            else next.set(k, v);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

/**
 * Companion bands for multi-line indicators. When the user adds a primary
 * band indicator (e.g. Bollinger Bands middle), the upper and lower bands
 * are automatically added so the chart renders the full envelope.
 * Keys are backend column names; values are companion descriptors.
 * Companion bands use dashed line style to visually distinguish them
 * from the primary band.
 */
const BAND_COMPANIONS: Record<string, Array<{ id: string; label: string; lineStyle?: string }>> = {
  'volatility_bbm': [
    { id: 'volatility_bbh', label: 'BB Upper', lineStyle: 'dashed' },
    { id: 'volatility_bbl', label: 'BB Lower', lineStyle: 'dashed' },
  ],
  'volatility_kcc': [
    { id: 'volatility_kch', label: 'KC Upper', lineStyle: 'dashed' },
    { id: 'volatility_kcl', label: 'KC Lower', lineStyle: 'dashed' },
  ],
  'volatility_dcl': [
    { id: 'volatility_dch', label: 'DC Upper', lineStyle: 'dashed' },
    { id: 'volatility_dcm', label: 'DC Middle', lineStyle: 'dashed' },
  ],
};

  const handleAddOverlay = useCallback(
    (descriptor: IndicatorDescriptor) => {
      const nextOverlays = [...overlays, descriptor];

      // Check if this indicator has companion bands (e.g. Bollinger Bands
      // upper/lower, Keltner upper/lower, Donchian upper/middle).
      // Resolve the catalog id to a backend column first.
      let column = descriptor.id;
      const m = /^ta__(.+)__/.exec(descriptor.id);
      if (m) {
        column = catalogEntryToColumn(m[1]);
      }
      const companions = BAND_COMPANIONS[column];
      if (companions) {
        // Override the primary band's label to avoid commas (which break
        // the comma-separated labels URL param). Use a descriptive label
        // that includes the window but not the std dev.
        const windowVal = descriptor.params?.window ?? 20;
        const primaryName = m ? m[1] : column;
        nextOverlays[nextOverlays.length - 1].label = `${primaryName} SMA${windowVal}`;

        for (const comp of companions) {
          // Always update companion band params to match the primary band,
          // even if the companion was already added (e.g. user changed the
          // std dev and re-added Bollinger Bands — the companion bands must
          // use the new params so the backend recomputes them correctly).
          const existing = nextOverlays.find((o) => o.id === comp.id);
          if (existing) {
            existing.params = descriptor.params;
          } else {
            nextOverlays.push({
              id: comp.id,
              label: comp.label,
              // Pass the same params as the primary band so the backend
              // recomputes the companion bands with the correct window
              // and std dev (e.g. Bollinger Bands with window_dev=3).
              params: descriptor.params,
            });
          }
        }
      }

      const paramMap: Record<string, Record<string, number>> = {};
      for (const o of nextOverlays) {
        if (o.params && Object.keys(o.params).length > 0) {
          paramMap[o.id] = o.params;
        }
      }
      updateUrl({
        overlays: nextOverlays.map((o) => o.id).join(','),
        labels: nextOverlays.map((o) => o.label).join(','),
        params: Object.keys(paramMap).length ? JSON.stringify(paramMap) : null,
      });
    },
    [overlays, updateUrl],
  );

  const handleRemoveOverlay = useCallback(
    (id: string) => {
      const nextOverlays = overlays.filter((o) => o.id !== id);
      const paramMap: Record<string, Record<string, number>> = {};
      for (const o of nextOverlays) {
        if (o.params && Object.keys(o.params).length > 0) {
          paramMap[o.id] = o.params;
        }
      }
      updateUrl({
        overlays: nextOverlays.length ? nextOverlays.map((o) => o.id).join(',') : null,
        labels: nextOverlays.length ? nextOverlays.map((o) => o.label).join(',') : null,
        params: Object.keys(paramMap).length ? JSON.stringify(paramMap) : null,
      });
    },
    [overlays, updateUrl],
  );

  // Toggle visibility of a single overlay without removing it. Local
  // state only — does not affect the URL.
  const handleToggleOverlay = useCallback((id: string) => {
    setActiveIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleRangeChange = useCallback(
    (mode: RangeMode, custom?: { start?: string; end?: string }) => {
      if (mode === 'custom') {
        updateUrl({
          range: 'custom',
          start: custom?.start ?? '',
          end: custom?.end ?? '',
        });
      } else {
        updateUrl({
          range: mode,
          start: null,
          end: null,
        });
      }
    },
    [updateUrl],
  );

  // Build the chart's indicator payload from the bars + overlays. Match
  // the chart endpoint's payload key convention: `<column>` for default
  // and `<column>__<sig>` for overrides. Hide overlays that the user
  // has toggled off — the underlying series data is still fetched
  // (one round-trip) but the chart only renders the active ones.
  const chartIndicatorsPayload = useMemo(() => {
    const series: Record<string, { time: number; value: number }[]> = {};
    chartBars.forEach((b) => {
      if (!b.indicators) return;
      const t = toEpochSeconds(b.time);
      Object.entries(b.indicators).forEach(([key, v]) => {
        if (v == null) return;
        if (!series[key]) series[key] = [];
        series[key].push({ time: t, value: v });
      });
    });
    // Build a set of companion band ids so we can set dashed line style
    // for upper/lower bands (Bollinger, Keltner, Donchian).
    const companionIds = new Set(
      Object.values(BAND_COMPANIONS).flatMap((comps) => comps.map((c) => c.id)),
    );
    return overlays.map((ov, i) => {
      // Resolve the chart-endpoint payload key for this overlay.
      // - For a catalog id (ta__<Name>__<sig>): translate the catalog
      //   name to its backend column, then build `<column>__<sig>` from
      //   the params dict.
      // - For a plain backend column id: the column IS the id, and
      //   when the overlay has params the key becomes `<column>__<sig>`.
      let column: string;
      let payloadKey: string;
      const m = /^ta__(.+)__/.exec(ov.id);
      if (m) {
        const catalogName = m[1];
        column = catalogEntryToColumn(catalogName);
        payloadKey = chartPayloadKey(column, ov.params);
      } else {
        // Strip trailing __<sig> to get the bare column name
        // (e.g. "trend_ema_fast__window20" → "trend_ema_fast").
        const lastSep = ov.id.lastIndexOf('__');
        column = lastSep > 0 ? ov.id.slice(0, lastSep) : ov.id;
        payloadKey = chartPayloadKey(column, ov.params);
      }
      const isOverlay = isOverlayColumn(column);
      return {
        name: ov.label,
        type: 'line',
        // Empty data array hides the series (lightweight-charts skips
        // lines with no points). The legend marker still shows because
        // the series is registered in CandleStickChart's effect — we
        // also need to skip the registration when inactive.
        data: activeIds.has(ov.id) ? (series[payloadKey] ?? []) : [],
        color: CHART_PALETTE[i % CHART_PALETTE.length],
        // Pass active state through so CandleStickChart can avoid
        // creating a series for hidden overlays.
        visible: activeIds.has(ov.id),
        // Oscillators (RSI, MACD, ADX, etc.) get their own pane below
        // the candles so they never get squished against the price axis.
        // Price-scaled overlays (EMAs, SMAs, Bollinger, etc.) share the
        // candle pane. Matches the pattern in TickerDetailDrawer.
        pane: isOverlay ? 'overlay' : 'oscillator',
        midline: isOverlay ? null : midlineForColumn(column),
        // Companion bands (BB Upper/Lower, KC Upper/Lower, etc.) use
        // dashed lines to visually distinguish them from the primary band.
        lineStyle: companionIds.has(ov.id) ? 'dashed' as const : undefined,
      };
    });
  }, [chartBars, overlays, activeIds]);

  if (!ticker) {
    return (
      <div style={{ padding: 64, color: colors.muted, textAlign: 'center' }}>
        No ticker specified.
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', backgroundColor: colors.canvas, display: 'flex', flexDirection: 'column' }}>
      {/* Header strip */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '20px 32px',
          borderBottom: `1px solid ${colors.border}`,
          backgroundColor: colors.surface,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            onClick={() => navigate(backPath)}
            aria-label={backLabel}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 12px',
              borderRadius: 6,
              border: `1px solid ${colors.border}`,
              background: 'none',
              color: colors.muted,
              fontSize: 13,
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            <ArrowLeft size={14} />
            {backLabel}
          </button>
          <span style={{ fontSize: 12, color: colors.subtle }}>{referrerLabel} ›</span>
          <span style={{ fontSize: 18, fontWeight: 700, color: colors.text }}>{ticker}</span>
          {metaData?.company_name && (
            <span style={{ fontSize: 13, color: colors.muted }}>{metaData.company_name}</span>
          )}
        </div>
      </div>

      {/* Two-column grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '320px 1fr',
          flex: 1,
          minHeight: 0,
        }}
      >
        {/* Left rail */}
        <div
          style={{
            borderRight: `1px solid ${colors.border}`,
            backgroundColor: colors.surface,
            padding: 20,
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
          }}
        >
          <MetadataRail
            ticker={ticker}
            data={metaData}
            loading={metaLoading}
            error={metaError}
            fromDate={fromDate}
          />
          <div style={{ height: 1, backgroundColor: colors.border }} />
          <div>
            <div
              style={{
                fontSize: 10,
                fontWeight: 600,
                color: colors.accent,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                marginBottom: 8,
              }}
            >
              Overlays
            </div>
            <OverlaysList
              overlays={overlays}
              activeIds={activeIds}
              onToggle={handleToggleOverlay}
              onRemove={handleRemoveOverlay}
              colors={colors}
            />
          </div>
          <div style={{ height: 1, backgroundColor: colors.border }} />
          <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            <div
              style={{
                fontSize: 10,
                fontWeight: 600,
                color: colors.accent,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                marginBottom: 8,
              }}
            >
              Add indicator
            </div>
            <IndicatorPickerPanel onAdd={handleAddOverlay} alreadyAdded={overlays.map((o) => o.id)} />
          </div>
        </div>

        {/* Chart panel */}
        <div
          style={{
            padding: 24,
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
          }}
        >
          <DateRangeBar
            mode={rangeMode}
            customStart={customStart}
            customEnd={customEnd}
            onChange={handleRangeChange}
            colors={colors}
          />
          <div
            style={{
              backgroundColor: colors.surfaceRaised,
              border: `1px solid ${colors.border}`,
              borderRadius: 12,
              padding: 16,
              flex: 1,
              minHeight: 400,
              position: 'relative',
            }}
          >
            {chartError ? (
              <div style={{ color: colors.muted, textAlign: 'center', padding: 40 }}>
                Failed to load chart: {chartError}
                <button
                  onClick={() => setChartError(null)}
                  style={{
                    marginLeft: 12,
                    padding: '4px 10px',
                    borderRadius: 4,
                    border: `1px solid ${colors.border}`,
                    background: 'none',
                    color: colors.muted,
                    cursor: 'pointer',
                  }}
                >
                  Retry
                </button>
              </div>
            ) : chartLoading && chartBars.length === 0 ? (
              <div style={{ color: colors.muted, textAlign: 'center', padding: 40 }}>
                Loading chart...
              </div>
            ) : chartBars.length === 0 ? (
              <div style={{ color: colors.muted, textAlign: 'center', padding: 40 }}>
                No data for {ticker} on this range. Try Max or a wider Custom range.
              </div>
            ) : (
              <CandleStickChart
                data={transformBars(chartBars)}
                height={500}
                indicators={chartIndicatorsPayload as never}
                cutoffDate={fromDate}
              />
            )}
            {chartLoading && chartBars.length > 0 && (
              <div
                style={{
                  position: 'absolute',
                  top: 12,
                  right: 12,
                  fontSize: 10,
                  fontWeight: 600,
                  color: colors.muted,
                  backgroundColor: colors.surface,
                  padding: '4px 8px',
                  borderRadius: 4,
                  border: `1px solid ${colors.border}`,
                }}
              >
                Loading...
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
