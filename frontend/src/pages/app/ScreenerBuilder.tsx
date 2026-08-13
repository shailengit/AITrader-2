import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { request } from '@/lib/api';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Search,
  Save,
  Share2,
  BookTemplate,
  Plus,
  Loader2,
  SlidersHorizontal,
  Sparkles,
  FunctionSquare,
  Layers,
} from 'lucide-react';
import { useScreens, type FilterCondition, type FilterGroup, type ScreenPreset } from '../../hooks/useScreens';
import { useComposites } from '../../hooks/useComposites';
import { useMacros } from '../../hooks/useMacros';
import { decodeShareUrl } from '../../lib/shareCodec';
import { getFilterByKey, type FilterSpec } from '../../data/filterCatalog';
import {
  getColumnsForFilters,
  type ResultsColumn,
} from '../../data/filterCatalog';
import type { IndicatorDescriptor } from '../../types/indicators';
import { recordAppReferrer } from '../../components/layout/Layout';
import TickerDetailDrawer from './ScreenerBuilder/TickerDetailDrawer';
import TemplateChips from './ScreenerBuilder/TemplateChips';
import GroupHeader from './ScreenerBuilder/GroupHeader';
import FilterRow from './ScreenerBuilder/FilterRow';
import FilterPicker from './ScreenerBuilder/FilterPicker';
import ScreenLibraryModal from './ScreenerBuilder/ScreenLibraryModal';
import SaveScreenDialog from './ScreenerBuilder/SaveScreenDialog';
import ShareDialog from './ScreenerBuilder/ShareDialog';
import ResultsPanel from './ScreenerBuilder/ResultsPanel';
import BacktestPanel from './ScreenerBuilder/BacktestPanel';
import CompositeBuilder from './ScreenerBuilder/CompositeBuilder';
import ScoringPanel, { DEFAULT_BASE_WEIGHT, DEFAULT_SUB_WEIGHTS, DEFAULT_SHOW_ALIGNMENT } from './ScreenerBuilder/ScoringPanel';

// ── Types ─────────────────────────────────────────────────

interface ScanResult {
  ticker: string;
  company_name?: string;
  sector?: string;
  close?: number;
  score?: number;
  rsi?: number;
  momentum_rsi?: number;
  volume_ratio?: number;
  ath_proximity?: number;
  eps_growth_qoq?: number;
  [key: string]: any;
}

const DRAFT_KEY = 'screener:builder:draft';

// ── Helpers ───────────────────────────────────────────────

let _condCounter = 0;
function newConditionId(): string {
  _condCounter += 1;
  return `cond_${Date.now()}_${_condCounter}`;
}

// Buy-and-hold return is only meaningful if at least 2 trading days have elapsed
// since the as-of-date. Otherwise the buy/sell prices collapse to the same bar.
const MIN_DAYS_HELD = 2;

function isCutoffEligible(cutoff: string | null | undefined): boolean {
  if (!cutoff) return false;
  const cutoffMs = new Date(cutoff + 'T00:00:00').getTime();
  if (Number.isNaN(cutoffMs)) return false;
  const todayMs = Date.now();
  return (todayMs - cutoffMs) / 86_400_000 >= MIN_DAYS_HELD;
}

function createEmptyCondition(): FilterCondition {
  return {
    id: newConditionId(),
    filterKey: '',
    operator: 'gte',
    value: null,
  };
}

function convertFiltersToBackend(filters: FilterGroup): Record<string, any> {
  const indicatorFilters: Record<string, any>[] = [];
  let regimeValue: string | undefined;

  for (const cond of filters.conditions) {
    const spec = getFilterByKey(cond.filterKey);
    if (!spec) continue;

    // Sector Regime — emitted as a top-level `regime` key (not an indicator
    // filter). Consumed by apply_quant_filters in parsers.py.
    if (spec.key === 'regime') {
      if (typeof cond.value === 'string' && cond.value.trim()) {
        regimeValue = cond.value.trim();
      }
      continue;
    }

    // Translate frontend catalog `key` → backend column name produced by
    // `add_all_ta_features` (e.g. `sma_50` → `trend_sma_slow`, `rsi` → `momentum_rsi`).
    // Without this, the backend filters out conditions whose column doesn't
    // exist in the DataFrame, causing identical results across all parameter
    // combinations. (See parsers.apply_quant_filters: missing-column skip.)
    const column = spec.backendColumn || cond.filterKey;
    const refSpec = cond.referenceFilterKey
      ? getFilterByKey(cond.referenceFilterKey)
      : undefined;
    const referenceColumn = refSpec
      ? (refSpec.backendColumn || cond.referenceFilterKey)
      : cond.referenceFilterKey;

    if (spec.type === 'number') {
      // ── Crossover mode (Crossed Above / Crossed Below) ──────────
      if (cond.operator === 'crossed_above' || cond.operator === 'crossed_below') {
        if (cond.referenceFilterKey) {
          const item: Record<string, any> = {
            column,
            condition: cond.operator === 'crossed_above' ? 'crossed_above' : 'crossed_below',
            reference_column: referenceColumn,
            lookback_days: cond.lookbackDays ?? 5,
          };
          if (cond.params) item.params = cond.params;
          if (cond.referenceParams) item.reference_params = cond.referenceParams;
          indicatorFilters.push(item);
        }
        continue;
      }

      // ── Indicator comparison mode (e.g. SMA20 > SMA200) ────────
      if (cond.compareToIndicator && cond.referenceFilterKey) {
        const conditionMap: Record<string, string> = {
          gt: 'above',
          gte: 'above',
          lt: 'below',
          lte: 'below',
          eq: 'equals',
        };
        const mapped = conditionMap[cond.operator];
        if (mapped) {
          const item: Record<string, any> = {
            column,
            condition: mapped,
            reference_column: referenceColumn,
          };
          if (cond.params) item.params = cond.params;
          if (cond.referenceParams) item.reference_params = cond.referenceParams;
          indicatorFilters.push(item);
        }
        continue;
      }

      // ── Value comparison mode (default) ────────────────────────
      const item: Record<string, any> = { column };
      if (cond.params) item.params = cond.params;
      switch (cond.operator) {
        case 'gte':
          item.min = cond.value;
          break;
        case 'gt':
          item.min = cond.value;
          item.exclusive_min = true;
          break;
        case 'lte':
          item.max = cond.value;
          break;
        case 'lt':
          item.max = cond.value;
          item.exclusive_max = true;
          break;
        case 'eq':
          item.min = cond.value;
          item.max = cond.value;
          break;
        case 'neq':
          item.min_exclude = cond.value;
          item.max_exclude = cond.value;
          break;
      }
      indicatorFilters.push(item);
    } else if (spec.type === 'cross' && cond.referenceFilterKey) {
      indicatorFilters.push({
        column,
        condition: cond.operator === 'crossed_above' ? 'above' : 'below',
        reference_column: referenceColumn,
        lookback_days: cond.lookbackDays ?? 5,
      });
    }
  }

  return {
    indicator_filters: indicatorFilters,
    ...(regimeValue ? { regime: regimeValue } : {}),
    sort_by: 'score',
    sort_order: 'desc',
    max_results: 50,
  };
}

// ── Component ────────────────────────────────────────────

export default function ScreenerBuilder() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { savePreset } = useScreens();
  const { composites } = useComposites();
  const { macros, saveMacro } = useMacros();

  // Drawer state — ticker detail card. Synced to ?ticker= URL param.
  const [drawerTicker, setDrawerTicker] = useState<string | null>(null);

  // URL → drawer sync on mount / external nav.
  useEffect(() => {
    const fromUrl = searchParams.get('ticker');
    if (fromUrl && fromUrl.toUpperCase() !== drawerTicker) {
      setDrawerTicker(fromUrl.toUpperCase());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const openTicker = useCallback(
    (t: string) => {
      const upper = t.toUpperCase();
      setDrawerTicker(upper);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('ticker', upper);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const closeDrawer = useCallback(() => {
    setDrawerTicker(null);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('ticker');
        return next;
      },
      { replace: true },
    );
  }, [setSearchParams]);

  // ── State ──────────────────────────────────────────────
  const [filters, setFilters] = useState<FilterGroup>({
    match: 'all',
    conditions: [],
  });
  const [screenName, setScreenName] = useState('Untitled Screener');
  const [cutoffDate, setCutoffDate] = useState('');
  const [sortBy, setSortBy] = useState('score');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [maxResults, setMaxResults] = useState(50);
  const [useAi, setUseAi] = useState(false);

  // Scoring tunables (added 2026-07-05). Persisted in screen presets and
  // the page-state draft. Sent on every scan request.
  const [baseWeight, setBaseWeight] = useState(60);
  const [subWeights, setSubWeights] = useState<{ trend: number; momentum: number; volatility: number; volume: number }>(
    { trend: 30, momentum: 25, volatility: 20, volume: 25 },
  );
  const [showAlignment, setShowAlignment] = useState(false);
  const [angleWeight, setAngleWeight] = useState(0);

  // Derive whether any crossover filters are active (for angle weight slider visibility)
  const hasCrossFilters = useMemo(
    () => filters.conditions.some(
      (c) => c.operator === 'crossed_above' || c.operator === 'crossed_below'
    ),
    [filters.conditions],
  );

  // Scan state
  const [isScanning, setIsScanning] = useState(false);
  const [scanProgress, setScanProgress] = useState(0);
  const [scanError, setScanError] = useState<string | undefined>();
  const [scanResults, setScanResults] = useState<ScanResult[]>([]);
  // Stable scan id — persists across remounts so a back-navigation can
  // re-fetch the same results from the backend without re-running the scan.
  const [scanId, setScanId] = useState<string | null>(null);

  // Buy-and-hold return data (ticker -> return_pct)
  const [returnData, setReturnData] = useState<Record<string, number> | null>(null);
  const [returnLoading, setReturnLoading] = useState(false);

  // Inline backtest panel (Buy & Hold + With Exit Rules)
  const [backtestExpanded, setBacktestExpanded] = useState(false);

  // ── Restore gate ─────────────────────────────────────
  // `hasRestored` is `false` on mount, and is set to `true` by the
  // restore effect (line ~434) AFTER it has finished reading the
  // persisted draft and calling all the setState's. The persistence
  // effects below gate themselves on this flag: if `hasRestored` is
  // still `false`, the initial empty state must NOT be written to
  // localStorage — that would clobber the persisted draft and break
  // back-navigation state recovery.
  //
  // This is a `useState` (not `useRef`) on purpose: in React 19's
  // dev-mode StrictMode, components are mounted, "unmounted", and
  // remounted to stress-test effects. `useRef` values are NOT
  // guaranteed to be reset to their initial value across the
  // simulated remount, but `useState` initializers DO run again.
  // So a `useState` flag reliably re-starts as `false` on each
  // remount, which is what the persistence gate needs.
  const [hasRestored, setHasRestored] = useState(false);

  // Dialog state
  const [pickerOpen, setPickerOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveMode, setSaveMode] = useState<'save' | 'save-as'>('save');
  const [shareOpen, setShareOpen] = useState(false);
  const [compositeOpen, setCompositeOpen] = useState(false);
  const [macroName, setMacroName] = useState('');
  const [showMacroSave, setShowMacroSave] = useState(false);

  // Refs
  const eventSourceRef = useRef<EventSource | null>(null);

  const colors = {
    text: 'var(--foreground)',
    muted: 'var(--muted)',
    subtle: 'var(--subtle)',
    border: 'var(--border)',
    surface: 'var(--surface)',
    surfaceRaised: 'var(--surface-raised)',
    inputBg: 'var(--canvas)',
    canvas: 'var(--canvas)',
    accent: 'var(--accent)',
  };

  // ── URL param handling ─────────────────────────────────
  useEffect(() => {
    const shared = searchParams.get('s');
    if (shared) {
      const decoded = decodeShareUrl(shared);
      if (decoded) {
        setFilters(decoded.filters as FilterGroup);
        if (decoded.sort?.by) setSortBy(decoded.sort?.by);
        if (decoded.sort?.order) setSortOrder(decoded.sort?.order);
        if (decoded.maxResults) setMaxResults(decoded.maxResults);
        if (decoded.cutoffDate) setCutoffDate(decoded.cutoffDate);
      }
    }

    const loadId = searchParams.get('load');
    if (loadId) {
      // Template loading is handled via the library modal
      // URL param is for direct preset loading
    }
  }, [searchParams]);

  // Record this page as the referrer so the QuantGen (or chart page)
  // header's "Back" button can return here. We do NOT clear on
  // unmount — the referrer is meant to persist across navigations
  // away from the screener and back. The Layout's "Home" button (and
  // the chart page's "Back" button) explicitly clear the referrer
  // when the user explicitly leaves the screener subtree.
  useEffect(() => {
    recordAppReferrer('/screener/build', 'Custom Screener');
  }, []);

  // ── Draft persistence ──────────────────────────────────
  // The draft covers the full page state so a browser back-navigation
  // (which remounts the page) restores the same view — including the
  // results table. scanResults and returnData are persisted by the
  // special useEffects below (which fire on changes), not on every
  // render of these large arrays.
  //
  // CRITICAL: the persistence effects must NOT run before the
  // restore effect (declared last). Otherwise the initial empty
  // state would overwrite the persisted draft on mount, breaking
  // back-navigation state recovery. The persistence effects gate
  // themselves on the `hasRestored` flag (set by the restore effect
  // at the end) so the restore is always the first thing to touch
  // localStorage on mount.

  useEffect(() => {
    // Skip persistence until the restore has finished. The restore
    // sets `hasRestored` to `true` after reading the persisted draft
    // and applying all the setState's.
    if (!hasRestored) return;
    try {
      const draft = {
        filters,
        screenName,
        cutoffDate,
        sortBy,
        sortOrder,
        maxResults,
        useAi,
        baseWeight,
        subWeights,
        showAlignment,
        angleWeight,
        // Persisted so the back button (which remounts the page)
        // returns to the same screen state, not a fresh builder.
        scanId,
        // Results / return data / drawer are intentionally persisted
        // by the special useEffects below.
        drawerTicker,
        timestamp: Date.now(),
      };
      localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch {
      // ignore
    }
  }, [hasRestored, filters, screenName, cutoffDate, sortBy, sortOrder, maxResults, useAi, baseWeight, subWeights, showAlignment, angleWeight, scanId]);

  // Persist scanResults separately to avoid re-serializing on every
  // render (which would happen if we put it in the main draft effect).
  useEffect(() => {
    if (!hasRestored) return;
    if (scanResults.length === 0) return;
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      const draft = raw ? JSON.parse(raw) : {};
      draft.scanResults = scanResults;
      draft.timestamp = Date.now();
      localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch {
      // ignore
    }
  }, [hasRestored, scanResults]);

  // Persist returnData separately too.
  useEffect(() => {
    if (!hasRestored) return;
    if (returnData === null) return;
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      const draft = raw ? JSON.parse(raw) : {};
      draft.returnData = returnData;
      draft.timestamp = Date.now();
      localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch {
      // ignore
    }
  }, [hasRestored, returnData]);

  // Restore draft on mount. If a fresh draft has a scanId, re-fetch
  // results from the backend so the user gets up-to-date values
  // (matching what the page would show if the user had run the scan
  // just now). The persisted scanResults are also seeded so the page
  // has data to show during the refetch.
  //
  // This effect must run BEFORE the persistence effects write, so
  // the initial empty state doesn't clobber the saved draft. Because
  // effects fire in declaration order and the persistence effects
  // above also skip their first run, this restore effect is the
  // first to touch localStorage on mount.
  useEffect(() => {
    let restoredScanId: string | null = null;
    let restoredResults: ScanResult[] | null = null;
    let restoredReturnData: Record<string, number> | null = null;

    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (raw) {
        const draft = JSON.parse(raw);
        const isFresh = draft.timestamp && Date.now() - draft.timestamp < 24 * 60 * 60 * 1000;
        if (isFresh) {
          if (draft.filters) setFilters(draft.filters);
          if (draft.screenName) setScreenName(draft.screenName);
          if (draft.cutoffDate) setCutoffDate(draft.cutoffDate);
          if (draft.sort?.by) setSortBy(draft.sort?.by);
          if (draft.sort?.order) setSortOrder(draft.sort?.order);
          if (draft.maxResults) setMaxResults(draft.maxResults);
          if (draft.useAi !== undefined) setUseAi(draft.useAi);
          if (typeof draft.baseWeight === 'number') setBaseWeight(draft.baseWeight);
          if (draft.subWeights) setSubWeights(draft.subWeights);
          if (typeof draft.showAlignment === 'boolean') setShowAlignment(draft.showAlignment);
          if (typeof draft.angleWeight === 'number') setAngleWeight(draft.angleWeight);
          if (draft.drawerTicker) setDrawerTicker(draft.drawerTicker);
          if (draft.scanId) restoredScanId = draft.scanId;
          if (Array.isArray(draft.scanResults)) {
            setScanResults(draft.scanResults);
            restoredResults = draft.scanResults;
          }
          if (draft.returnData) {
            setReturnData(draft.returnData);
            restoredReturnData = draft.returnData;
          }
        } else {
          // Stale draft — drop persisted scan results so the user
          // doesn't see old data, but keep the filter draft.
          if (draft.filters) setFilters(draft.filters);
          if (draft.screenName) setScreenName(draft.screenName);
          if (draft.cutoffDate) setCutoffDate(draft.cutoffDate);
          if (draft.sort?.by) setSortBy(draft.sort?.by);
          if (draft.sort?.order) setSortOrder(draft.sort?.order);
          if (draft.maxResults) setMaxResults(draft.maxResults);
          if (draft.useAi !== undefined) setUseAi(draft.useAi);
          if (typeof draft.baseWeight === 'number') setBaseWeight(draft.baseWeight);
          if (draft.subWeights) setSubWeights(draft.subWeights);
          if (typeof draft.showAlignment === 'boolean') setShowAlignment(draft.showAlignment);
          if (typeof draft.angleWeight === 'number') setAngleWeight(draft.angleWeight);
        }
      }
    } catch {
      // ignore
    }

    // If we restored a scanId, re-fetch the results from the backend so
    // the user sees fresh data. This handles the case where the page
    // remounts (e.g. after a back-navigation) — the persisted
    // scanResults are shown immediately, then replaced by the live
    // fetch ONLY if the backend returns usable data. If the refetch
    // fails (e.g. backend was restarted and the in-memory scan_status
    // is gone) the persisted scanResults stay visible — that is the
    // primary state-recovery path. The refetch is a refresh, not a
    // requirement.
    if (restoredScanId) {
      setScanId(restoredScanId);
      const tickers = (restoredResults ?? []).map((r) => r.ticker);
      // Fire-and-forget the live refetch. Only overwrite the
      // persisted results if the backend returns a non-empty list.
      request<{ results?: ScanResult[] }>(`/screener/results/${restoredScanId}`)
        .then((data) => {
          if (data && Array.isArray(data.results) && data.results.length > 0) {
            setScanResults(data.results);
            // Refresh return data if the cutoff is eligible.
            if (cutoffDate && isCutoffEligible(cutoffDate) && data.results.length > 0) {
              const newTickers = data.results.map((r: ScanResult) => r.ticker);
              setReturnLoading(true);
              request<{ ticker_results?: { ticker: string; return_pct: number }[] }>(
                '/screener/backtest-hold',
                { method: 'POST', body: { tickers: newTickers, as_of_date: cutoffDate } },
              )
                .then((bd) => {
                  if (bd && Array.isArray(bd.ticker_results)) {
                    const next: Record<string, number> = {};
                    for (const tr of bd.ticker_results) {
                      next[tr.ticker] = tr.return_pct;
                    }
                    setReturnData(next);
                  }
                })
                .catch(() => {})
                .finally(() => setReturnLoading(false));
            }
          }
          // If data.results is empty/missing, keep the persisted
          // results visible — they are the source of truth.
        })
        .catch(() => {
          // Live refetch failed — the persisted scanResults stay visible.
        });
      // Touch the variables so TypeScript doesn't complain.
      void tickers;
      void restoredReturnData;
    }
    // Mark the restore as done. The persistence effects (which gate
    // on `hasRestored`) can now safely write to localStorage with the
    // current (restored) state values. This is the LAST setState in
    // the effect so the persistence effects' deps are guaranteed to
    // settle on the next render.
    setHasRestored(true);
  }, [cutoffDate]);

  // Cleanup event source on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  // ── Custom filters from composites & macros ────────────
  const customFilters = useMemo(() => {
    const filters: FilterSpec[] = [];

    // User-defined math composites
    for (const comp of composites) {
      filters.push({
        key: comp.name,
        label: comp.name,
        category: 'composite',
        type: 'number',
        backendColumn: comp.name,
        operators: [
          { operator: 'gt', label: '>', valueType: 'number' },
          { operator: 'gte', label: '>=', valueType: 'number' },
          { operator: 'lt', label: '<', valueType: 'number' },
          { operator: 'lte', label: '<=', valueType: 'number' },
        ],
        unit: 'pts',
        description: comp.description || `Custom: ${comp.leftIndicator} ${comp.operation} ${comp.rightIndicator}`,
      });
    }

    // Macro filter groups
    for (const macro of macros) {
      filters.push({
        key: `__macro__${macro.id}`,
        label: `📁 ${macro.name}`,
        category: 'composite',
        type: 'categorical',
        backendColumn: '',
        operators: [],
        description: macro.description || `${macro.filters.conditions.length} condition macro`,
      });
    }

    return filters;
  }, [composites, macros]);

  // Indicator list for the drawer's chart overlay set. Mirrors the
  // filterColumns derivation in ResultsPanel so the drawer's chart shows
  // the same overlays the user filtered on.
  const filterColumns: ResultsColumn[] = useMemo(
    () => getColumnsForFilters(filters.conditions as unknown as FilterCondition[]),
    [filters.conditions],
  );
  const chartIndicators: IndicatorDescriptor[] = useMemo(
    () =>
      filterColumns.map((col) => ({
        id: col.payloadKey,
        label: col.header,
        params: col.params,
      })),
    [filterColumns],
  );

  // ── Filter operations ──────────────────────────────────
  const addCondition = () => {
    setFilters((prev) => ({
      ...prev,
      conditions: [...prev.conditions, createEmptyCondition()],
    }));
  };

  const updateCondition = (index: number, updated: FilterCondition) => {
    setFilters((prev) => {
      const conditions = [...prev.conditions];
      conditions[index] = updated;
      return { ...prev, conditions };
    });
  };

  const removeCondition = (index: number) => {
    setFilters((prev) => ({
      ...prev,
      conditions: prev.conditions.filter((_, i) => i !== index),
    }));
  };

  const setGroupMatch = (match: 'all' | 'any') => {
    setFilters((prev) => ({ ...prev, match }));
  };

  // ── Load preset ────────────────────────────────────────
  const handleLoadPreset = (preset: ScreenPreset) => {
    setFilters(preset.filters);
    setScreenName(preset.name);
    if (preset.sort?.by) setSortBy(preset.sort?.by);
    if (preset.sort?.order) setSortOrder(preset.sort?.order);
    if (preset.maxResults) setMaxResults(preset.maxResults);
    if (preset.cutoffDate) setCutoffDate(preset.cutoffDate);
    if (preset.useAi !== undefined) setUseAi(preset.useAi);
    if (typeof preset.baseWeight === 'number') setBaseWeight(preset.baseWeight);
    if (preset.subWeights) setSubWeights(preset.subWeights);
    if (typeof preset.showAlignment === 'boolean') setShowAlignment(preset.showAlignment);
    if (typeof preset.angleWeight === 'number') setAngleWeight(preset.angleWeight);
  };

  // ── Save ───────────────────────────────────────────────
  const handleSave = (name: string, description?: string, category?: string) => {
    savePreset({
      name,
      filters,
      description,
      category,
      sort: sortBy ? { by: sortBy, order: sortOrder } : undefined,
      maxResults,
      cutoffDate: cutoffDate || undefined,
      useAi,
      baseWeight,
      subWeights,
      showAlignment,
      angleWeight,
    });
    setScreenName(name);
  };

  // ── Share data ─────────────────────────────────────────
  const shareData = {
    schemaVersion: 1 as const,
    name: screenName || 'Untitled',
    filters,
    sort: sortBy ? { by: sortBy, order: sortOrder } : undefined,
    maxResults,
    cutoffDate: cutoffDate || undefined,
    useAi,
    angleWeight,
  };

  // ── Scan pipeline ───────────────────────────────────────
  const startScan = useCallback(async () => {
    if (filters.conditions.length === 0) return;

    setIsScanning(true);
    setScanError(undefined);
    setScanResults([]);
    setScanId(null);
    setScanProgress(0);
    setReturnData(null);

    const backendFilters = convertFiltersToBackend(filters);

    // Build custom composites list for the backend
    const customCompositesList = composites
      .filter((comp) => {
        // Only include composites that are referenced in the current filters
        return filters.conditions.some((c) => c.filterKey === comp.name);
      })
      .map((comp) => ({
        name: comp.name,
        left_indicator: comp.leftIndicator,
        right_indicator: comp.rightIndicator,
        operation: comp.operation,
      }));

    try {
      const data = await request<{ scan_id: string }>('/screener/scan', {
        method: 'POST',
        body: {
          mode: 'quant_strategy',
          use_ai: useAi,
          cutoff_date: cutoffDate || undefined,
          max_results: maxResults,
          filters: backendFilters,
          base_weight: baseWeight,
          sub_weights: subWeights,
          include_alignment: showAlignment,
          angle_weight: angleWeight,
          // Tell the backend which result-row keys the UI needs values for
          // (e.g. the user's chosen SMA 200 with window=200). The worker
          // computes each column at the requested params and includes the
          // value in the scan result row.
          result_columns: filterColumns
            .filter((c) => c.dataKey)
            .map((c) => ({ dataKey: c.dataKey, params: c.params })),
          custom_composites: customCompositesList.length > 0 ? customCompositesList : undefined,
        },
      });
      const id = data.scan_id;
      setScanId(id);

      // SSE stream
      const es = new EventSource(`/api/screener/stream/${id}`);
      eventSourceRef.current = es;

      es.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          const { type, data: eventData } = payload;

          if (type === 'progress') {
            setScanProgress(eventData.progress);
          } else if (type === 'status') {
            if (eventData.status === 'completed') {
              setIsScanning(false);
              setScanProgress(100);
              fetchResults(id);
              es.close();
              // Fetch buy-and-hold returns after results come in
              if (isCutoffEligible(cutoffDate)) {
                (async () => {
                  try {
                    const d = await request<{ results?: any[] }>(`/screener/results/${id}`);
                    const tickers = (d.results || []).map((x: any) => x.ticker);
                    if (tickers.length > 0) {
                      setReturnLoading(true);
                      const bd = await request<{ ticker_results?: { ticker: string; return_pct: number }[] }>(
                        '/screener/backtest-hold',
                        { method: 'POST', body: { tickers, as_of_date: cutoffDate } },
                      );
                      {
                        const returns: Record<string, number> = {};
                        for (const tr of bd.ticker_results || []) {
                          returns[tr.ticker] = tr.return_pct;
                        }
                        setReturnData(returns);
                      }
                    }
                  } catch { /* ignore */ }
                  finally { setReturnLoading(false); }
                })();
              }
            } else if (eventData.status === 'failed') {
              setIsScanning(false);
              setScanError(eventData.error || 'Scan failed');
              es.close();
            }
          }
        } catch {
          // ignore parse errors
        }
      };

      es.onerror = () => {
        es.close();
        pollFallback(id);
      };
    } catch (err) {
      setIsScanning(false);
      setScanError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, [filters, useAi, cutoffDate, maxResults, baseWeight, subWeights, showAlignment]);

  const fetchResults = async (id: string) => {
    try {
      const data = await request<{ results?: ScanResult[] }>(`/screener/results/${id}`);
      setScanResults(data.results || []);
    } catch {
      // ignore
    }
  };

  const pollFallback = async (id: string) => {
    const poll = async () => {
      try {
        const data = await request<{ progress?: number; status?: string; error?: string }>(`/screener/status/${id}`);

        setScanProgress(data.progress ?? 0);

        if (data.status === 'running') {
          setTimeout(poll, 1000);
        } else if (data.status === 'completed') {
          setIsScanning(false);
          setScanProgress(100);
          fetchResults(id);
          // Fetch buy-and-hold returns
          if (isCutoffEligible(cutoffDate)) {
            (async () => {
              try {
                const d = await request<{ results?: any[] }>(`/screener/results/${id}`);
                const tickers = (d.results || []).map((x: any) => x.ticker);
                if (tickers.length > 0) {
                  setReturnLoading(true);
                  const bd = await request<{ ticker_results?: { ticker: string; return_pct: number }[] }>(
                    '/screener/backtest-hold',
                    { method: 'POST', body: { tickers, as_of_date: cutoffDate } },
                  );
                  {
                    const returns: Record<string, number> = {};
                    for (const tr of bd.ticker_results || []) {
                      returns[tr.ticker] = tr.return_pct;
                    }
                    setReturnData(returns);
                  }
                }
              } catch { /* ignore */ }
              finally { setReturnLoading(false); }
            })();
          }
        } else if (data.status === 'failed') {
          setIsScanning(false);
          setScanError(data.error || 'Scan failed');
        }
      } catch {
        setIsScanning(false);
        setScanError('Failed to get scan status');
      }
    };
    poll();
  };

  // ── Export to Lab ──────────────────────────────────────
  const openChartView = useCallback(
    (t: string) => {
      const upper = t.toUpperCase();
      closeDrawer();
      // Translate each IndicatorDescriptor's payload key (`<column>__<sig>`)
      // into the actual backend column name. The standalone chart endpoint
      // expects `overlays=<col1>,<col2>` (column names), with a separate
      // `params` map keyed by column for any non-default window overrides.
      // Sending payload keys as `overlays` makes the backend silently drop
      // them (registry doesn't know about `trend_sma_slow__window50`).
      //
      // We also pass `labels` (a parallel array of the friendly column
      // headers like "SMA 50" / "SMA 200") so the standalone chart can
      // show the overlay list with the same labels the user saw in the
      // results table — not the raw backend column name. When the label
      // can't be recovered (e.g. it was never supplied), we fall back to
      // a best-effort `name (params)` form on the chart side.
      const cols: string[] = [];
      const labels: string[] = [];
      const params: Record<string, Record<string, number>> = {};
      for (const c of chartIndicators) {
        const lastSep = c.id.lastIndexOf('__');
        const column = lastSep > 0 ? c.id.slice(0, lastSep) : c.id;
        if (!cols.includes(column)) {
          cols.push(column);
          labels.push(c.label);
        }
        if (c.params && Object.keys(c.params).length > 0) {
          params[column] = c.params;
        }
      }
      const qs = new URLSearchParams();
      if (cutoffDate) qs.set('from', cutoffDate);
      qs.set('range', '1y');
      qs.set('overlays', cols.join(','));
      if (labels.length) qs.set('labels', labels.join(','));
      if (Object.keys(params).length) qs.set('params', JSON.stringify(params));
      navigate(`/screener/build/chart/${upper}?${qs.toString()}`);
    },
    [closeDrawer, navigate, cutoffDate, chartIndicators],
  );

  const exportToLab = () => {
    // Make sure the referrer is current before navigating so the
    // QuantGen page's "Back" button can find its way back here.
    recordAppReferrer('/screener/build', 'Custom Screener');
    const tickers = scanResults.map((r) => r.ticker).join(',');
    const fromDate = cutoffDate || new Date().toISOString().split('T')[0];
    navigate(`/quantgen/build?tickers=${encodeURIComponent(tickers)}&from_date=${fromDate}`);
  };

  // ── Render ──────────────────────────────────────────────
  return (
    <div style={{ minHeight: '100vh', backgroundColor: colors.canvas }}>
      <div style={{ maxWidth: 1280, margin: '0 auto', padding: '0 32px' }}>
        {/* ── Header ──────────────────────────────────────── */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            paddingTop: 32,
            paddingBottom: 24,
          }}
        >
          <div>
            <h1
              style={{
                fontSize: 28,
                fontWeight: 600,
                letterSpacing: '-0.02em',
                color: colors.text,
                margin: 0,
              }}
            >
              Custom Screener
            </h1>
            <p style={{ fontSize: 14, color: colors.muted, margin: '4px 0 0' }}>
              Build your own stock screener from a library of filters
            </p>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => {
                setSaveMode('save');
                setSaveOpen(true);
              }}
              style={headerButtonStyle(colors)}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = colors.accent;
                e.currentTarget.style.color = colors.accent;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = colors.border;
                e.currentTarget.style.color = colors.muted;
              }}
            >
              <Save size={15} />
              Save
            </button>
            <button
              onClick={() => {
                setSaveMode('save-as');
                setSaveOpen(true);
              }}
              style={headerButtonStyle(colors)}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = colors.accent;
                e.currentTarget.style.color = colors.accent;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = colors.border;
                e.currentTarget.style.color = colors.muted;
              }}
            >
              Save As
            </button>
            <button
              onClick={() => setLibraryOpen(true)}
              style={headerButtonStyle(colors)}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = colors.accent;
                e.currentTarget.style.color = colors.accent;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = colors.border;
                e.currentTarget.style.color = colors.muted;
              }}
            >
              <BookTemplate size={15} />
              Templates
            </button>
            <button
              onClick={() => setShareOpen(true)}
              style={{
                ...headerButtonStyle(colors),
                backgroundColor: 'var(--accent-glow)',
                color: colors.accent,
                borderColor: 'var(--accent-glow)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--accent-glow)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--accent-glow)';
              }}
            >
              <Share2 size={15} />
              Share
            </button>
          </div>
        </div>

        {/* ── Config row ─────────────────────────────────── */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            marginBottom: 24,
            padding: '16px 20px',
            borderRadius: 12,
            border: `1px solid ${colors.border}`,
            backgroundColor: colors.surface,
          }}
        >
          <div style={{ flex: 1 }}>
            <label
              style={{
                display: 'block',
                fontSize: 11,
                fontWeight: 600,
                color: colors.muted,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: 4,
              }}
            >
              Screen Name
            </label>
            <input
              type="text"
              value={screenName}
              onChange={(e) => setScreenName(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: 6,
                border: `1px solid ${colors.border}`,
                backgroundColor: colors.inputBg,
                color: colors.text,
                fontSize: 14,
                outline: 'none',
              }}
            />
          </div>

          <div style={{ width: 180 }}>
            <label
              style={{
                display: 'block',
                fontSize: 11,
                fontWeight: 600,
                color: colors.muted,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: 4,
              }}
            >
              As-Of Date
            </label>
            <input
              type="date"
              value={cutoffDate}
              onChange={(e) => setCutoffDate(e.target.value)}
              max={new Date().toISOString().split('T')[0]}
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: 6,
                border: `1px solid ${colors.border}`,
                backgroundColor: colors.inputBg,
                color: colors.text,
                fontSize: 14,
                outline: 'none',
              }}
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingTop: 16 }}>
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: colors.muted,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              AI
            </span>
            <button
              onClick={() => setUseAi(!useAi)}
              style={{
                width: 36,
                height: 20,
                borderRadius: 10,
                border: 'none',
                backgroundColor: useAi ? colors.accent : colors.subtle,
                cursor: 'pointer',
                position: 'relative',
                transition: 'background-color 150ms ease',
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  top: 2,
                  width: 16,
                  height: 16,
                  borderRadius: '50%',
                  backgroundColor: 'var(--surface)',
                  transition: 'transform 150ms ease',
                  transform: useAi ? 'translateX(16px)' : 'translateX(2px)',
                }}
              />
            </button>
          </div>
        </div>

        {/* ── Template chips strip ──────────────────────── */}
        <TemplateChips
          onLoad={(tpl) => {
            setFilters(tpl.filters);
            setScreenName(tpl.name);
            if (tpl.sort?.by) setSortBy(tpl.sort.by);
            if (tpl.sort?.order) setSortOrder(tpl.sort.order);
            if (tpl.maxResults) setMaxResults(tpl.maxResults);
            if (tpl.useAi !== undefined) setUseAi(tpl.useAi);
            if (typeof tpl.angleWeight === 'number') setAngleWeight(tpl.angleWeight);
          }}
          activeFilters={filters}
        />

        {/* ── Filter builder ──────────────────────────────── */}
        <div
          style={{
            marginBottom: 24,
            padding: 20,
            borderRadius: 12,
            border: `1px solid ${colors.border}`,
            backgroundColor: colors.surface,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <SlidersHorizontal size={18} color={colors.text} />
            <span style={{ fontSize: 15, fontWeight: 600, color: colors.text }}>
              Filters
            </span>
            {filters.conditions.length > 0 && (
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 500,
                  color: colors.accent,
                  padding: '2px 8px',
                  borderRadius: 6,
                  backgroundColor: 'var(--accent-glow)',
                }}
              >
                {filters.conditions.length} condition
                {filters.conditions.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>

          {filters.conditions.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <GroupHeader
                match={filters.match}
                onMatchChange={setGroupMatch}
                conditionCount={filters.conditions.length}
              />
              {filters.conditions.map((cond, idx) => (
                <FilterRow
                  key={cond.id}
                  condition={cond}
                  index={idx}
                  total={filters.conditions.length}
                  groupMatch={filters.match}
                  onChange={(updated) => updateCondition(idx, updated)}
                  onRemove={() => removeCondition(idx)}
                  onGroupMatchChange={setGroupMatch}
                />
              ))}
            </div>
          ) : (
            <div
              style={{
                textAlign: 'center',
                padding: '32px 16px',
                color: colors.muted,
              }}
            >
              <Search size={28} style={{ margin: '0 auto 8px', display: 'block', opacity: 0.4 }} />
              <span style={{ fontSize: 14, display: 'block', marginBottom: 12 }}>
                No filters yet. Add a filter to start building your screener.
              </span>
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button
              onClick={addCondition}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '8px 16px',
                borderRadius: 8,
                border: `1px dashed ${colors.border}`,
                backgroundColor: 'transparent',
                color: colors.accent,
                fontSize: 13,
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'all 150ms ease',
                flex: 1,
                justifyContent: 'center',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = colors.accent;
                e.currentTarget.style.backgroundColor = 'var(--accent-glow)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = colors.border;
                e.currentTarget.style.backgroundColor = 'transparent';
              }}
            >
              <Plus size={16} />
              Add Filter
            </button>
            <button
              onClick={() => setCompositeOpen(true)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '8px 16px',
                borderRadius: 8,
                border: `1px dashed ${colors.border}`,
                backgroundColor: 'transparent',
                color: colors.accent,
                fontSize: 13,
                fontWeight: 600,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = colors.accent;
                e.currentTarget.style.backgroundColor = 'var(--accent-glow)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = colors.border;
                e.currentTarget.style.backgroundColor = 'transparent';
              }}
            >
              <FunctionSquare size={16} />
              Create Composite
            </button>
            {filters.conditions.length > 0 && (
              <button
                onClick={() => {
                  const name = `Macro (${filters.conditions.length} conditions)`;
                  saveMacro(name, filters);
                  setShowMacroSave(true);
                  setMacroName(name);
                  setTimeout(() => setShowMacroSave(false), 2000);
                }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '8px 16px',
                  borderRadius: 8,
                  border: `1px dashed ${colors.border}`,
                  backgroundColor: 'transparent',
                  color: colors.accent,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = colors.accent;
                  e.currentTarget.style.backgroundColor = 'var(--accent-glow)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = colors.border;
                  e.currentTarget.style.backgroundColor = 'transparent';
                }}
              >
                <Layers size={16} />
                Save as Macro
              </button>
            )}
          </div>
          {showMacroSave && (
            <div
              style={{
                marginTop: 8,
                padding: '6px 12px',
                borderRadius: 6,
                backgroundColor: 'var(--accent-glow)',
                color: colors.accent,
                fontSize: 12,
                fontWeight: 500,
                textAlign: 'center',
              }}
            >
              Saved as macro "{macroName}" — find it in the filter picker under Composites
            </div>
          )}
        </div>

        {/* ── Scoring panel ──────────────────────────────── */}
        <ScoringPanel
          baseWeight={baseWeight}
          subWeights={subWeights}
          showAlignment={showAlignment}
          angleWeight={angleWeight}
          hasCrossFilters={hasCrossFilters}
          onBaseWeightChange={setBaseWeight}
          onSubWeightChange={(key, v) => setSubWeights((prev) => ({ ...prev, [key]: v }))}
          onShowAlignmentChange={setShowAlignment}
          onAngleWeightChange={setAngleWeight}
          onReset={() => {
            setBaseWeight(DEFAULT_BASE_WEIGHT);
            setSubWeights(DEFAULT_SUB_WEIGHTS);
            setShowAlignment(DEFAULT_SHOW_ALIGNMENT);
            setAngleWeight(0);
          }}
        />

        {/* ── Sort & Config ──────────────────────────────── */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            marginBottom: 24,
            padding: '16px 20px',
            borderRadius: 12,
            border: `1px solid ${colors.border}`,
            backgroundColor: colors.surface,
          }}
        >
          <div>
            <label
              style={{
                display: 'block',
                fontSize: 11,
                fontWeight: 600,
                color: colors.muted,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: 4,
              }}
            >
              Sort By
            </label>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              style={{
                padding: '8px 10px',
                borderRadius: 6,
                border: `1px solid ${colors.border}`,
                backgroundColor: colors.inputBg,
                color: colors.text,
                fontSize: 13,
                outline: 'none',
              }}
            >
              <option value="score">Score</option>
              <option value="close">Close Price</option>
              <option value="momentum_rsi">RSI</option>
              <option value="volume_ratio">Volume Ratio</option>
              <option value="ath_proximity">ATH Proximity</option>
              <option value="eps_growth_qoq">EPS Growth</option>
              <option value="ticker">Ticker</option>
            </select>
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: 11,
                fontWeight: 600,
                color: colors.muted,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: 4,
              }}
            >
              Order
            </label>
            <select
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value as 'asc' | 'desc')}
              style={{
                padding: '8px 10px',
                borderRadius: 6,
                border: `1px solid ${colors.border}`,
                backgroundColor: colors.inputBg,
                color: colors.text,
                fontSize: 13,
                outline: 'none',
              }}
            >
              <option value="desc">Desc</option>
              <option value="asc">Asc</option>
            </select>
          </div>

          <div style={{ width: 100 }}>
            <label
              style={{
                display: 'block',
                fontSize: 11,
                fontWeight: 600,
                color: colors.muted,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: 4,
              }}
            >
              Max Results
            </label>
            <input
              type="number"
              min={1}
              max={200}
              value={maxResults}
              onChange={(e) => setMaxResults(parseInt(e.target.value, 10) || 50)}
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: 6,
                border: `1px solid ${colors.border}`,
                backgroundColor: colors.inputBg,
                color: colors.text,
                fontSize: 13,
                outline: 'none',
              }}
            />
          </div>

          <div style={{ flex: 1 }} />

          {/* Scan button */}
          <button
            onClick={startScan}
            disabled={isScanning || filters.conditions.length === 0}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 24px',
              borderRadius: 8,
              border: 'none',
              backgroundColor:
                isScanning || filters.conditions.length === 0 ? colors.subtle : colors.accent,
              color:
                isScanning || filters.conditions.length === 0 ? colors.muted : 'var(--accent-ink)',
              fontSize: 14,
              fontWeight: 600,
              cursor:
                isScanning || filters.conditions.length === 0
                  ? 'not-allowed'
                  : 'pointer',
              transition: 'all 150ms ease',
              marginTop: 16,
            }}
            onMouseEnter={(e) => {
              if (!isScanning && filters.conditions.length > 0) {
                e.currentTarget.style.opacity = '0.9';
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = '1';
            }}
          >
            {isScanning ? (
              <>
                <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
                Scanning... {scanProgress}%
              </>
            ) : (
              <>
                <Sparkles size={16} />
                Scan
              </>
            )}
          </button>
        </div>

        {/* ── Progress bar ────────────────────────────────── */}
        {isScanning && (
          <div
            style={{
              marginBottom: 24,
              height: 4,
              borderRadius: 2,
              backgroundColor: colors.border,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${scanProgress}%`,
                height: '100%',
                backgroundColor: colors.accent,
                borderRadius: 2,
                transition: 'width 300ms ease',
              }}
            />
          </div>
        )}

        {/* ── Results ──────────────────────────────────────── */}
        {(scanResults.length > 0 || isScanning || scanError) && (
          <div style={{ marginBottom: 48 }}>
            <ResultsPanel
              results={scanResults}
              loading={isScanning}
              error={scanError}
              returnData={returnData}
              returnLoading={returnLoading}
              cutoffDate={cutoffDate}
              filters={filters}
              showAlignment={showAlignment}
              baseWeight={baseWeight}
              onExport={exportToLab}
              onShowBacktest={() => {
                // Toggle the inline backtest panel (Buy & Hold + With Exit Rules)
                setBacktestExpanded((v) => !v);
              }}
              onTickerClick={openTicker}
            />
            {backtestExpanded && cutoffDate && (
              <div style={{ marginTop: 16 }}>
                <BacktestPanel
                  tickers={scanResults.map((r) => r.ticker)}
                  asOfDate={cutoffDate}
                  customFilters={convertFiltersToBackend(filters)}
                />
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Dialogs ────────────────────────────────────────── */}
      <FilterPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        onSelect={(filterKey) => {
          // Check if this is a macro (starts with __macro__)
          if (filterKey.startsWith('__macro__')) {
            const macro = macros.find((m) => `__macro__${m.id}` === filterKey);
            if (macro) {
              // Expand macro conditions into the builder
              setFilters((prev) => ({
                ...prev,
                conditions: [
                  ...prev.conditions,
                  ...macro.filters.conditions.map((c) => ({ ...c, id: `cond_${Date.now()}_${Math.random()}` })),
                ],
              }));
            }
            return;
          }

          if (filters.conditions.length === 0) {
            addCondition();
          }
          // Update the last condition with the selected filter
          setFilters((prev) => {
            if (prev.conditions.length === 0) return prev;
            const conditions = [...prev.conditions];
            const last = { ...conditions[conditions.length - 1] };
            last.filterKey = filterKey;
            // Reset cross-condition fields when switching filters
            last.referenceFilterKey = undefined;
            last.lookbackDays = undefined;
            last.compareToIndicator = false;
            // Check custom filters first (composites)
            const customFilter = customFilters.find((f: FilterSpec) => f.key === filterKey);
            const spec = customFilter || getFilterByKey(filterKey);
            if (spec) {
              // Categorical filters with fixed `options` (e.g. Sector Regime
              // BULL/BEAR) default to `eq` against their first option so a
              // freshly added row carries a persisted value.
              const hasOptions = spec.type === 'categorical' && (spec.options?.length ?? 0) > 0;
              last.operator =
                spec.type === 'number'
                  ? 'gte'
                  : spec.type === 'cross'
                    ? 'crossed_above'
                    : hasOptions
                      ? 'eq'
                      : 'is_true';
              last.value =
                spec.type === 'number' ? 0
                  : spec.type === 'boolean' ? true
                  : hasOptions ? spec.options![0].value
                  : null;
            }
            conditions[conditions.length - 1] = last;
            return { ...prev, conditions };
          });
        }}
        customFilters={customFilters}
      />

      <ScreenLibraryModal
        open={libraryOpen}
        onOpenChange={setLibraryOpen}
        onLoad={handleLoadPreset}
      />

      <SaveScreenDialog
        open={saveOpen}
        onOpenChange={setSaveOpen}
        onSave={handleSave}
        initialName={screenName}
        mode={saveMode}
      />

      <ShareDialog
        open={shareOpen}
        onOpenChange={setShareOpen}
        screenData={shareData}
      />

      <CompositeBuilder
        open={compositeOpen}
        onOpenChange={setCompositeOpen}
      />

      <TickerDetailDrawer
        ticker={drawerTicker}
        asOfDate={cutoffDate}
        indicators={chartIndicators}
        scoreRow={drawerTicker ? scanResults.find((r) => r.ticker.toUpperCase() === drawerTicker.toUpperCase()) ?? null : null}
        baseWeight={baseWeight}
        onClose={closeDrawer}
        onOpenInChart={openChartView}
        onExportToLab={(t) => {
          // Pre-fill Lab with just this ticker and the current as-of date.
          // Record the referrer first so the QuantGen page's "Back to
          // Custom Screener" button can return here.
          recordAppReferrer('/screener/build', 'Custom Screener');
          const fromDate = cutoffDate || new Date().toISOString().split('T')[0];
          navigate(`/quantgen/build?tickers=${encodeURIComponent(t)}&from_date=${fromDate}`);
          closeDrawer();
        }}
      />
    </div>
  );
}

// ── Style helpers ─────────────────────────────────────────

function headerButtonStyle(colors: Record<string, string>): React.CSSProperties {
  return {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '8px 14px',
    borderRadius: 8,
    border: `1px solid ${colors.border}`,
    backgroundColor: 'transparent',
    color: colors.muted,
    fontSize: 13,
    fontWeight: 500,
    cursor: 'pointer',
    transition: 'all 150ms ease',
  };
}
