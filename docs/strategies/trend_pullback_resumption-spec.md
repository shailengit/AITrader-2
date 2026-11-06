# Trend-Pullback Resumption Rotation — Spec (Phase 1 output)

## The premise, corrected first

The brief was "golden crossovers are great, use the amazing CAGR". Before designing
on that, two corrections from this repo's own measurements:

- The **+766% EMA10/EMA200** number is the artifact the skill's warmup section
  retracts (corrected 441.4%), produced by a scorer with 3 days of lookahead.
- With warmup, causality and costs fixed, `DailyGoldenCrossRotation` is **good but
  not spectacular**: median over 6 starts is CAGR 20.15%, annualised alpha +2.63%,
  Sharpe 0.89, maxDD 34.9% (at 5bps/side, dc=0.005).

What *did* survive every correction and reproduced 6/6 (p=0.031) is narrower and
more useful: **the slow trend line must be an EMA200, and being above it is the
edge** — not the cross event. So this strategy is built on the validated part
(the EMA200 trend regime) and treats the cross *event* as a switch to be measured,
not an assumption.

## 1. Entry signal — five indicators, each with one job

| # | Indicator | Job | Rule |
|---|---|---|---|
| 1 | **EMA200** | primary regime | `close > EMA200` **and** `EMA200` higher than 20 sessions ago |
| 2 | **EMA50 > EMA200** | intermediate alignment | golden-cross **state** (a switch can require the fresh *event* instead — see §7) |
| 3 | **EMA20** | pullback + resumption | price was below EMA20 at some point in the last 10 sessions, **and crosses back above it today** |
| 4 | **MACD(12,26,9)** | momentum trigger | MACD line above its signal line |
| 5 | **RSI(14)** | overbought guard | `45 <= RSI <= 75` |

Universe filters: 20-day average dollar volume >= $10M; 20-day return std <= 4%.

**Critique that shaped it.** A single EMA crossover only fires on one day and is
noisy; this structure separates *regime* (EMA200), *structure* (EMA50 alignment),
*setup* (a pullback to EMA20) and *trigger* (the cross back above EMA20 + MACD).
That is the classic trend-pullback template rather than five votes on the same
thing. **Known risk:** five simultaneous conditions can starve a strategy — the
volume-filter finding in this repo is exactly that failure mode. Condition
count must be checked against realised trade count, not assumed.

## 2. Ranking / scoring

```
risk_adj_momentum = (close / close[t-126] - 1) / (126d annualised vol)
score = 0.60 * sigmoid((risk_adj_momentum - 0.5) * 4) + 0.40 * log_market_cap_scaled
```

**Critique.** Raw momentum concentrates in small-cap blowups, so the score divides
by realised volatility. Both terms use **fixed scales**, not population
normalisation, so the live path and the backtest score identically by construction.

## 3. Exit rules (adapter priority order)

| # | Exit | Rule | Rationale |
|---|---|---|---|
| 1 | Trend break | `close < EMA200` | the thesis is the primary trend; if it fails, exit |
| 2 | Hard stop | -10% | gap risk the EMA can't catch |
| 3 | Take profit | +40% | wide: trend trades pay for the failures |
| 4 | Trailing stop | 20% off peak | lets trends breathe without giving back the whole move |
| 5 | Time stop | 120 days | releases dead capital |
| — | Rotated out | falls out of top-5 after min hold | |

## 4. Position sizing

Linear score-weighted (not squared). The top names differ only marginally in score;
squaring would amplify noise rather than edge.

## 5. Risk management

- Max 5 holdings, max 2 per sector (breakouts and trends cluster by sector).
- 50% exposure when SPY < SMA200.
- Volatility and liquidity screens above; liquidity is a hard requirement because
  the score divides by volatility, which flatters thin names.

## 6. Parameters

| ema_fast 20 | ema_mid 50 | ema_slow 200 | slow_rising 20 |
|---|---|---|---|
| pullback_window 10 | macd 12/26/9 | rsi 14 (45..75) | min_dollar_volume $10M |
| max_volatility 4% | mom_window 126 | max_holdings 5 | max_sector_count 2 |
| hard_stop 10% | take_profit 40% | trailing 20% | time_stop 120 |
| min_hold 10 | protect_winners True | bear_exposure 50% | cost 5bps |

Warmup: EMA200 needs ~830 bars, so no date is scanned with fewer than 830 bars
behind it and history always loads from a 2008 floor.

## 7. Special filters / the golden-cross hypothesis

`require_fresh_cross` (default **False**): when True, an entry additionally needs
EMA50 to have crossed above EMA200 within the last `cross_window` (20) sessions.
This encodes the "golden crossovers are great" hypothesis as a measurable lever.
It is **not** assumed — it will be tested paired against the state-based version.

## Untested assumptions (stated, not hidden)

1. `rsi_floor 45` / `rsi_ceiling 75` and the fixed `risk_adj` sigmoid (centre 0.5,
   scale 4) are explicit but arbitrary.
2. Exit levels are priors, not tuned.
3. Whether five entry conditions starve the universe is unknown until measured.

Next step after generation: a paired multi-start A/B (harness shape:
`backend/scripts/dgc_signal_ab.py`), never a single run.

## Phase 4: Learn — results

**Single run first (2020-01-01 .. 2026-09-30):** +132.92% vs SPY +157.54%
(alpha -24.62% lifetime, -1.70%/yr), CAGR 13.35%, Sharpe 0.65, maxDD 32.4%,
33.2 trades/yr. That window includes the COVID crash and the whole 2022 bear.

**Paired multi-start A/B** (4 starts: 2021, 2022, 2023, 2024; fixed end
2026-09-30; same costs). Each arm changes the entry mask, so each was
precomputed separately. Medians:

| arm | CAGR | alpha/yr | Sharpe | maxDD | PF | trades/yr |
|---|---|---|---|---|---|---|
| **full (shipped)** | **24.41** | **+6.10** | **1.10** | 26.15 | **1.95** | 31.3 |
| no_macd | 14.29 | -3.34 | 0.72 | 24.45 | 1.69 | 27.3 |
| minimal (no MACD/RSI/pullback) | 13.74 | -3.34 | 0.70 | 24.45 | 1.59 | 27.3 |
| fresh_cross (require cross event) | 7.90 | -8.10 | 0.45 | 37.94 | 1.44 | 14.4 |

Per-start CAGR:

| arm | 2021 | 2022 | 2023 | 2024 |
|---|---|---|---|---|
| full | 23.96 | 18.50 | 24.87 | 25.85 |
| minimal | 11.18 | 8.91 | 16.30 | 30.04 |
| no_macd | 11.18 | 8.91 | 17.41 | 29.94 |
| fresh_cross | 8.07 | 7.73 | 6.30 | 11.06 |

**Finding 1 — the filters DO earn their place. My Phase-1 starvation fear was
wrong.** The full five-condition entry beats the three-condition core on 3 of 4
starts and by +10.7pp of median CAGR, with a higher Sharpe and PF at similar
drawdown. Fewer conditions was the weaker strategy, not the stronger one.

**Finding 2 — MACD is carrying it.** Removing MACD alone: 24.41 -> 14.29 median
CAGR. Removing RSI and pullback as well changes almost nothing further
(14.29 -> 13.74). The RSI guard and the pullback requirement are close to inert;
MACD is the filter that separates good resumptions from bad ones.

**Finding 3 — the golden-cross EVENT is refuted; the STATE is what matters.**
Requiring EMA50 to have crossed above EMA200 within 20 days collapses the
strategy: median CAGR 7.90 vs 24.41, alpha/yr -8.10 vs +6.10, Sharpe 0.45 vs
1.10, maxDD 37.9 vs 26.2 — worse in **4/4** starts. It also starves the signal
count (248 signals vs 64k for the no-MACD arm). The robust prior is being *above*
the EMA200 with EMA50 aligned, not the day the lines cross.

**Caveat:** 4 starts is below the 6+ the methodology asks for, and the 2020-start
single run was materially worse than the 2021-2024 starts — results are
window-sensitive. Treat the medians as directional until a 6+ start run confirms
them.

## Verdict — same six starts vs the golden-cross strategy

Both on 2019-01-02 .. 2024-01-02 starts, fixed end 2026-09-30, same costs:

| strategy | CAGR | alpha/yr | Sharpe | maxDD | PF | trades/yr |
|---|---|---|---|---|---|---|
| **TrendPullbackResumption** | **21.23** | **+4.27** | **0.98** | **30.29** | **1.91** | **31.3** |
| DailyGoldenCross (arm E) | 20.15 | +2.63 | 0.89 | 34.94 | 1.52 | 73.7 |

Per-start CAGR:

| strategy | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
|---|---|---|---|---|---|---|
| TrendPullback | 8.41 | 13.36 | 23.96 | 18.50 | 24.89 | 25.85 |
| GoldenCross | 20.44 | 24.35 | 16.96 | 19.85 | 23.65 | 10.98 |

**Honest reading.** The multi-indicator strategy is better on every *median*
metric — higher CAGR, nearly double the annualised alpha, higher Sharpe and
profit factor, lower drawdown — while trading **less than half as much**
(31 vs 74 trades/yr), which matters once costs are real. But the per-start
split is 3-3: golden cross wins the 2019-2020 starts, this strategy wins
2021/2023/2024. So the improvement is in **risk-adjusted efficiency and
turnover**, not a decisive return edge; the return difference is inside the
noise at six starts.

The shipped defaults (`full`, `require_fresh_cross=False`) are the best of the
arms tested. It is a genuine alternative to the golden-cross strategy, not a
replacement for it.
