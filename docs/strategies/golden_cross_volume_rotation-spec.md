# Golden Cross Volume Rotation (GCVR) — Strategy Spec

## Goal
A daily-scan rotation strategy that buys stocks primed to rise (golden cross
with volume confirmation) and intelligently rotates holdings to maximize profit
while controlling turnover and drawdown.

## Universe filter (a stock qualifies only if it passes ALL)
- Price above 200-day SMA (trend filter — only buy in uptrends)
- EMA10 crosses above EMA200 on the signal day (golden cross)
- Volume > 1.0x 50-day average on the cross day (volume confirmation)
- 14-day daily-return std <= 5% (volatility filter)

## Ranking (composite score, descending)
- angle_score = sigmoid(crossover_angle * 100)   (steepness of EMA10/200 cross)
- cap_score   = normalized market cap across universe
- composite   = 0.60 * angle_score + 0.40 * cap_score

## Rotation (buy/hold spread — the key design decision)
- **Buy:** the top 5 by composite score (after sector cap)
- **Hold:** a position is kept while it ranks within the top 10 (a wider band
  than the buy cap), so winners that merely dip in rank are NOT churned out.
- **Sell:** only when a holding drops out of the top 10, OR an exit rule fires.
- Scan daily, but rebalance only when triggered — most days produce no trades.
- This cuts turnover (the single biggest cost drag in momentum rotation) while
  still capturing rotation into new leaders.

## Position sizing
- Score-weighted ("linear" on composite score). Higher composite score names
  get larger positions.

## Exits (in priority order)
1. Death cross (EMA10 < EMA200) — via should_exit
2. Hard stop loss: 10% (overrides min hold)
3. Take profit: +25%
4. Trailing stop: 20% from peak
5. Time stop: 90 days
6. Rotation: sold when a holding drops out of the top 10 (after 10-day min hold)

## Market regime
- SPY < SMA(200) -> bear_exposure = 0.0 (go to cash)
- SPY >= SMA(200) -> bear_exposure = 1.0

## Parameters
- Max holdings: 5
- Hold rank (buy/hold spread): 10
- Max per sector: 2
- Min hold days: 10
- Max volatility: 5% (14d)
- Volume multiplier: 1.0x 50-day average
- EMA fast/slow: 10 / 200
- Trend SMA: 200
- Angle weight: 0.60
- Cap weight: 0.40
- Hard stop: 10%
- Trailing stop: 20%
- Take profit: 25%
- Time stop: 90 days
- Bear exposure: 0.0

## Look-ahead safety
- All indicators computed as-of (only data with date <= trade date).
- Price used is that day's close; fills happen at the NEXT trading day's open
  (handled by the backtest adapter).

## Files
- In-app: `backend/app/services/strategies/golden_cross_volume_rotation.py`
- Standalone: `strategies/golden_cross_volume_rotation.py`
- Report: `docs/reports/golden_cross_volume_rotation.html`
