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

## Experiment: EMA20/EMA200 alignment instead of EMA50/EMA200 (2026-11-07)

Same experiment repeated with `ema_mid = 20`, so the alignment/crossover condition
is `EMA20 > EMA200`. `ema_fast` stays 20, so the EMA20 serves as both the
pullback/trigger line and the alignment line. Everything else identical.
Reproduce with `backend/scripts/tpr_ema_alignment_ab.py`.

**4-arm A/B, medians over the same 4 starts:**

| arm | EMA50 CAGR | **EMA20 CAGR** | EMA50 Sharpe | **EMA20 Sharpe** |
|---|---|---|---|---|
| full | 24.41 | **15.29** | 1.10 | **0.75** |
| minimal | 13.74 | 20.23 | 0.70 | 0.91 |
| no_macd | 14.29 | 20.79 | 0.72 | 0.93 |
| fresh_cross | 7.90 | **-14.88** | 0.45 | **-0.41** |

**Finding 1 — EMA20 alignment is clearly worse.** The full arm drops from
24.41% to 15.29% median CAGR, alpha/yr from +6.10% to -1.55%, Sharpe 1.10 to
0.75, drawdown worsens 26.2% -> 32.7%.

**Finding 2 — the filter complementarity INVERTS.** With EMA50 alignment the
extra filters helped enormously (full 24.41 vs minimal 13.74). With EMA20
alignment they *hurt* (full 15.29 vs minimal 20.23). The filters are not
independently good; they only pay off on top of a slower, higher-quality
alignment condition. This is the opposite of a transferable prior — it is an
interaction, and it had to be measured.

**Finding 3 — a fresh EMA20/EMA200 cross is catastrophic.** Median CAGR
-14.88%, alpha/yr -31.70%, Sharpe -0.41, maxDD 54.2%, on only 690 signals. EMA20
crosses EMA200 far more often than EMA50 does, and many are whipsaws.

**Same six starts vs golden cross:**

| strategy | CAGR | alpha/yr | Sharpe | maxDD |
|---|---|---|---|---|
| TPR **EMA50**/EMA200 | **21.23** | **+4.27** | **0.98** | 30.29 |
| TPR **EMA20**/EMA200 | 11.22 | -4.42 | 0.59 | 32.66 |
| GoldenCross arm E | 20.15 | +2.63 | 0.89 | 34.94 |

Per-start CAGR, TPR EMA20/200 vs golden cross: 2/6 wins (2023, 2024) — versus
3/6 for EMA50/200, which also beat it on every median.

**Conclusion: keep `ema_mid = 50`.** Moving the alignment line to EMA20 costs
about 10pp of median CAGR, inverts the value of every other filter, and turns
the strategy into an underperformer against the golden cross. The shipped
default is unchanged.

## Exit-lever A/B (2026-11-07) — the diagnostics' recommendations were rejected

The exit diagnostic showed the 10% hard stop leaving +9.0% mean excess vs SPY
over the next 60 sessions, and the 40% take profit leaving +4.05%. The obvious
inference was "widen both". The portfolio A/B says no. Medians over 4 starts:

| arm | CAGR | alpha/yr | Sharpe | maxDD | PF |
|---|---|---|---|---|---|
| **base_10_40 (shipped)** | **24.41** | **+6.10** | **1.10** | 26.15 | **1.95** |
| stop15 | 18.19 | +1.37 | 0.88 | 26.16 | 1.58 |
| stop20 | 17.42 | -0.25 | 0.86 | 29.75 | 1.67 |
| no_stop | 17.42 | -0.25 | 0.86 | 29.75 | 1.67 |
| tp80 | 14.26 | +0.59 | 0.71 | 24.53 | 1.57 |
| no_tp | 9.87 | -3.52 | 0.55 | 30.78 | 1.46 |
| dead_off | 24.41 | +6.10 | 1.10 | 26.15 | 1.95 |

- **Widening or removing the stop loses ~7pp of CAGR.** A tight stop is not just
  damage control: it frees a scarce top-5 slot for the ranking to redeploy.
  Post-exit drift ignores that opportunity cost entirely.
- **Raising or removing the take profit loses 10-15pp.** The 40% target is
  load-bearing, even though it truncates the occasional big winner.
- `stop20` is byte-identical to `no_stop`: at 20% no trade ever reaches the stop
  (the trend break fires first), so 20%+ is effectively "no hard stop".
- `dead_off` is byte-identical to base, confirming the diagnostic that pullback
  and RSI bind on 0 of 3,587 core stock-days.

**Lesson (the same one recorded for MQR): a post-exit drift study cannot rank
exit policies.** It measures what the stock did after the sale, not what the
portfolio would have earned by refusing to recycle the capital. Diagnostic
analysis locates binding constraints; only a paired portfolio A/B ranks levers.

**Applied:** `use_pullback = False`, `use_rsi_filter = False` (behaviour-identical,
less work per bar). Stop and take-profit unchanged.

**Remaining upside is on the screening side, not exits:** the one-day EMA20
cross-back trigger excludes 93.7% of the top-decile movers the strategy never
sees. Broadening that trigger (an N-day entry window, or a second entry path)
is the only untested lever with room to raise CAGR, and it needs its own A/B.

## Trigger-broadening A/B + coverage diagnostic (2026-11-07) — recommendation refuted

`trigger_window` allows entry within N sessions of the EMA20 cross (price must
still be above EMA20); N=1 reproduces the original rule exactly. Medians over
4 starts:

| trigger window | CAGR | alpha/yr | Sharpe | maxDD | PF |
|---|---|---|---|---|---|
| **1 (shipped)** | **24.41** | **+6.10** | **1.10** | 26.15 | **1.95** |
| 3 | 10.67 | -4.42 | 0.58 | 32.66 | 1.28 |
| 5 | -0.82 | -15.11 | 0.09 | 39.78 | 0.95 |
| 10 | 14.99 | -3.42 | 0.76 | 24.99 | 1.60 |

Window 1 wins **every one of the four starts**. Broadening the trigger is a
large regression.

The coverage diagnostic explains why, and reframes the "bottleneck":

| | share of top-decile movers |
|---|---|
| excluded by the **regime** (not trigger) | **61.6%** |
| regime-eligible | 38.4% |
| ...reachable at window 1 | 8.1% |
| ...reachable at window 3 / 5 / 10 | 17.3% / 24.3% / 34.3% |

Forward 60d return among regime-eligible stock-days **falls as the window
broadens** — reachable at w1: 2.94% mean / 2.09% median; w3: 2.74/1.95;
w5: 2.63/1.88; w10: 2.38/1.56. The unreachable days average *higher* (2.67%) than
the broadened-window sets, so widening admits worse entries.

**Conclusion: the funnel is correctly narrow.** The "93.7% of movers missed" was
a mirage. Most of those movers are either (a) outside the uptrend regime — i.e.
bounce trades, a different strategy with a different edge — or (b) not at a
fresh, high-quality entry. The one-day cross is not an arbitrary restriction; it
is the best day. Both the regime and the trigger are now validated twice, and
**neither should be relaxed.**

**Where to look next** (none of these widen the entry funnel):
1. **Capacity** — test `max_holdings` 5 vs 8 vs 10. More slots lets the
   portfolio act on more of the candidates it already sees, with no quality loss.
2. **Ranking** — the score is risk-adjusted 126d momentum + log market cap. Test
   adding a trend-strength term (ADX) or changing sizing (linear vs squared).
3. **Orthogonal fresh events** — a *second* entry setup that also fires fresh
   (e.g. MACD histogram crosses up while above EMA20 and regime holds), rather
   than widening the existing one.
4. **Change the KPI.** Universe capture is not a target: a 5-slot portfolio
   cannot and should not hold 9,892 movers. Judge changes by portfolio
   CAGR/Sharpe/drawdown and turnover.
