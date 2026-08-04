import { useEffect, useMemo, useRef, useState } from 'react';
import { SectorRegime, summarizeRegimes } from '../../lib/regime';
import {
  createChart,
  ColorType,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createSeriesMarkers,
  IChartApi,
  ISeriesApi,
  IPriceLine,
  Time,
  CandlestickData,
  HistogramData,
  SeriesMarker,
  LineData,
  LineStyle,
  SeriesMarkerShape,
  SeriesMarkerPosition,
} from 'lightweight-charts';

interface OHLCVData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface TradeMarker {
  time: number;
  price?: number;
  type: 'buy' | 'sell';
  size?: number;
  pnl?: number;
}

interface IndicatorData {
  time: number;
  value: number;
}

interface Indicator {
  name: string;
  type: string;
  data: IndicatorData[];
  color?: string;
  lineWidth?: number;
  /**
   * Series type. 'line' (default) draws a continuous line.
   * 'bar' draws a histogram (per-bar color) — used for MACD
   * histogram, OBV, and other volume-style series. */
  seriesType?: 'line' | 'bar';
  /**
   * Per-data-point colors for 'bar' series. When provided, each
   * bar uses the matching color; when omitted, the bar uses the
   * series color. */
  dataColors?: ('#10b981' | '#f43f5e' | string)[];
  /**
   * Line style for the series. 'solid' (default) draws a continuous
   * line; 'dashed' / 'dotted' draw a stepped-dash pattern to
   * visually distinguish companion series (e.g. Bollinger upper /
   * lower bands) from the primary series (the middle band). */
  lineStyle?: 'solid' | 'dashed' | 'dotted' | 'large_dashed' | 'sparse_dotted';
  /**
   * When false, the line series is not registered on the chart at all
   * (no legend entry, no render). When true (default) or omitted, the
   * series is created and plotted normally.
   */
  visible?: boolean;
  /**
   * Where to render the series.
   *  - 'overlay' (default): drawn on the candle pane sharing the price
   *    scale — for price-scaled indicators (SMA, EMA, Bollinger, PSAR, …).
   *  - 'oscillator': drawn in its OWN pane below the candles with an
   *    independent price scale — for oscillators (RSI, MACD, ADX, ATR,
   *    volume oscillators, …) so they never get squished against the
   *    price axis or share a scale with another oscillator.
   */
  pane?: 'overlay' | 'oscillator';
  /**
   * Optional canonical midline (e.g. 50 for RSI, 0 for MACD/ROC, 25 for
   * ADX). When provided, the chart draws a horizontal reference line at
   * that value so the user can read the indicator's state at a glance.
   * Line is bound to the series — toggling the indicator off removes it.
   * Ignored when omitted or for overlay (price-scaled) indicators. */
  midline?: number | null;
}

interface CandleStickChartProps {
  data: OHLCVData[];
  trades?: TradeMarker[];
  indicators?: Indicator[];
  height?: number;
  cutoffDate?: string; // mm/dd/yyyy or yyyy-mm-dd dashed vertical line
  visibleRange?: { from: number; to: number };
  /**
   * Optional sector regime data (per-ETF CURRENT regime, not a time
   * series). When `showRegimeOverlay` is on, the chart renders a
   * green/red regime badge reflecting the aggregate market regime.
   * SectorRegime carries no per-date data, so it cannot drive a
   * time-based band overlay — the badge is the honest interpretation.
   */
  regimeBands?: SectorRegime[];
  /** When true (and `regimeBands` is provided), show the regime badge. */
  showRegimeOverlay?: boolean;
}

/** Parse mm/dd/yyyy or yyyy-mm-dd to UTC timestamp in seconds. */
/** Map string line style to lightweight-charts LineStyle enum. Companion
 *  series (e.g. Bollinger upper/lower bands) use a stepped-dash pattern
 *  to visually distinguish them from the primary series (the middle
 *  band). Used for any series that should look secondary on the chart. */
function lineStyleMap(style: string | undefined) {
  switch (style) {
    case 'dashed': return LineStyle.Dashed;
    case 'dotted': return LineStyle.Dotted;
    case 'large_dashed': return LineStyle.LargeDashed;
    case 'sparse_dotted': return LineStyle.SparseDotted;
    case 'solid':
    default: return LineStyle.Solid;
  }
}

function parseDateToTimestamp(dateStr: string): number | null {
  // Try mm/dd/yyyy
  const slashParts = dateStr.split('/');
  if (slashParts.length === 3) {
    const month = parseInt(slashParts[0], 10);
    const day = parseInt(slashParts[1], 10);
    const year = parseInt(slashParts[2], 10);
    if (!isNaN(month) && !isNaN(day) && !isNaN(year)) {
      return Math.floor(Date.UTC(year, month - 1, day) / 1000);
    }
  }
  // Try yyyy-mm-dd
  const dashParts = dateStr.split('-');
  if (dashParts.length === 3) {
    const year = parseInt(dashParts[0], 10);
    const month = parseInt(dashParts[1], 10);
    const day = parseInt(dashParts[2], 10);
    if (!isNaN(year) && !isNaN(month) && !isNaN(day)) {
      return Math.floor(Date.UTC(year, month - 1, day) / 1000);
    }
  }
  return null;
}

/** Custom primitive to draw a dashed vertical line at a specific time. */
class VerticalLinePrimitive {
  private _chart: IChartApi | null = null;
  private _cutoffTime: Time;

  constructor(cutoffTime: Time) {
    this._cutoffTime = cutoffTime;
  }

  attached(param: any): void {
    this._chart = param.chart;
  }

  detached(): void {
    this._chart = null;
  }

  paneViews(): any[] {
    return [this._createPaneView()];
  }

  private _createPaneView(): any {
    const primitive = this;
    return {
      renderer() {
        return {
          draw(target: any) {
            if (!primitive._chart) return;
            const x = primitive._chart.timeScale().timeToCoordinate(primitive._cutoffTime);
            if (x === null) return;

            target.useBitmapCoordinateSpace((scope: any) => {
              const ctx = scope.context;
              const bitmapX = x * scope.horizontalPixelRatio;
              ctx.save();
              ctx.beginPath();
              ctx.setLineDash([6 * scope.horizontalPixelRatio, 4 * scope.horizontalPixelRatio]);
              ctx.strokeStyle = '#10B981';
              ctx.lineWidth = 2 * scope.horizontalPixelRatio;
              ctx.moveTo(bitmapX, 0);
              ctx.lineTo(bitmapX, scope.bitmapSize.height);
              ctx.stroke();
              ctx.restore();
            });
          },
        };
      },
      zOrder() {
        return 'top';
      },
    };
  }
}

export function CandleStickChart({
  data,
  trades = [],
  indicators = [],
  height = 400,
  cutoffDate,
  visibleRange,
  regimeBands,
  showRegimeOverlay = false,
}: CandleStickChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const indicatorSeriesRef = useRef<Record<string, ISeriesApi<'Line'> | ISeriesApi<'Histogram'>>>({});
  // Price lines bound to each indicator series (RSI's midline=50, MACD's
  // midline=0, …). Tracked separately so the destroy/recreate effect
  // can remove them with their series without leaking ghost lines.
  const indicatorPriceLinesRef = useRef<Record<string, IPriceLine[]>>({});
  const cutoffLineRef = useRef<VerticalLinePrimitive | null>(null);

  // Total chart height the layout actually needs (sum of all pane
  // heights + the time-scale row at the bottom). The wrapper's inline
  // height is driven from this so the container grows to fit pinned
  // oscillator panes and the outer chart panel's `overflowY: 'auto'`
  // provides the scrollbar. Without this, panes 2..N would be clipped
  // by the fixed wrapper height and become unreachable.
  const [chartTotalHeight, setChartTotalHeight] = useState(height);

  /**
   * Total chart height for a given candle-pane target and oscillator
   * count. Each pane is `candleTarget` px tall (stretch 1:1:…), plus
   * a fixed budget for the time-scale row at the bottom.
   *
   * The candle pane must stay at `candleTarget` regardless of how
   * many oscillator panes are added — that's why we *grow* the chart
   * rather than squeezing the candle pane. */
  const computeTotalHeight = (candleTarget: number, oscillatorCount: number): number => {
    return candleTarget * (1 + Math.max(0, oscillatorCount)) + 30; // 30 = time-scale row
  };

  /** Number of oscillator (non-overlay) indicators in the current payload. */
  const oscillatorCount = useMemo(
    () => indicators.filter((i) => i.pane === 'oscillator' && i.visible !== false && i.data?.length).length,
    [indicators],
  );

  /** Aggregate BULL/BEAR/vol regime derived from the per-ETF SectorRegime
   *  list. Only computed when regime data is actually supplied. */
  const regimeSummary = useMemo(() => {
    if (!regimeBands || regimeBands.length === 0) return null;
    return summarizeRegimes(regimeBands);
  }, [regimeBands]);

  /** Green for BULL, red for BEAR, muted gray for UNKNOWN / no data. */
  const regimeColor =
    regimeSummary?.overall === 'BULL'
      ? '#10b981'
      : regimeSummary?.overall === 'BEAR'
        ? '#f43f5e'
        : '#71717a';

  /** Total chart height the lightweight-charts canvas should be sized to. */
  const totalChartHeight = computeTotalHeight(height, oscillatorCount);

  const applyVisibleRange = () => {
    if (!chartRef.current) return;
    if (visibleRange?.from != null && visibleRange?.to != null) {
      try {
        chartRef.current.timeScale().setVisibleRange({
          from: Math.floor(visibleRange.from) as Time,
          to: Math.floor(visibleRange.to) as Time,
        });
        return;
      } catch (err) {
        console.error('Failed to set visible range:', err);
      }
    }
    chartRef.current.timeScale().fitContent();
  };

  // Initialize chart — runs ONCE on mount. The chart's height is later
  // adjusted via a separate effect that calls `applyOptions({ height })`
  // rather than re-initializing, so indicator series and the candle
  // series stay attached across height changes (expand/collapse).
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#d4d4d8',
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
      },
      width: chartContainerRef.current.clientWidth,
      height: totalChartHeight,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: 'rgba(255, 255, 255, 0.1)',
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.1)',
      },
      leftPriceScale: {
        visible: true,
        borderColor: 'rgba(255, 255, 255, 0.1)',
      },
    });

    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#f43f5e',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
      priceLineVisible: false,
    });

    candleSeriesRef.current = candleSeries;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      cutoffLineRef.current = null;
    };
  }, []);

  // Adjust chart height without tearing down the chart. Runs whenever
  // the height prop changes (candle target) OR when the number of
  // oscillator panes changes — the total height must grow to keep
  // every pane at the candle's full size. Lightweight-charts accepts
  // a height change via `applyOptions` and the series stay attached.
  useEffect(() => {
    if (!chartRef.current) return;
    chartRef.current.applyOptions({ height: totalChartHeight });
  }, [totalChartHeight]);

  // Update candlestick data
  useEffect(() => {
    if (!candleSeriesRef.current || !data.length) return;

    const cleanData: CandlestickData[] = data
      .filter((d) => d && typeof d.time === 'number' && !isNaN(d.time))
      .map((d) => ({
        time: Math.floor(d.time) as Time,
        open: d.open || 0,
        high: d.high || 0,
        low: d.low || 0,
        close: d.close || 0,
      }))
      .filter(
        (item, index, self) =>
          index === self.findIndex((t) => t.time === item.time)
      )
      .sort((a, b) => (a.time as number) - (b.time as number));

    candleSeriesRef.current.setData(cleanData);

    // Add volume if present
    const hasVolume = data.some((d) => d.volume > 0);
    if (hasVolume && chartRef.current) {
      if (!volumeSeriesRef.current) {
        const volumeSeries = chartRef.current.addSeries(HistogramSeries, {
          color: '#3b82f6',
          priceFormat: { type: 'volume' },
          priceScaleId: 'left',
        });

        volumeSeries.priceScale().applyOptions({
          scaleMargins: {
            top: 0.8,
            bottom: 0,
          },
        });
        // Ensure volume is visible by not auto-scaling with price data
        candleSeriesRef.current.priceScale().applyOptions({
          scaleMargins: {
            top: 0,
            bottom: 0.2,
          },
        });

        volumeSeriesRef.current = volumeSeries;
      }

      // Create a lookup map for OHLCV data by time
      const dataByTime = new Map<number, OHLCVData>();
      data.forEach((d) => {
        const timeKey = Math.floor(d.time);
        dataByTime.set(timeKey, d);
      });

      const volData: HistogramData[] = cleanData.map((d) => {
        const original = dataByTime.get(d.time as number);
        return {
          time: d.time,
          value: original?.volume || 0,
          color:
            d.close >= d.open
              ? 'rgba(16, 185, 129, 0.65)'
              : 'rgba(244, 63, 94, 0.65)',
        };
      });

      volumeSeriesRef.current.setData(volData);
    }

    applyVisibleRange();
  }, [data]);

  // Update trade markers
  useEffect(() => {
    if (!candleSeriesRef.current || !trades.length) return;

    const markers: SeriesMarker<Time>[] = trades
      .filter((trade) => trade && trade.time && trade.type)
      .map((trade) => ({
        time: Math.floor(trade.time) as Time,
        position: (trade.type === 'buy' ? 'belowBar' : 'aboveBar') as SeriesMarkerPosition,
        color: trade.type === 'buy' ? '#10b981' : '#f43f5e',
        shape: (trade.type === 'buy' ? 'arrowUp' : 'arrowDown') as SeriesMarkerShape,
        text: trade.type.toUpperCase(),
        size: 1,
        price: trade.price || 0,
      }))
      .sort((a, b) => (a.time as number) - (b.time as number));

    if (markers.length > 0) {
      createSeriesMarkers(candleSeriesRef.current, markers);
    }
  }, [trades]);

  // Update indicators
  useEffect(() => {
    if (!chartRef.current || !indicators.length) return;

    // Clear existing indicator series AND their bound price lines
    // (midline references). Removing the series also drops the price
    // lines in lightweight-charts, but we clear the tracking ref so
    // the next render starts from a known-empty state.
    Object.entries(indicatorSeriesRef.current).forEach(([name, series]) => {
      if (series && chartRef.current) {
        try {
          const lines = indicatorPriceLinesRef.current[name] ?? [];
          for (const line of lines) {
            try { series.removePriceLine(line); } catch { /* ignore */ }
          }
          indicatorPriceLinesRef.current[name] = [];
          chartRef.current.removeSeries(series);
        } catch {
          // Series may already be removed during unmount; ignore
        }
      }
    });
    indicatorSeriesRef.current = {};
    indicatorPriceLinesRef.current = {};

    // Remove any oscillator panes left over from a previous render so
    // the pane count matches the current indicator set. Pane 0 holds
    // candles + volume + overlays and is never removed. Clear from the
    // highest index down so removal doesn't shift the indices we still
    // need to touch.
    const panesBefore = chartRef.current.panes();
    for (let i = panesBefore.length - 1; i >= 1; i--) {
      try {
        chartRef.current.removePane(i);
      } catch {
        // Pane may already be gone; ignore
      }
    }

    // Pane assignment. Overlays share pane 0 with the candles (price
    // scale). Each oscillator gets its OWN pane (1, 2, …) with an
    // independent price scale, so RSI (0-100), MACD (~0), ADX (0-100),
    // ATR, OBV, … never share an axis with price or with each other.
    let oscillatorPane = 1;

    indicators.forEach((indicator, index) => {
      // Skip indicators the caller marked invisible. The caller is
      // responsible for not sending the data; we also skip the
      // series creation entirely so the legend doesn't show a hidden
      // overlay.
      if (indicator.visible === false) return;
      if (!indicator?.data?.length) return;

      try {
        const hue = (index * 137.508) % 360;
        const color = indicator.color || `hsl(${hue}, 70%, 50%)`;

        const isOscillator = indicator.pane === 'oscillator';
        const paneIndex = isOscillator ? oscillatorPane : 0;
        const isBar = indicator.seriesType === 'bar';

        // For bar series (MACD histogram, OBV, etc.) the chart uses
        // HistogramSeries with per-point color. The line series
        // path is taken for everything else.
        const lineSeries = chartRef.current!.addSeries(
          isBar ? HistogramSeries : LineSeries,
          {
            color: color,
            lineWidth: (isBar ? 2 : (indicator.lineWidth || 2)) as 1 | 2 | 3 | 4,
            lineStyle: lineStyleMap(indicator.lineStyle),
            priceLineVisible: false,
            crosshairMarkerVisible: !isBar,
            lastValueVisible: !isBar,
            priceScaleId: 'right',
          },
          paneIndex,
        ) as ISeriesApi<'Line'> | ISeriesApi<'Histogram'>;

        if (isOscillator) oscillatorPane += 1;

        if (isBar) {
          // Bar series: build {time, value, color} per point. The
          // caller can supply `dataColors` to override the color
          // per bar (e.g. green for positive MACD histogram, red
          // for negative). Default to the series color for all
          // bars.
          const fallbackColor = color;
          const histData: HistogramData[] = indicator.data
            .filter((d) => d && d.time && d.value !== undefined)
            .map((d, i) => ({
              time: (typeof d.time === 'number' ? Math.floor(d.time) : d.time) as Time,
              value: d.value,
              color: indicator.dataColors?.[i] ?? fallbackColor,
            }))
            .sort((a, b) => (a.time as number) - (b.time as number));
          lineSeries.setData(histData);
        } else {
          const indicatorData: LineData[] = indicator.data
            .filter((d) => d && d.time && d.value !== undefined)
            .map((d) => ({
              time: (typeof d.time === 'number' ? Math.floor(d.time) : d.time) as Time,
              value: d.value,
            }))
            .sort((a, b) => (a.time as number) - (b.time as number));
          lineSeries.setData(indicatorData);
        }
        indicatorSeriesRef.current[indicator.name] = lineSeries;

        // Draw a midline reference when the caller supplied one. Bound
        // to the series so toggling the indicator off (visible=false)
        // — or removing it entirely — drops the line with it. Dashed
        // + muted color so it doesn't compete visually with the data.
        if (indicator.midline != null) {
          const line = lineSeries.createPriceLine({
            price: indicator.midline,
            color: 'rgba(148, 163, 184, 0.7)', // slate-400, theme-agnostic
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'mid',
          });
          indicatorPriceLinesRef.current[indicator.name] = [line];
        }
      } catch (error) {
        console.error('Failed to add indicator:', indicator.name, error);
      }
    });

    // Give every pane an equal share of the vertical space so the
    // oscillator panes (RSI/MACD/ADX/…) render at the same physical
    // height as the candle pane.
    //
    // IMPORTANT: this must run on the next animation frame, not in
    // this effect synchronously. The chart's pane layout (heights
    // returned by `pane.getHeight()`) is computed by lightweight-
    // charts on the next frame after the series / height changes; if
    // we read the heights now, the new pane reports 0px and our
    // setStretchFactor call has no effect. requestAnimationFrame
    // defers the read until the layout has actually been computed.
    requestAnimationFrame(() => {
      if (!chartRef.current) return;
      try {
        const panes = chartRef.current.panes();
        for (let i = 0; i < panes.length; i++) panes[i].setStretchFactor(1);
      } catch {
        // setStretchFactor is best-effort; ignore if unavailable
      }
    });

    // Pin every oscillator pane to the candle pane's actual rendered
    // height. Deferred to the next animation frame so the chart's
    // layout has time to compute the post-stretch heights — reading
    // pane heights synchronously here would see the pre-stretch
    // values (with the new oscillator pane at 0px) and pin it to 0.
    //
    // Two frames are needed in practice:
    //   frame 1: apply stretch factors (1:1:…)
    //   frame 2: measure heights, pin oscillator panes, resize wrapper
    requestAnimationFrame(() => {
      if (!chartRef.current) return;
      requestAnimationFrame(() => {
        if (!chartRef.current) return;
        try {
          const panes = chartRef.current.panes();
          if (panes.length === 0) return;
          const candleHeight = panes[0]?.getHeight() ?? height;
          for (let i = 1; i < panes.length; i++) {
            try {
              panes[i].setHeight(candleHeight);
            } catch {
              // Per-pane failure shouldn't break the layout.
            }
          }
          // Drive the wrapper's outer height from the actual pane
          // geometry. Pinned total may exceed the chart's internal
          // `height` — that's fine, the outer panel scrolls.
          const totalFromPanes = panes.reduce((sum, p) => sum + p.getHeight(), 0);
          setChartTotalHeight(Math.max(height, totalFromPanes + 30));
        } catch {
          // pane() / getHeight() may not be available; fall back to
          // the pre-pinned stretch layout, which is still equal-height.
        }
      });
    });

    applyVisibleRange();
  }, [indicators]);

  // Re-apply visible range whenever the prop changes (e.g. returning to Dashboard)
  useEffect(() => {
    applyVisibleRange();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleRange?.from, visibleRange?.to]);

  // Draw dashed green vertical line at cutoff date using custom primitive
  useEffect(() => {
    if (!chartRef.current || !candleSeriesRef.current || !cutoffDate || !data.length) {
      if (cutoffLineRef.current && candleSeriesRef.current) {
        try {
          candleSeriesRef.current.detachPrimitive(cutoffLineRef.current);
        } catch { /* ignore */ }
        cutoffLineRef.current = null;
      }
      return;
    }

    const cutoffTs = parseDateToTimestamp(cutoffDate);
    if (cutoffTs === null) return;

    // Find the nearest data point time to the cutoff for exact timeToCoordinate match
    let nearestTime = data[0].time;
    let minDiff = Math.abs(data[0].time - cutoffTs);
    for (const d of data) {
      const diff = Math.abs(d.time - cutoffTs);
      if (diff < minDiff) {
        minDiff = diff;
        nearestTime = d.time;
      }
    }

    try {
      if (cutoffLineRef.current && candleSeriesRef.current) {
        candleSeriesRef.current.detachPrimitive(cutoffLineRef.current);
      }
      const primitive = new VerticalLinePrimitive(Math.floor(nearestTime) as Time);
      candleSeriesRef.current.attachPrimitive(primitive);
      cutoffLineRef.current = primitive;
    } catch (err) {
      console.error('Failed to draw cutoff line:', err);
    }
  }, [cutoffDate, data]);

  return (
    <div
      className="w-full relative"
      style={{ height: `${Math.max(chartTotalHeight, totalChartHeight)}px` }}
    >
      <div
        ref={chartContainerRef}
        className="w-full h-full"
        // Wrapper height is driven by `chartTotalHeight` (the measured
        // total of all pinned panes + the time-scale row) and falls back
        // to the pre-pinned `totalChartHeight` for the first frame
        // before the indicator effect has had a chance to measure.
        // When the total exceeds the parent chart panel's height, the
        // panel's `overflowY: 'auto'` provides the scrollbar so every
        // pane — including the candle pane — stays at its full target
        // size instead of being squished.
      />
      {/* Regime overlay badge — gated by `showRegimeOverlay`. Rendered as
          an absolutely-positioned chip in the chart's top-left corner
          (the chart-header analog), green/red for BULL/BEAR. SectorRegime
          is a CURRENT per-ETF reading, not a time series, so an honest
          overlay is this aggregate badge rather than fabricated bands. */}
      {showRegimeOverlay && regimeSummary && (
        <div
          style={{
            position: 'absolute',
            top: '8px',
            left: '8px',
            zIndex: 5,
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '4px 10px',
            borderRadius: '6px',
            backgroundColor: 'rgba(0,0,0,0.65)',
            border: `1px solid ${regimeColor}`,
            color: regimeColor,
            fontSize: '11px',
            fontWeight: 700,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            pointerEvents: 'none',
            whiteSpace: 'nowrap',
          }}
        >
          <span
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: regimeColor,
              flexShrink: 0,
            }}
          />
          Regime: {regimeSummary.overall}
          <span style={{ opacity: 0.75 }}>Vol: {regimeSummary.vol}</span>
        </div>
      )}
    </div>
  );
}
