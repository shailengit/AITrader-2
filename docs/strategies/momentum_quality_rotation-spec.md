# Momentum Quality Rotation (MQR) — Strategy Spec

## Goal
High CAGR (target 40%+) with materially lower drawdown than the current
momentum strategies. The current `sector_top5_pegy` averages ~40% CAGR but
with ~29% max drawdown and huge variance. The two levers this strategy adds:

1. **Market regime filter** (SPY < SMA200 → cut exposure to 50%). The current
   momentum strategies run `bear_exposure=1.0` (always fully invested), so
   they ride every bear market down. Cutting exposure in downtrends is the
   single biggest drawdown reducer.
2. **Quality factor** (as-of earnings growth) blended with momentum, so we
   don't just buy the hottest momentum names (which are often the most
   overextended).

## Universe filter (a stock qualifies only if it passes ALL)
- Market cap >= $5B
- 14-day daily-return std <= 5%
- Scanner sector filter: stock's 3-month perf beats its sector ETF
  (min_perf = 0 if sector_3m > 0.20, else sector_3m * 0.5)
- Quality gate: as-of trailing EPS growth > 0 (computable from the two most
  recent annual reports with report_date <= trade date). No valid growth -> not
  buyable.

## Ranking (composite score, descending)
- momentum_score = sigmoid(perf_3m * 10)   (3-month momentum)
- quality_score  = sigmoid(eps_growth * 2) (as-of earnings growth, bounded)
- composite = 0.70 * momentum_score + 0.30 * quality_score

## Position sizing
- Momentum/quality-proportional ("linear" on composite score). Higher composite
  names get larger positions.

## Exits (in priority order)
1. Hard stop loss: 20% (overrides min hold)
2. Trailing stop: 12% from peak
3. Take profit: +50%
4. Time stop: 120 days
5. Rotation: sold when a holding leaves the top-5 (after 14-day min hold),
   with protect_winners = True (keep a profitable holding that leaves the top-N)

## Market regime
- SPY < SMA(200) -> bear_exposure = 0.50 (positions sized at half weight)
- SPY >= SMA(200) -> bear_exposure = 1.0

## Parameters
- Max holdings: 5
- Max per sector: 2
- Min hold days: 14
- Market cap min: $5B
- Max volatility: 5% (14d)
- Momentum weight: 0.70
- Quality weight: 0.30
- Hard stop: 20%
- Trailing stop: 12%
- Take profit: 50%
- Time stop: 120 days
- Bear exposure: 0.50

## Look-ahead safety
- All indicators computed as-of (only data with date <= trade date).
- EPS growth uses only annual reports with report_date <= trade date.
- Price used is that day's close.

## Files
- In-app: `backend/app/services/strategies/momentum_quality_rotation.py`
- Standalone: `strategies/momentum_quality_rotation.py`
- Report: `docs/reports/momentum_quality_rotation.html`
