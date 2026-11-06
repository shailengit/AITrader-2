# 52-Week High Breakout Rotation — Spec (Phase 1 output)

Demo run of the `strategy-crafter` skill. Decisions below were made by the
assistant acting as coach; each topic records the choice **and** the critique
that shaped it.

Universe: S&P 1500 single names (same DB tables as the other strategies).
Capital: $100,000. Benchmark: SPY.

## 1. Entry signal

**Chosen:** a *fresh* 252-day closing high, not every day spent at one.

```
close[i]   >= rolling_max(close, 252)[i]
close[i-1] <  rolling_max(close, 252)[i-1]
```

**Critique that shaped it.** Taking "close is at a 52-week high" alone fires on
every day of a strong uptrend; the position is only opened once, but the signal
date becomes arbitrary and the same stock re-fires the day after any exit. Requiring
the *transition* makes each signal a discrete event, which is what the strategy is
actually claiming an edge on.

**Not chosen:** a 52-week high *intraday* (whipsaws), and a "within X% of the high"
threshold (that is a different, weaker strategy — proximity rather than breakout).

## 2. Ranking / scoring

**Chosen:** `score = 0.70 x RS + 0.30 x log(market cap)`, both on **fixed scales**:

```
RS       = close / close[t-63] - 1            (12-week return)
RS_norm  = sigmoid((RS - 0.10) * 10)          # centred on +10%, fixed
cap_norm = clip((log10(mc) - 9) / 3, 0, 1)    # $1B..$1T, fixed
```

**Critique that shaped it.** The obvious implementation normalises RS and market
cap against the candidate set or the universe. That makes the score depend on
*who else* happened to signal that day — the live path and the backtest then rank
the same stock differently, which is a real bug already found in this repo. Fixed
scales remove the population entirely: the score is a pure function of the stock.

**Known weakness:** a sigmoid centred on +10% is an assumption. It is a knob
(`rs_center`, `rs_scale`), not a measured optimum.

## 3. Exit rules (adapter priority order)

| # | Exit | Rule |
|---|---|---|
| 1 | Momentum breakdown | close < EMA50 (strategy_exit) |
| 2 | Hard stop | −12% from entry |
| 3 | Take profit | +35% |
| 4 | Trailing stop | 20% off peak |
| 5 | Time stop | 90 days |
| — | Rotated out | falls out of top-5 after min hold |

**Critique.** A breakout that closes below its 50-day EMA has failed on its own
terms; holding it to a −12% stop gives back too much. The hard stop exists for
gap risk that the EMA can't catch. Take profit at 35% is deliberately wide —
breakouts that work tend to run, and a tight target caps the payoff that pays
for the failures.

## 4. Position sizing

**Chosen:** linear score-weighted (not squared).

**Critique.** Score-squared concentrates in the top pick; for a breakout strategy
where the top-ranked names differ only marginally in score, that would amplify
noise rather than edge. Linear is the safer default here.

## 5. Risk management

- Max 5 holdings, **max 2 per sector** — breakouts cluster by sector (a whole
  sector breaking out together is one bet, not five).
- Volatility filter: skip 14-day return std > 6%.
- Bear regime: 50% exposure when SPY < SMA200 (adapter `bear_exposure`).

## 6. Parameters

| Parameter | Value |
|---|---|
| high_window | 252 |
| rs_window | 63 |
| fast_span (EMA50) | 50 |
| volume_ma_span | 50 |
| volume_mult | 1.2 |
| max_volatility | 0.06 |
| max_holdings | 5 |
| max_sector_count | 2 |
| hard_stop_loss | 0.12 |
| take_profit | 0.35 |
| trailing_stop | 0.20 |
| time_stop_days | 90 |
| min_hold_days | 7 |
| cost_bps | 5.0 |

## 7. Special filters

- **Volume confirmation:** `volume > 1.2 x 50-day average`.
- **Warmup:** the 252-day high is *exact*, not converging — it needs 252 bars.
  No date is scanned with fewer than 300 bars behind it. History always loads
  from a 2008 floor so the first simulated day is warm.

## Untested assumptions (stated, not hidden)

1. `volume_mult = 1.2` is the textbook breakout rule, **not measured here**. The
   repo's own evidence says volume filters often starve a strategy; this must be
   A/B'd, not assumed.
2. `rs_center = 0.10` / `rs_scale = 10` are arbitrary but explicit.
3. Exit levels (12/35/20/90) are reasonable priors, not tuned.

Next step after generation is a paired multi-start A/B (see
`backend/scripts/dgc_signal_ab.py` for the harness shape), not a single run.

## Phase 4: Learn (what the first run exposed)

The first full run (2023-01-01 .. 2026-09-30) returned **-19.15%** while SPY made
+109.44%. The exit mix was the tell: **328 of 400 exits were "Rotated Out"** —
82% of all exits were rotation, ~107 trades/year.

**Diagnosis.** The entry rule (a *fresh* 252-day high) and the rotation score
(12-week relative strength) both reward recent strength. A newly-signalling stock
almost always outranks an existing holding, so the book churns every few days and
the 10bps round-trip plus spread eats whatever edge the signal had.

**Fix, tested as a paired 3-start comparison** with shared precomputed signals
(`protect_winners` is an adapter-side rotation param, so entry signals are held fixed):

| protect_winners | median CAGR | median Sharpe | median maxDD | median trades |
|---|---|---|---|---|
| False | 1.32% | 0.22 | 46.3% | 292 |
| **True** | **8.79%** | **0.44** | **36.8%** | **169** |

Consistent across all three starts; turnover roughly halves. Applied as the
default. This is the same lesson the golden-cross strategy already recorded: a
rotation criterion that always prefers fresh signals churns away winners.

Also fixed: `pct_change()` -> `pct_change(fill_method=None)` (the `'pad'` default
is deprecated and would change meaning on a pandas upgrade).

Final single run after the fix: **+37.06%**, CAGR 8.78%, Sharpe 0.44, maxDD 30.3%,
197 trades, PF 1.26, alpha **-72.38%** vs SPY.

## Honest verdict

The implementation now does what the spec says, but **the idea is still weak**: it
badly underperforms buy-and-hold SPY over 2023-2026. Two unmeasured levers remain
before judging the idea itself:

1. the volume filter (`volume_mult=1.2`) is a textbook assumption, and this repo's
   evidence says volume filters often starve a strategy — test it OFF;
2. `rs_center=0.10` / `rs_scale=10` shape the ranking and were never tuned.

Both need a paired multi-start A/B, not a single run — which is exactly what
`backend/scripts/dgc_signal_ab.py` exists for.
