"""
Filter parsing and application for Quant Strategy screening.
Extracted from agno_screener.py for better maintainability.
"""

import logging
import json
from typing import Dict, Any

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

QUANT_FILTER_SCHEMA = {
    "ath_proximity_min": "float|null  // 0-1, e.g. 0.95 = within 5% of ATH",
    "ath_proximity_max": "float|null",
    "rsi_min": "float|null  // 0-100",
    "rsi_max": "float|null  // 0-100",
    "volume_ratio_min": "float|null  // vs 50-day avg",
    "sma_20_relation": "'above'|'below'|'any'",
    "sma_50_relation": "'above'|'below'|'any'",
    "sector_whitelist": "[string]  // e.g. ['Technology','Healthcare']",
    "market_cap_min": "float|null  // in billions",
    "market_cap_max": "float|null  // in billions",
    "eps_growth_min": "float|null  // decimal, e.g. 0.10 = 10%",
    "revenue_growth_min": "float|null  // decimal, e.g. 0.10 = 10%",
    "sort_by": "'ticker'|'ath_proximity'|'rsi'|'volume_ratio'|'close'",
    "sort_order": "'asc'|'desc'",
    "max_results": "int  // default 20",
    "earnings_within_days": "int|null  // e.g. 10 = next earnings within 10 days. null means ignore.",
    "indicator_filters": "[{column: string, params?: {window?: int, ...}, min?: float, max?: float, condition?: 'above'|'below'|'equals', reference_column?: string, reference_params?: {window?: int, ...}}]  // dynamic indicator filters. Use condition+reference_column for cross-indicator comparisons (e.g. EMA above SMA). Use min/max for threshold-based filters."
}

# Catalog of available technical indicators for the LLM parser
INDICATOR_CATALOG = """
Available technical indicators (use exact column names):
  momentum_rsi — RSI (Relative Strength Index), default window=14
  momentum_stoch — Stochastic Oscillator, default window=14
  momentum_stoch_signal — Stochastic Signal, default window=14
  momentum_wr — Williams %R, default lbp=14
  momentum_ao — Awesome Oscillator
  momentum_roc — Rate of Change, default window=12
  momentum_tsi — True Strength Index, default window_slow=25, window_fast=13
  momentum_uo — Ultimate Oscillator
  momentum_kama — KAMA (Kaufman Adaptive Moving Average), default window=10
  volatility_bbw — Bollinger Band Width, default window=20, window_dev=2
  volatility_bbp — Bollinger Band Percentage, default window=20, window_dev=2
  volatility_bbh — Bollinger Band High, default window=20, window_dev=2
  volatility_bbl — Bollinger Band Low, default window=20, window_dev=2
  volatility_atr — Average True Range, default window=14
  volatility_ui — Ulcer Index, default window=14
  trend_sma_fast — SMA 20
  trend_sma_slow — SMA 50
  trend_ema_fast — EMA 12
  trend_ema_slow — EMA 26
  trend_macd — MACD line, default window_slow=26, window_fast=12, window_sign=9
  trend_macd_signal — MACD Signal line
  trend_macd_diff — MACD Histogram
  trend_adx — ADX (Average Directional Index), default window=14
  trend_cci — CCI (Commodity Channel Index), default window=20
  trend_trix — TRIX, default window=15
  trend_mass_index — Mass Index
  trend_aroon_up — Aroon Up, default window=25
  trend_aroon_down — Aroon Down, default window=25
  trend_aroon_ind — Aroon Indicator, default window=25
  trend_stc — Schaff Trend Cycle
  volume_mfi — MFI (Money Flow Index), default window=14
  volume_cmf — CMF (Chaikin Money Flow), default window=20
  volume_obv — OBV (On-Balance Volume)
  volume_fi — Force Index, default window=13
  volume_vwap — VWAP (Volume Weighted Average Price)
  volume_adi — Accumulation/Distribution Index
  volume_nvi — Negative Volume Index

  custom_ema_pct_change — EMA Percentage Change (day-over-day % change of EMA). Parameter: period (default 9). Scale: percentage (can be positive or negative).
"""

FILTER_PARSER_PROMPT = """You are a stock screener filter parser.
Convert the user's request into a JSON object matching this schema exactly.
Only include non-null fields. Return ONLY valid JSON, no markdown, no explanation.

Schema fields:
{schema}

Available indicators:
{indicators}

Indicator scales (CRITICAL — these determine what min/max values to use):
- momentum_rsi: 0–100 scale. 70+ = overbought, 30- = oversold.
- volatility_bbw: Percentage scale (e.g., 5.0 = 5%). Squeeze = under 6.0–10.0. Wide bands = 20+.
- volatility_bbp: 0–1 scale (percentage of band position).
- volatility_atr: Raw price scale (dollar amount of average true range).
- trend_macd: Raw price scale (can be positive or negative).
- trend_adx: 0–100 scale. 25+ = trending, 50+ = strong trend.
- trend_cci: Unbounded scale. +100/-100 are common thresholds.
- momentum_stoch: 0–100 scale. 80+ = overbought.
- momentum_wr: -100–0 scale. -20 = overbought, -80 = oversold.
- momentum_roc: Percentage scale (e.g., 5.0 = 5% change).
- volume_mfi: 0–100 scale. 80+ = overbought on volume.
- volume_cmf: Unbounded scale. +0.05/-0.05 are common thresholds.
- custom_ema_pct_change: Percentage scale (can be positive or negative). Measures day-over-day % change of EMA. Use min > 0 for accelerating EMA, max < 0 for decelerating EMA.

Parameter customization:
- Any indicator can include a "params" object to override default parameters.
- Example: RSI with window=7: {{"column": "momentum_rsi", "params": {{"window": 7}}, "min": 0, "max": 30}}
- Example: Bollinger Band Width squeeze: {{"column": "volatility_bbw", "max": 6.0}}
- Example: MACD above signal: {{"column": "trend_macd", "min": 0}}
- Example: Strong trend (ADX > 25): {{"column": "trend_adx", "min": 25}}
- Example: EMA(20) percentage change accelerating: {{"column": "custom_ema_pct_change", "params": {{"period": 20}}, "min": 1.0}}

Cross-indicator comparisons (CRITICAL — use this for EMA vs SMA, MACD vs Signal, etc.):
- When the user asks for one indicator relative to another (e.g. "EMA(9) above SMA(20)", "MACD above signal", "price above SMA"), DO NOT use min/max.
- Instead, use "condition" + "reference_column" (+ optional "reference_params"):
  - Example: EMA(9) above SMA(20): {{"column": "trend_ema_fast", "params": {{"window": 9}}, "condition": "above", "reference_column": "trend_sma_fast", "reference_params": {{"window": 20}}}}
  - Example: MACD above signal: {{"column": "trend_macd", "condition": "above", "reference_column": "trend_macd_signal"}}
  - Example: Price above SMA 50: {{"column": "close", "condition": "above", "reference_column": "trend_sma_slow"}}
  - Example: SMA(20) below SMA(50): {{"column": "trend_sma_fast", "params": {{"window": 20}}, "condition": "below", "reference_column": "trend_sma_slow", "reference_params": {{"window": 50}}}}
- Valid conditions: "above", "below", "equals".
- Both "column" and "reference_column" must be exact names from the indicator catalog.
- If the user specifies custom windows (e.g. "EMA(9)" vs default EMA 12), include "params" and "reference_params".

Logic guidance:
- If the user combines contradictory conditions (e.g., "high RSI AND volatility squeeze"), both must be true simultaneously. A stock in a squeeze has low recent movement, so RSI is unlikely to be > 70. Expect 0 results.
- Use the indicator_filters array for ALL indicator-based conditions. Reserve the legacy rsi_min/max fields only for simple RSI-only prompts.
- If an indicator reference is ambiguous (e.g., "RSI"), default to "momentum_rsi".
- When the user says "X above Y" or "X below Y", ALWAYS use condition+reference_column. Never approximate with min/max.

Default rules:
- If user asks for stocks "close to all time high", set ath_proximity_min to 0.90-0.98 depending on wording (very close = 0.98, close = 0.95, near = 0.90).
- If user specifies a count (e.g. "top 20", "find 50"), set max_results to that number.
- sort_by defaults to "ath_proximity" if ATH mentioned, otherwise "ticker".
- sort_order defaults to "desc" for proximity-based sorts, "asc" for ticker.
- sma_20_relation and sma_50_relation default to "any".
- sector_whitelist should be exact sector names as they appear in stock_metadata (e.g. "Technology", "Healthcare", "Financials").
- When the user references an indicator not in the catalog, map it to the closest available indicator by name.
- Use "indicator_filters" for any indicator-based condition beyond the legacy rsi_min/max fields.

Earnings calendar filter:
- When the user mentions earnings (e.g., "earnings tomorrow", "reports next week", "upcoming earnings"), set earnings_within_days accordingly.
- "earnings tomorrow" -> earnings_within_days: 1
- "earnings this week" -> earnings_within_days: 7
- "earnings next week" -> earnings_within_days: 14
- "earnings in 10 days" -> earnings_within_days: 10
- "no earnings soon" or "avoid earnings" -> earnings_within_days: 0 (only stocks with NO earnings in the immediate future)
- If the user doesn't mention earnings, leave earnings_within_days as null.
""".format(
    schema="\n".join(f'  "{k}": {v}' for k, v in QUANT_FILTER_SCHEMA.items()),
    indicators=INDICATOR_CATALOG
)


def parse_quant_filters(prompt: str) -> Dict[str, Any]:
    """Parse a natural language prompt into structured QuantFilters using an LLM."""
    from agno.agent import Agent
    from agno.models.ollama import Ollama
    import json

    try:
        parser = Agent(
            model=Ollama(id=OLLAMA_MODEL_ID, options={"num_ctx": 8192}),
            instructions=FILTER_PARSER_PROMPT,
            markdown=False,
        )
        response = parser.run(prompt)
        content = response.content if hasattr(response, 'content') else str(response)

        if content is None:
            content = ""

        # Extract JSON from the response
        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end != -1 and end > start:
            filters = json.loads(content[start:end + 1])
        else:
            filters = {}
    except Exception as e:
        logger.warning("Filter parsing failed: %s. Returning empty filters.", e)
        filters = {}

    # Normalize and set sensible defaults
    normalized: Dict[str, Any] = {
        "ath_proximity_min": filters.get("ath_proximity_min"),
        "ath_proximity_max": filters.get("ath_proximity_max"),
        "rsi_min": filters.get("rsi_min"),
        "rsi_max": filters.get("rsi_max"),
        "volume_ratio_min": filters.get("volume_ratio_min"),
        "sma_20_relation": filters.get("sma_20_relation", "any"),
        "sma_50_relation": filters.get("sma_50_relation", "any"),
        "sector_whitelist": filters.get("sector_whitelist", []),
        "market_cap_min": filters.get("market_cap_min"),
        "market_cap_max": filters.get("market_cap_max"),
        "eps_growth_min": filters.get("eps_growth_min"),
        "revenue_growth_min": filters.get("revenue_growth_min"),
        "sort_by": filters.get("sort_by", "ticker"),
        "sort_order": filters.get("sort_order", "asc"),
        "max_results": filters.get("max_results", 20),
        "earnings_within_days": filters.get("earnings_within_days"),
        "indicator_filters": filters.get("indicator_filters", []),
    }
    return normalized


def apply_quant_filters(df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    """Apply QuantFilters to a DataFrame of technical screening results."""
    if df.empty:
        return df

    # ATH proximity
    ath_min = filters.get("ath_proximity_min")
    if ath_min is not None and "ath_proximity" in df.columns:
        df = df[df["ath_proximity"] >= ath_min]
    ath_max = filters.get("ath_proximity_max")
    if ath_max is not None and "ath_proximity" in df.columns:
        df = df[df["ath_proximity"] <= ath_max]

    # RSI
    rsi_min = filters.get("rsi_min")
    if rsi_min is not None and "momentum_rsi" in df.columns:
        df = df[df["momentum_rsi"] >= rsi_min]
    rsi_max = filters.get("rsi_max")
    if rsi_max is not None and "momentum_rsi" in df.columns:
        df = df[df["momentum_rsi"] <= rsi_max]

    # Volume ratio
    vol_min = filters.get("volume_ratio_min")
    if vol_min is not None and "volume_ratio" in df.columns:
        df = df[df["volume_ratio"] >= vol_min]

    # SMA relations
    sma20_rel = filters.get("sma_20_relation", "any")
    if sma20_rel == "above" and "trend_sma_fast" in df.columns:
        df = df[df["close"] > df["trend_sma_fast"]]
    elif sma20_rel == "below" and "trend_sma_fast" in df.columns:
        df = df[df["close"] < df["trend_sma_fast"]]

    sma50_rel = filters.get("sma_50_relation", "any")
    if sma50_rel == "above" and "trend_sma_slow" in df.columns:
        df = df[df["close"] > df["trend_sma_slow"]]
    elif sma50_rel == "below" and "trend_sma_slow" in df.columns:
        df = df[df["close"] < df["trend_sma_slow"]]

    # Dynamic indicator_filters (new format: any indicator with min/max and optional params)
    for item in filters.get("indicator_filters", []):
        col = item.get("column")
        if not col:
            continue
        if col not in df.columns:
            raise ValueError(
                f"apply_quant_filters: missing column '{col}' in row DataFrame; "
                f"offending filter: {item!r}"
            )
        condition = item.get("condition")
        # Cross conditions (crossed_above / crossed_below) are worker-only —
        # they require a per-ticker time series and lookback, neither of
        # which `apply_quant_filters` has access to. The aggregator
        # (`technical_screener`) must strip them from the filters dict
        # before calling us. If we see one here, it's a bug in the caller
        # — fail loud so the score doesn't silently ignore the filter.
        if condition in ("crossed_above", "crossed_below"):
            raise ValueError(
                f"apply_quant_filters: '{condition}' is worker-only; "
                f"the aggregator must strip cross conditions before calling apply_quant_filters. "
                f"Offending filter: {item!r}"
            )
        ref_col = item.get("reference_column")
        if condition and ref_col and ref_col in df.columns:
            # Cross-indicator comparison (e.g. EMA above SMA)
            if condition == "above":
                df = df[df[col] > df[ref_col]]
            elif condition == "below":
                df = df[df[col] < df[ref_col]]
            elif condition == "equals":
                # Use percentage-based tolerance if provided (default 1%)
                # Formula: |A - B| <= |B| * tolerance
                tol = item.get("tolerance", 0.01)
                if tol > 0:
                    df = df[np.abs(df[col] - df[ref_col]) <= (df[ref_col].abs() * tol)]
                else:
                    df = df[df[col] == df[ref_col]]
        else:
            # Threshold-based filter (min/max)
            min_val = item.get("min")
            max_val = item.get("max")
            if min_val is not None:
                df = df[df[col] >= min_val]
            if max_val is not None:
                df = df[df[col] <= max_val]

    # Sector regime (BULL/BEAR) — filter by Markov sector-ETF regime.
    regime_target = filters.get("regime")
    if regime_target is not None and "ticker" in df.columns:
        # Imported lazily: the Markov modules pull in statsmodels/arch which are
        # heavy and irrelevant for scans that don't use the regime filter.
        from app.services.markov.regime_model import SectorRegimeManager
        from app.services.data_service import DataService

        target = str(regime_target).strip().upper()  # normalize 'bull'/'BEAR'
        if target in ("BULL", "BEAR"):
            rm = SectorRegimeManager()
            keep = []
            for ticker in df["ticker"]:
                meta = DataService.get_ticker_metadata(ticker)
                if not meta or not meta.get("sector"):
                    continue
                # as_of_date is not available here; the manager evaluates at its
                # current (most recently trained) state, matching how the rest of
                # the platform consumes regime state.
                regime = rm.get_ticker_regime(ticker, meta["sector"], date=None)
                if regime.get("regime") == target:
                    keep.append(ticker)
            df = df[df["ticker"].isin(keep)]

    # Sort (limit removed — scoring will rank and cap downstream)
    sort_by = filters.get("sort_by", "ticker")
    sort_order = filters.get("sort_order", "asc")
    ascending = sort_order != "desc"

    if sort_by in df.columns:
        df = df.sort_values(by=sort_by, ascending=ascending)
    elif sort_by == "ticker" and "ticker" in df.columns:
        df = df.sort_values(by="ticker", ascending=ascending)

    return df


# =============================================================================
# AGENT INITIALIZATION
# =============================================================================

