# Momentum Quality Rotation (MQR) — Strategy Spec

## Goal
High CAGR (target 40%+) with materially lower drawdown than the current
momentum strategies. The current `sector_top5_pegy` averages ~40% CAGR but
with ~29% max drawdown and huge variance. The two levers this strategy adds:

1. **Market regime filter** (SPY < SMA200 → cut exposure to 50%). The current
   momentum strategies run `bear_exposure=1.0` (always fully invested), so
   they ride every bear market down. Cutting exposure in downtrends is the
   single biggest drawdown reducer.

> **Note — the "quality" factor was removed.** An as-of EPS-growth factor was
> implemented and measured: it shrank the universe and *reduced* CAGR (4.5% vs
> 46%). It is **not** in the strategy. The name is a legacy of that experiment;
> ranking is pure momentum. See `scripts/mqr_*` sweeps and the turnover audit at
> `docs/reports/mqr_turnover_audit_20260929.html`.

## Universe filter (a stock qualifies only if it passes ALL)
- Market cap >= $5B
- 14-day daily-return std <= 5%
- Scanner sector filter: stock's 3-month perf beats its sector ETF
  (min_perf = 0 if sector_3m > 0.20, else sector_3m * 0.5)

## Ranking (descending)
- score = sigmoid(perf_3m * 10)   (3-month momentum, MOMENTUM_K = 10.0)
- Sector-capped at 2 per sector, then the top 5 are bought.

## Position sizing
- Momentum-proportional ("linear" on the sigmoid-normalized score). Higher
  momentum names get larger positions.

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
- MOMENTUM_K: 10.0 (sigmoid steepness for score/sizing)
- Hard stop: 20% (rarely binds — a 12% trail fires first; 0.5% of exits at baseline)
- Trailing stop: 12%
- Trailing stop activation: 0.0 (trail armed from entry; swept, see report)
- Take profit: 50%
- Time stop: 120 days (rarely binds — 2.1% of exits)
- Bear exposure: 0.50
- Cost per side (bps): 0.0 (costless fills — the adapter has no cost model by default)

## Look-ahead safety
- All indicators computed as-of (only data with date <= trade date).
- Price used is that day's close.
- Fills use the NEXT trading day's open (not the signal day's close).

## Known findings (2026-09-29/30)
- **Single-run backtests are path-chaotic — do not compare levers from them.**
  `shares = int(target_value/price)` truncates, so a negligible input change
  reshuffles the whole trade sequence. Varying only `cost_bps` moved CAGR by
  +4.4 pts at a 0.06%/yr drag and +32.5 pts at 0.30%/yr, reproducing
  bit-identically. Use multi-start sampling or the 100-run batch, on medians.
- Turnover is **load-bearing**, not leakage: ~61 exits/yr, ~30-day average hold.
  Suppressing one exit reason (via `min_hold_days` or trailing-stop activation)
  only re-routes the churn into another. Full analysis:
  `docs/reports/mqr_turnover_audit_20260929.html`.
- **bear_exposure 0.50 is confirmed optimal — keep it.** Tested against five
  alternatives with paired multi-start sampling (6 start dates). None wins:
  - 0.75 / 1.00 (higher): return difference is chaos (4/6 and 3/6 wins, ~38-pt
    spread), drawdown consistently worse, Sharpe flat.
  - 0.00 / 0.25 / 0.35 (lower): all lose on return (median CAGR −2.72 / −3.19 /
    −4.87 pts; wins 2/6, 1/6, 2/6) and Sharpe (−0.04 / −0.03 / −0.05).
  - **Drawdown is NOT ordered by exposure**: median max drawdown is 48.6% at
    0.00, 45.8% at 0.25, 42.1% at 0.35, 43.2% at 0.50. Full cash is the WORST.
  - **Why:** `bear_exposure` multiplies the size of NEW entries only; it never
    force-exits existing holdings. At 0.00 the strategy stops buying in downtrends
    while its holdings still ride the decline, so it forgoes the recovery without
    avoiding the drawdown. **It is a poor drawdown control** — do not reach for it
    when the goal is reducing drawdown.
- Max drawdown (~45% over 2020-2026) is the strategy's real weakness.
- The adapter charges **no transaction costs** unless `cost_bps` is set; at
  ~24x annual portfolio turnover this overstates returns by ~1.2%/yr at 5bps.
  Measure cost drag analytically (turnover x bps) — re-simulating changes the
  trajectory and is meaningless here.

## Files
- In-app: `backend/app/services/strategies/momentum_quality_rotation.py`
- Standalone: `strategies/momentum_quality_rotation.py`
- Report: `docs/reports/momentum_quality_rotation.html`
