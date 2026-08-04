export type FilterCategory =
  | 'trend' | 'momentum' | 'volatility' | 'volume' | 'price'
  | 'valuation' | 'growth_quality' | 'balance_sheet' | 'income'
  | 'ownership' | 'analyst_events' | 'categorical'
  | 'crossover' | 'composite';

export type Operator =
  | 'gt' | 'gte' | 'lt' | 'lte' | 'eq' | 'ne' | 'between'
  | 'crossed_above' | 'crossed_below'
  | 'in' | 'not_in'
  | 'on' | 'between_dates';

export interface OperatorSpec {
  operator: Operator;
  label: string;
  valueType: 'number' | 'range' | 'string' | 'string[]' | 'boolean' | 'cross';
  defaultValue?: unknown;
}

export interface FilterSpec {
  key: string;
  label: string;
  category: FilterCategory;
  type: 'number' | 'range' | 'categorical' | 'boolean' | 'date' | 'cross';
  backendColumn: string;
  defaultParams?: Record<string, number>;
  operators: OperatorSpec[];
  defaultValue?: unknown;
  unit?: string;
  description: string;
  tunable?: boolean;
  /** Fixed selectable options for categorical/select filters (e.g. BULL/BEAR).
   *  When present, FilterRow renders a dropdown whose selection is stored in
   *  the condition's `value`. */
  options?: Array<{ value: string; label: string }>;
  /** Template string for dynamic label, e.g. 'SMA {window}' or 'RSI ({window})'.
   *  When set, the label is computed by substituting param values into this template.
   *  Falls back to the static `label` field when params are empty or template is unset. */
  labelTemplate?: string;
  comingSoon?: boolean;
}

export interface FilterCategoryInfo {
  id: FilterCategory;
  label: string;
  description: string;
}

// ---------------------------------------------------------------------------
// Common operator presets
// ---------------------------------------------------------------------------

const NUMERIC_OPS: OperatorSpec[] = [
  { operator: 'gt', label: '>', valueType: 'number' },
  { operator: 'gte', label: '>=', valueType: 'number' },
  { operator: 'lt', label: '<', valueType: 'number' },
  { operator: 'lte', label: '<=', valueType: 'number' },
  { operator: 'crossed_above', label: 'Crossed Above', valueType: 'cross' },
  { operator: 'crossed_below', label: 'Crossed Below', valueType: 'cross' },
];

const CROSS_OPS: OperatorSpec[] = [
  { operator: 'crossed_above', label: 'Crossed Above', valueType: 'cross' },
  { operator: 'crossed_below', label: 'Crossed Below', valueType: 'cross' },
];

const CATEGORICAL_OPS: OperatorSpec[] = [
  { operator: 'in', label: 'Is In', valueType: 'string[]' },
  { operator: 'not_in', label: 'Is Not In', valueType: 'string[]' },
];

const BOOLEAN_OPS: OperatorSpec[] = [
  { operator: 'eq', label: 'Is', valueType: 'boolean', defaultValue: true },
];

// ---------------------------------------------------------------------------
// Filter catalog
// ---------------------------------------------------------------------------

export const FILTER_CATALOG: FilterSpec[] = [
  // ── Trend (12) ────────────────────────────────────────────────────────────
  {
    key: 'sma_10',
    label: 'SMA 10',
    labelTemplate: 'SMA {window}',
    category: 'trend',
    type: 'number',
    backendColumn: 'sma_10',
    defaultParams: { window: 10 },
    operators: NUMERIC_OPS,
    unit: 'price',
    description: '10-period Simple Moving Average',
    tunable: true,
  },
  {
    key: 'sma_20',
    label: 'SMA 20',
    labelTemplate: 'SMA {window}',
    category: 'trend',
    type: 'number',
    backendColumn: 'trend_sma_fast',
    defaultParams: { window: 20 },
    operators: NUMERIC_OPS,
    unit: 'price',
    description: '20-period Simple Moving Average',
    tunable: true,
  },
  {
    key: 'sma_50',
    label: 'SMA 50',
    labelTemplate: 'SMA {window}',
    category: 'trend',
    type: 'number',
    backendColumn: 'trend_sma_slow',
    defaultParams: { window: 50 },
    operators: NUMERIC_OPS,
    unit: 'price',
    description: '50-period Simple Moving Average',
    tunable: true,
  },
  {
    key: 'sma_100',
    label: 'SMA 100',
    labelTemplate: 'SMA {window}',
    category: 'trend',
    type: 'number',
    backendColumn: 'sma_100',
    defaultParams: { window: 100 },
    operators: NUMERIC_OPS,
    unit: 'price',
    description: '100-period Simple Moving Average',
    tunable: true,
  },
  {
    key: 'sma_200',
    label: 'SMA 200',
    labelTemplate: 'SMA {window}',
    category: 'trend',
    type: 'number',
    backendColumn: 'sma_200',
    defaultParams: { window: 200 },
    operators: NUMERIC_OPS,
    unit: 'price',
    description: '200-period Simple Moving Average',
    tunable: true,
  },
  {
    key: 'ema_20',
    label: 'EMA 20',
    labelTemplate: 'EMA {window}',
    category: 'trend',
    type: 'number',
    backendColumn: 'ema_20',
    defaultParams: { window: 20 },
    operators: NUMERIC_OPS,
    unit: 'price',
    description: '20-period Exponential Moving Average',
    tunable: true,
  },
  {
    key: 'ema_12',
    label: 'EMA 12',
    labelTemplate: 'EMA {window}',
    category: 'trend',
    type: 'number',
    backendColumn: 'trend_ema_fast',
    defaultParams: { window: 12 },
    operators: NUMERIC_OPS,
    unit: 'price',
    description: '12-period Exponential Moving Average',
    tunable: true,
  },
  {
    key: 'ema_26',
    label: 'EMA 26',
    labelTemplate: 'EMA {window}',
    category: 'trend',
    type: 'number',
    backendColumn: 'trend_ema_slow',
    defaultParams: { window: 26 },
    operators: NUMERIC_OPS,
    unit: 'price',
    description: '26-period Exponential Moving Average',
    tunable: true,
  },
  {
    key: 'adx',
    label: 'ADX (14)',
    labelTemplate: 'ADX ({window})',
    category: 'trend',
    type: 'number',
    backendColumn: 'trend_adx',
    defaultParams: { window: 14 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Average Directional Index (0-100) — measures trend strength',
    tunable: true,
  },
  {
    key: 'macd',
    label: 'MACD',
    labelTemplate: 'MACD ({window_fast}, {window_slow}, {window_sign})',
    category: 'trend',
    type: 'number',
    backendColumn: 'trend_macd',
    defaultParams: { window_fast: 12, window_slow: 26, window_sign: 9 },
    operators: NUMERIC_OPS,
    description: 'Moving Average Convergence Divergence — trend-following momentum indicator',
    tunable: true,
  },

  {
    key: 'trix',
    label: 'TRIX (15)',
    labelTemplate: 'TRIX ({window})',
    category: 'trend',
    type: 'number',
    backendColumn: 'trend_trix',
    defaultParams: { window: 15 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Triple Exponential Average — percentage rate of change of a triple EMA',
    tunable: true,
  },
  {
    key: 'mass_index',
    label: 'Mass Index',
    category: 'trend',
    type: 'number',
    backendColumn: 'trend_mass_index',
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Mass Index — identifies trend reversals based on high-low range expansion',
    tunable: true,
  },
  {
    key: 'aroon_up',
    label: 'Aroon Up (25)',
    labelTemplate: 'Aroon Up ({window})',
    category: 'trend',
    type: 'number',
    backendColumn: 'trend_aroon_up',
    defaultParams: { window: 25 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Aroon Up — measures time since last high (0-100)',
    tunable: true,
  },
  {
    key: 'aroon_down',
    label: 'Aroon Down (25)',
    labelTemplate: 'Aroon Down ({window})',
    category: 'trend',
    type: 'number',
    backendColumn: 'trend_aroon_down',
    defaultParams: { window: 25 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Aroon Down — measures time since last low (0-100)',
    tunable: true,
  },
  {
    key: 'aroon_ind',
    label: 'Aroon Indicator',
    labelTemplate: 'Aroon Indicator ({window})',
    category: 'trend',
    type: 'number',
    backendColumn: 'trend_aroon_ind',
    defaultParams: { window: 25 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Aroon Indicator — Aroon Up minus Aroon Down (-100 to 100)',
    tunable: true,
  },
  {
    key: 'stc',
    label: 'Schaff Trend Cycle',
    category: 'trend',
    type: 'number',
    backendColumn: 'trend_stc',
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Schaff Trend Cycle — identifies trend direction and cycle position (0-100)',
    tunable: true,
  },

  // ── Momentum (10) ───────────────────────────────────────────────────────
  {
    key: 'rsi',
    label: 'RSI (14)',
    labelTemplate: 'RSI ({window})',
    category: 'momentum',
    type: 'number',
    backendColumn: 'momentum_rsi',
    defaultParams: { window: 14 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Relative Strength Index (0-100) — measures speed and magnitude of price changes',
    tunable: true,
  },
  {
    key: 'stoch_k',
    label: 'Stochastic %K (14,3)',
    labelTemplate: 'Stochastic %K ({window},{smooth_window})',
    category: 'momentum',
    type: 'number',
    backendColumn: 'momentum_stoch',
    defaultParams: { window: 14, smooth_window: 3 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Stochastic Oscillator %K — compares close to high-low range',
    tunable: true,
  },
  {
    key: 'williams_r',
    label: 'Williams %R (14)',
    labelTemplate: 'Williams %R ({lbp})',
    category: 'momentum',
    type: 'number',
    backendColumn: 'momentum_wr',
    defaultParams: { lbp: 14 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Williams Percent Range — overbought/oversold indicator (-100 to 0)',
    tunable: true,
  },
  {
    key: 'roc',
    label: 'Rate of Change (12)',
    labelTemplate: 'Rate of Change ({window})',
    category: 'momentum',
    type: 'number',
    backendColumn: 'momentum_roc',
    defaultParams: { window: 12 },
    operators: NUMERIC_OPS,
    unit: '%',
    description: 'Rate of Change — percentage change between current price and price n periods ago',
    tunable: true,
  },
  {
    key: 'cci',
    label: 'CCI (20)',
    labelTemplate: 'CCI ({window})',
    category: 'momentum',
    type: 'number',
    backendColumn: 'trend_cci',
    defaultParams: { window: 20 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Commodity Channel Index — identifies cyclical trends and overbought/oversold levels',
    tunable: true,
  },
  {
    key: 'ppo',
    label: 'Percentage Price Oscillator',
    labelTemplate: 'PPO ({window_fast}, {window_slow}, {window_sign})',
    category: 'momentum',
    type: 'number',
    backendColumn: 'momentum_ppo',
    defaultParams: { window_fast: 12, window_slow: 26, window_sign: 9 },
    operators: NUMERIC_OPS,
    unit: '%',
    description: 'Percentage Price Oscillator — MACD as percentage of price (12,26,9)',
    tunable: true,
  },
  {
    key: 'kama',
    label: 'KAMA (10)',
    labelTemplate: 'KAMA ({window})',
    category: 'momentum',
    type: 'number',
    backendColumn: 'momentum_kama',
    defaultParams: { window: 10, pow1: 2, pow2: 30 },
    operators: NUMERIC_OPS,
    unit: 'price',
    description: 'Kaufman Adaptive Moving Average — adjusts sensitivity based on market noise',
    tunable: true,
  },
  {
    key: 'awesome_osc',
    label: 'Awesome Oscillator',
    category: 'momentum',
    type: 'number',
    backendColumn: 'momentum_ao',
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Awesome Oscillator — difference between 5-period and 34-period simple moving averages',
    tunable: true,
  },
  {
    key: 'tsi',
    label: 'True Strength Index',
    labelTemplate: 'TSI ({window_slow}, {window_fast})',
    category: 'momentum',
    type: 'number',
    backendColumn: 'momentum_tsi',
    defaultParams: { window_slow: 25, window_fast: 13 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'True Strength Index — measures trend strength and direction',
    tunable: true,
  },
  {
    key: 'ultimate_osc',
    label: 'Ultimate Oscillator',
    category: 'momentum',
    type: 'number',
    backendColumn: 'momentum_uo',
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Ultimate Oscillator — multi-timeframe momentum oscillator (0-100)',
    tunable: true,
  },
  {
    key: 'demarker',
    label: 'DeMarker (14)',
    labelTemplate: 'DeMarker ({window})',
    category: 'momentum',
    type: 'number',
    backendColumn: 'momentum_demarker',
    defaultParams: { window: 14 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'DeMarker (Tom DeMark) — momentum oscillator on High/Low price action. 0-1 scale; 0.7+ overbought, 0.3- oversold.',
    tunable: true,
  },

  // ── Volatility (3) ──────────────────────────────────────────────────────
  {
    key: 'bb_width',
    label: 'Bollinger Band Width (20,2)',
    labelTemplate: 'Bollinger Band Width ({window},{window_dev})',
    category: 'volatility',
    type: 'number',
    backendColumn: 'volatility_bbw',
    defaultParams: { window: 20, window_dev: 2 },
    operators: NUMERIC_OPS,
    unit: '%',
    description: 'Bollinger Band Width — width of bands as percentage of middle band',
    tunable: true,
  },
  {
    key: 'bb_pct_b',
    label: 'Bollinger Band %B (20,2)',
    labelTemplate: 'Bollinger Band %B ({window},{window_dev})',
    category: 'volatility',
    type: 'number',
    backendColumn: 'volatility_bbp',
    defaultParams: { window: 20, window_dev: 2 },
    operators: NUMERIC_OPS,
    unit: '%',
    description: 'Bollinger Band %B — price position within the bands (0-100)',
    tunable: true,
  },
  {
    key: 'atr',
    label: 'ATR (14)',
    labelTemplate: 'ATR ({window})',
    category: 'volatility',
    type: 'number',
    backendColumn: 'volatility_atr',
    defaultParams: { window: 14 },
    operators: NUMERIC_OPS,
    unit: 'price',
    description: 'Average True Range — market volatility measure based on high-low range',
    tunable: true,
  },
  {
    key: 'kc_width',
    label: 'Keltner Channel Width (20)',
    labelTemplate: 'Keltner Channel Width ({window})',
    category: 'volatility',
    type: 'number',
    backendColumn: 'volatility_kcw',
    defaultParams: { window: 20 },
    operators: NUMERIC_OPS,
    unit: 'price',
    description: 'Keltner Channel Width — volatility measure based on ATR',
    tunable: true,
  },
  {
    key: 'ulcer_index',
    label: 'Ulcer Index (14)',
    labelTemplate: 'Ulcer Index ({window})',
    category: 'volatility',
    type: 'number',
    backendColumn: 'volatility_ui',
    defaultParams: { window: 14 },
    operators: NUMERIC_OPS,
    unit: '%',
    description: 'Ulcer Index — downside risk and drawdown severity measure',
    tunable: true,
  },

  // ── Volume (4) ──────────────────────────────────────────────────────────
  {
    key: 'volume',
    label: 'Volume',
    category: 'volume',
    type: 'number',
    backendColumn: 'Volume',
    operators: NUMERIC_OPS,
    unit: 'shares',
    description: 'Daily trading volume',
  },
  {
    key: 'volume_ratio',
    label: 'Volume Ratio (vs 50d avg)',
    category: 'volume',
    type: 'number',
    backendColumn: 'volume_ratio',
    operators: NUMERIC_OPS,
    unit: '×',
    description: 'Current volume divided by 50-day average volume',
  },
  {
    key: 'mfi',
    label: 'MFI (14)',
    labelTemplate: 'MFI ({window})',
    category: 'volume',
    type: 'number',
    backendColumn: 'volume_mfi',
    defaultParams: { window: 14 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Money Flow Index (0-100) — volume-weighted RSI measuring buying/selling pressure',
    tunable: true,
  },
  {
    key: 'obv',
    label: 'OBV',
    category: 'volume',
    type: 'number',
    backendColumn: 'volume_obv',
    operators: NUMERIC_OPS,
    description: 'On-Balance Volume — cumulative volume indicator relating volume to price change',
  },
  {
    key: 'cmf',
    label: 'Chaikin Money Flow (20)',
    labelTemplate: 'Chaikin Money Flow ({window})',
    category: 'volume',
    type: 'number',
    backendColumn: 'volume_cmf',
    defaultParams: { window: 20 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Chaikin Money Flow — accumulation/distribution over 20 periods',
    tunable: true,
  },
  {
    key: 'force_index',
    label: 'Force Index (13)',
    labelTemplate: 'Force Index ({window})',
    category: 'volume',
    type: 'number',
    backendColumn: 'volume_fi',
    defaultParams: { window: 13 },
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Force Index — measures price movement strength relative to volume',
    tunable: true,
  },
  {
    key: 'vwap',
    label: 'VWAP',
    category: 'volume',
    type: 'number',
    backendColumn: 'volume_vwap',
    operators: NUMERIC_OPS,
    unit: 'price',
    description: 'Volume Weighted Average Price — average price weighted by volume',
  },
  {
    key: 'adi',
    label: 'A/D Index',
    category: 'volume',
    type: 'number',
    backendColumn: 'volume_adi',
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Accumulation/Distribution Index — cumulative flow of volume-adjusted price',
  },
  {
    key: 'nvi',
    label: 'Negative Volume Index',
    category: 'volume',
    type: 'number',
    backendColumn: 'volume_nvi',
    operators: NUMERIC_OPS,
    unit: 'pts',
    description: 'Negative Volume Index — focuses on days when volume decreases',
  },

  // ── Price (4) ───────────────────────────────────────────────────────────
  {
    key: 'daily_return',
    label: 'Daily Return %',
    category: 'price',
    type: 'number',
    backendColumn: 'others_dr',
    operators: NUMERIC_OPS,
    unit: '%',
    description: 'Daily percentage price change',
  },
  {
    key: 'close',
    label: 'Close',
    category: 'price',
    type: 'number',
    backendColumn: 'close',
    operators: NUMERIC_OPS,
    unit: 'price',
    description: 'Closing price',
  },
  {
    key: 'ath_proximity',
    label: 'ATH Proximity',
    category: 'price',
    type: 'number',
    backendColumn: 'ath_proximity',
    operators: NUMERIC_OPS,
    unit: '%',
    description: 'Close as % of all-time high',
  },
  {
    key: 'high_52w',
    label: '52W High',
    category: 'price',
    type: 'number',
    backendColumn: 'high_52w',
    operators: NUMERIC_OPS,
    unit: 'price',
    description: '52-week high price',
  },

  // ── Valuation (3) ───────────────────────────────────────────────────────
  {
    key: 'market_cap',
    label: 'Market Cap',
    category: 'valuation',
    type: 'number',
    backendColumn: 'market_cap',
    operators: NUMERIC_OPS,
    unit: '$B',
    description: 'Market capitalization in billions',
  },
  {
    key: 'pe_ttm',
    label: 'P/E Ratio (TTM)',
    category: 'valuation',
    type: 'number',
    backendColumn: 'pe_ttm',
    operators: NUMERIC_OPS,
    unit: '×',
    description: 'Price-to-Earnings ratio (trailing twelve months)',
  },
  {
    key: 'peg_ratio',
    label: 'PEG Ratio',
    category: 'valuation',
    type: 'number',
    backendColumn: 'peg_ratio',
    operators: NUMERIC_OPS,
    unit: '×',
    description: 'P/E ratio divided by earnings growth rate',
  },

  // ── Growth & Quality (4) ────────────────────────────────────────────────
  {
    key: 'eps_growth_qoq',
    label: 'EPS Growth QoQ',
    category: 'growth_quality',
    type: 'number',
    backendColumn: 'eps_growth_qoq',
    operators: NUMERIC_OPS,
    unit: '%',
    description: 'Quarter-over-quarter earnings per share growth',
  },
  {
    key: 'eps_growth_yoy',
    label: 'EPS Growth YoY',
    category: 'growth_quality',
    type: 'number',
    backendColumn: 'eps_growth_yoy',
    operators: NUMERIC_OPS,
    unit: '%',
    description: 'Year-over-year earnings per share growth',
  },
  {
    key: 'revenue_growth_qoq',
    label: 'Revenue Growth QoQ',
    category: 'growth_quality',
    type: 'number',
    backendColumn: 'revenue_growth_qoq',
    operators: NUMERIC_OPS,
    unit: '%',
    description: 'Quarter-over-quarter revenue growth',
  },
  {
    key: 'revenue_growth_yoy',
    label: 'Revenue Growth YoY',
    category: 'growth_quality',
    type: 'number',
    backendColumn: 'revenue_growth_yoy',
    operators: NUMERIC_OPS,
    unit: '%',
    description: 'Year-over-year revenue growth',
  },

  // ── Crossover (1) ───────────────────────────────────────────────────────
  {
    key: 'crossover',
    label: 'Crossover',
    category: 'crossover',
    type: 'cross',
    backendColumn: 'crossover',
    operators: CROSS_OPS,
    description: 'One indicator crossing above or below another',
  },

  // ── Composite (5) ───────────────────────────────────────────────────────
  {
    key: 'volatility_bbw_pct',
    label: 'Bollinger Squeeze',
    category: 'composite',
    type: 'number',
    backendColumn: 'volatility_bbw_pct',
    operators: NUMERIC_OPS,
    unit: '%',
    description: 'Bollinger Bandwidth percentile (lower = tighter squeeze)',
  },
  {
    key: 'volume_cluster_count',
    label: 'Volume Cluster',
    category: 'composite',
    type: 'number',
    backendColumn: 'volume_cluster_count',
    operators: NUMERIC_OPS,
    unit: 'days',
    description: 'Days with volume >1.2x average in last 5',
  },
  {
    key: 'consolidation_tightness',
    label: 'Consolidation Tightness',
    category: 'composite',
    type: 'number',
    backendColumn: 'consolidation_tightness',
    operators: NUMERIC_OPS,
    unit: '%',
    description: '% of days within 3% of SMA(20)',
  },
  {
    key: 'rs_vs_sector',
    label: 'RS vs Sector',
    category: 'composite',
    type: 'number',
    backendColumn: 'rs_vs_sector',
    operators: NUMERIC_OPS,
    unit: 'x',
    description: '20-day relative strength ratio vs sector ETF',
  },
  {
    key: 'sector_above_sma50',
    label: 'Sector Above SMA50',
    category: 'composite',
    type: 'boolean',
    backendColumn: 'sector_above_sma50',
    operators: BOOLEAN_OPS,
    description: 'Sector ETF is above its 50-day SMA',
  },

  // ── Categorical (1) ─────────────────────────────────────────────────────
  {
    key: 'sector',
    label: 'Sector',
    category: 'categorical',
    type: 'categorical',
    backendColumn: 'sector',
    operators: CATEGORICAL_OPS,
    description: 'Stock sector',
  },
  {
    key: 'regime',
    label: 'Sector Regime',
    category: 'categorical',
    type: 'categorical',
    backendColumn: 'regime',
    operators: [
      { operator: 'eq', label: 'Is', valueType: 'string', defaultValue: 'BULL' },
    ],
    options: [
      { value: 'BULL', label: 'BULL' },
      { value: 'BEAR', label: 'BEAR' },
    ],
    description: 'Filter by sector ETF Markov regime (BULL requires bull_probability > 0.5)',
  },
];

// ---------------------------------------------------------------------------
// Filter categories
// ---------------------------------------------------------------------------

export const FILTER_CATEGORIES: FilterCategoryInfo[] = [
  { id: 'trend', label: 'Trend', description: 'Moving averages and trend strength' },
  { id: 'momentum', label: 'Momentum', description: 'Price momentum and oscillator indicators' },
  { id: 'volatility', label: 'Volatility', description: 'Price volatility and band indicators' },
  { id: 'volume', label: 'Volume', description: 'Volume-based indicators' },
  { id: 'price', label: 'Price', description: 'Price levels and proximity' },
  { id: 'valuation', label: 'Valuation', description: 'Fundamental valuation metrics' },
  { id: 'growth_quality', label: 'Growth & Quality', description: 'Earnings and revenue growth' },
  { id: 'crossover', label: 'Crossover', description: 'Cross-indicator comparisons' },
  { id: 'composite', label: 'Composite', description: 'Derived multi-indicator metrics' },
  { id: 'categorical', label: 'Categorical', description: 'Stock attributes and categories' },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Look up a filter spec by its key. */
export function getFilterByKey(key: string): FilterSpec | undefined {
  return FILTER_CATALOG.find((f) => f.key === key);
}

/** Get all filters for a given category. */
export function getFiltersByCategory(category: FilterCategory): FilterSpec[] {
  return FILTER_CATALOG.filter((f) => f.category === category);
}

/** Get the default operator for a filter (first in the list). */
export function getDefaultOperator(filter: FilterSpec): OperatorSpec {
  return filter.operators[0];
}

/**
 * Compute a dynamic label by substituting param values into a labelTemplate.
 * Falls back to the static `label` when no template is set or params are empty.
 *
 * Examples:
 *   getDynamicLabel({ label: 'SMA 20', labelTemplate: 'SMA {window}' }, { window: 40 })
 *   → 'SMA 40'
 *
 *   getDynamicLabel({ label: 'RSI (14)', labelTemplate: 'RSI ({window})' }, { window: 7 })
 *   → 'RSI (7)'
 */
export function getDynamicLabel(
  spec: FilterSpec,
  params?: Record<string, number>,
): string {
  if (!spec.labelTemplate || !params || Object.keys(params).length === 0) {
    return spec.label;
  }
  let label = spec.labelTemplate;
  for (const [key, val] of Object.entries(params)) {
    label = label.replace(new RegExp(`\\{${key}\\}`, 'g'), String(val));
  }
  return label;
}

// ---------------------------------------------------------------------------
// Filter → Results-table columns
// ---------------------------------------------------------------------------

/**
 * Column metadata derived from an active filter. Used by ResultsPanel to render
 * one column per indicator that's actually referenced by the user's filters.
 */
export interface ResultsColumn {
  /** Backend column name as it appears in the scan result row. */
  dataKey: string;
  /**
   * Unique key used to disambiguate columns that share a backend column but
   * differ by params (e.g. ema_20 w=20 vs ema_20 w=200). Default-param
   * requests reuse `dataKey`; override requests append a short signature.
   */
  payloadKey: string;
  /** Header label to show in the table (already includes window params). */
  header: string;
  /**
   * True for the left-hand side of a crossover (e.g. SMA50 in
   * "SMA50 crossed above SMA200"). Both sides share the same row, but
   * callers may want to render them with slightly different emphasis.
   */
  isCrossoverSide?: 'primary' | 'reference';
  /**
   * Optional custom-param override that should be forwarded to the chart
   * endpoint so the same indicator with non-default params is recomputed
   * server-side (e.g. EMA with window=200 even though backendColumn is
   * `ema_20` which defaults to window=20).
   */
  params?: Record<string, number>;
}

/** Stable short signature for an indicator-params dict, mirroring the
 *  backend's `_params_signature` in `chart_data.py`. Two requests with the
 *  same params collapse to the same signature so the dedup key in
 *  `getColumnsForFilters` only collapses genuinely-duplicate columns. */
function paramsSignature(params?: Record<string, number>): string {
  if (!params || Object.keys(params).length === 0) return "";
  const items = Object.keys(params)
    .sort()
    .map((k) => `${k}${params[k]}`);
  return items.join("_");
}

/**
 * Walk a list of FilterConditions and return one column per indicator
 * actually referenced by the user's filters. Useful for making the Results
 * table dynamically add columns for the indicators being tested, instead of
 * showing a fixed set of metrics unrelated to the screen.
 *
 * Behavior:
 * - Number/date filter (e.g. RSI < 30): one column for the filter's indicator.
 * - Crossover or indicator-comparison filter (e.g. SMA50 crossed above SMA200):
 *   two columns — primary + reference — in filter order.
 * - Composite / categorical / boolean: skipped (they don't map to a single
 *   indicator column).
 *
 * Duplicates are de-duplicated by `payloadKey` (dataKey + params signature)
 * so that two requests for the same `ema_20` column with different windows
 * both appear as separate columns.
 *
 * Example:
 *   getColumnsForFilters([{ filterKey: 'ema_20', operator: 'crossed_above',
 *                          referenceFilterKey: 'sma_200' }])
 *   → [
 *       { dataKey: 'ema_20', payloadKey: 'ema_20', header: 'EMA 20' },
 *       { dataKey: 'sma_200', payloadKey: 'sma_200', header: 'SMA 200' },
 *     ]
 */
export function getColumnsForFilters(
  conditions: Array<{
    filterKey: string;
    operator?: string;
    referenceFilterKey?: string;
    params?: Record<string, number>;
    referenceParams?: Record<string, number>;
    compareToIndicator?: boolean;
  }>,
): ResultsColumn[] {
  const out: ResultsColumn[] = [];
  const seen = new Set<string>();

  const push = (col: ResultsColumn) => {
    if (!col.dataKey || seen.has(col.payloadKey)) return;
    seen.add(col.payloadKey);
    out.push(col);
  };

  for (const cond of conditions) {
    const spec = getFilterByKey(cond.filterKey);
    if (!spec) continue;

    // Skip non-numeric categories — they don't map to a single indicator column.
    // Composite filters aggregate multiple indicators (they show in Score, not columns).
    // Categorical filters don't have a numeric value to display.
    if (spec.type !== 'number') continue;
    if (spec.category === 'composite') continue;

    const primaryDataKey = spec.backendColumn || cond.filterKey;
    const primarySig = paramsSignature(cond.params);
    push({
      dataKey: primaryDataKey,
      payloadKey: primarySig ? `${primaryDataKey}__${primarySig}` : primaryDataKey,
      header: getDynamicLabel(spec, cond.params),
      isCrossoverSide: 'primary',
      params: cond.params,
    });

    // Crossover (operator = crossed_above/crossed_below) AND indicator-vs-indicator
    // comparison (compareToIndicator = true) both reference a second indicator.
    const isCrossOrCompare =
      cond.operator === 'crossed_above' ||
      cond.operator === 'crossed_below' ||
      cond.compareToIndicator === true;

    if (isCrossOrCompare && cond.referenceFilterKey) {
      const refSpec = getFilterByKey(cond.referenceFilterKey);
      if (refSpec && refSpec.type === 'number' && refSpec.category !== 'composite') {
        const refDataKey = refSpec.backendColumn || cond.referenceFilterKey;
        const refSig = paramsSignature(cond.referenceParams);
        push({
          dataKey: refDataKey,
          payloadKey: refSig ? `${refDataKey}__${refSig}` : refDataKey,
          header: getDynamicLabel(refSpec, cond.referenceParams),
          isCrossoverSide: 'reference',
          params: cond.referenceParams,
        });
      }
    }
  }

  return out;
}
