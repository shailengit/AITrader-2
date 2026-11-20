# 100-run validation: SectorScannerTop5Rotation & MomentumQualityRotation

Generated 2026-11-10. Harness: `backend/scripts/validate_top5_100run.py`.
Raw data: `/tmp/top5_validate/VALIDATION_REPORT.json`

## Experiment

| | |
|---|---|
| Strategies | `SectorScannerTop5Rotation`, `MomentumQualityRotation` |
| Runs per strategy | 100 (0 failed) |
| End date | 2026-11-09 — identical for all 200 runs |
| Start dates | 100 **distinct** random dates, 2010-02-23 .. 2023-11-15, seed 42 |
| Capital | $100,000 per run |
| Costs | 0 bps per side (the strategies' own baseline) |
| Fills | next session's OPEN for both entries and exits |
| Universe | 916 tickers passing the $5B cap + sector mapping |
| Signal engine | shared precompute — identical for both strategies (asserted structurally) |

Runs have different lengths (same end, different start), so lifetime totals
(`total_return_pct`, `total_trades`) are **not comparable**. Everything below is
length-normalized (CAGR, alpha/yr, Sharpe, maxDD, trades/yr).

## Results (per-run distribution)

| Metric | SectorScannerTop5Rotation | MomentumQualityRotation |
|---|---|---|
| CAGR median (p10 – p90) | **29.42%** (17.36 – 41.08) | **36.96%** (24.70 – 55.76) |
| Alpha/yr median (p10 – p90) | 14.75% (2.77 – 25.08) | 22.54% (10.53 – 39.92) |
| Sharpe median (p10 – p90) | 0.82 (0.58 – 0.99) | 0.98 (0.75 – 1.21) |
| Max drawdown median | 51.83% | 51.29% |
| Trades/yr median | 104.4 | 60.3 |
| Win rate median | 47.3% | 33.5% |
| Profit factor median | 1.21 | 1.48 |
| Worst run / best run CAGR | −0.16% / 51.45% | 19.10% / 110.56% |

Exit mix (all 100 runs pooled):

| Exit reason | SectorScanner | MQR |
|---|---|---|
| Rotated Out | 54.6% | 34.5% |
| Trailing Stop | 42.1% | 53.3% |
| Take Profit | 2.7% | 8.5% |
| Time Stop | — (disabled) | 2.6% |
| Stop Loss | 0.6% | 1.1% |
| avg hold (median) | 16.5d (14) | 29.4d (19) |

## Paired comparison (same 100 start dates; only exits/regime differ)

| Delta (MQR − Scanner) | Median | MQR better on | Range |
|---|---|---|---|
| CAGR | **+8.43 pts** | 66/100 | −15.86 .. +63.83 |
| Sharpe | **+0.165** | 75/100 | −0.24 .. +0.88 |
| Max drawdown | −2.18 pts (lower) | 43/100 | −23.16 .. +20.87 |

MQR's edge is broad but not unanimous: it wins CAGR on 2/3 of starts and Sharpe
on 3/4, and it does **not** reliably reduce drawdown (only 43/100). On the worst
start it gives up 15.9 pts of CAGR.

## Lookahead / causality tests

| Test | What it proves | Result |
|---|---|---|
| **T1** end-truncation invariance | Ending a run 2.8 years early leaves every earlier trade bit-identical — past decisions do not depend on future bars | **PASS** — 3 starts × 2 strategies, 0 symmetric differences (e.g. 1,137 closed trades and 1,142 buys identical) |
| **T2** signal prefix stability | Signals for dates ≤ 2023-12-29 are identical whether or not 2024-2026 bars are loaded | **PASS** — 1,006/1,006 dates identical |
| **T3** per-day vs precomputed parity | The live path and the vectorized backtest path agree | **PASS** — 6/6 sample dates (234–488 candidates each) identical |
| **T4** score causality | Cached holding scores equal per-day SQL scores | **PASS** — 12/12, delta 0.0 |
| **T5** fill verification | Every fill price equals the real next session's OPEN pulled independently from Postgres | **PASS** — 11,779/11,779 fills, 0 mismatches, 0 close fallbacks |

Signal computation was also read line by line: `perf_3m` uses `searchsorted` on
`date − 90d` (trailing), `vol_14` is a trailing `rolling(14).std()`, and the ETF
sector filter uses the last ETF bar ≤ the signal date. No centred windows, no
full-range aggregates.

## Trade validity audit (all 200 runs)

Checked: side/reason vocabulary, BUY carries no exit fields, positive prices,
exit ≥ entry, `holding_days` arithmetic, `return_pct` recomputation from fill
prices, dates inside the run, FIFO open/close matching (no overlapping position
in one ticker, no orphan sell), concurrent slot count ≤ 5, equity `n_holdings`
agreement, non-negative cash, and `cash + holdings = value` every day.

- **Hard integrity issues: 0** across 171,094 buys and 170,187 sells.
- Max concurrent holdings: 5 (both) — the cap holds.
- Positions still open at run end: 481 (Scanner), 424 (MQR).

### Soft findings (behavioural, not defects)

1. **Sector cap "2" is really a cap on selection.** Max concurrent same-sector
   was 4 for Scanner and 5 for MQR. Because `rotation_hold_rank` defaults to 0,
   `hold_set` equals `top_n`, so the only way to exceed the cap is `min_hold_days`
   (Scanner and MQR) or `protect_winners` (MQR) retaining names that have left the
   top-5. Up to 2 retained + 2 new same-sector names coexist.
2. **Same-day exit → re-entry.** 13.08% of Scanner exits and 11.43% of MQR exits
   are immediately re-bought on the same date at the same next-session open
   (e.g. `2016-04-29 FCX: SELL[Take Profit] 8.40→12.69, then BUY @ 12.69`).
   Mostly Trailing Stop (119 of 129 in the sampled run). At 0 bps this does not
   move the equity curve, but it re-bases the entry price and re-arms the trailing
   stop from the new entry, so the stop does not actually protect the position.
   At any realistic cost it is a direct drag — and the baseline models no cost.

### Fill-date convention

A trade's `entry_date` / `exit_date` is the **signal/decision** date; the price is
the **next** session's open. Holding periods and `holding_days` are therefore
measured decision-to-decision, one session shorter than the actual holding.

## What this run does NOT prove

These are limits of the data, not of the simulator:

1. **Point-in-time universe — the one genuine future-information path.**
   `stock_metadata` has columns `ticker, name, sector, industry, market_cap, beta`
   and **no as-of date**. The $5B market-cap filter and the sector mapping applied
   to a 2010 bar are today's values. A name that was small in 2012 but is large
   today is admitted to the 2012 universe, and one that shrank below $5B today is
   excluded from 2012. The strategy code and the adapter never read the future,
   but the *filter* effectively does.
2. **Survivorship bias.** The DB contains only tickers that exist today; delisted
   and acquired names are absent from the 916-name universe. Returns are therefore
   biased upward.
3. **Zero transaction costs.** Both strategies run at `cost_bps = 0`. Given
   ~104 (Scanner) and ~60 (MQR) trades per year and the 11–13% same-day churn,
   realistic costs will reduce both, and disproportionately the higher-turnover one.
4. **No slippage, no borrow, no liquidity cap; integer share sizing.** Share
   counts are `int(target/price)`, so a single run is path-chaotic — which is
   exactly why this experiment uses 100 starts and medians rather than one run.

## HTML run viewers

- `docs/reports/batch_SectorScannerTop5Rotation -- 100-run val_20261110_152727.html`
- `docs/reports/batch_MomentumQualityRotation -- 100-run valid_20261110_152727.html`

---

## Addendum (2026-11-12): MQR trade-level diagnostics

| Metric | MQR | Scanner |
|---|---|---|
| Beats SPY on | 100/100 starts | 92/100 starts |
| Win rate / avg win / avg loss | 33.3% / +23.3% / −7.4% | 47.4% / +12.1% / −7.9% |
| Payoff ratio / expectancy per trade | 3.16 / +2.83% | 1.54 / +1.59% |
| Top 5% of trades as share of gross wins | 80.8% | 76.2% |
| Max consecutive losing trades (median / worst) | 16 / 22 | 20 / 21 |
| Days below prior equity peak | 86.0% | 88.1% |
| Median invested fraction / slots used | 100% / 5 of 5 | 100% / 5 of 5 |
| Turnover drag at 10 bps per side | ≈ 2.4%/yr | ≈ 4.2%/yr |

Median CAGR by start year (MQR): 2010 **22.5%**, 2013 33.6%, 2016 35.5%,
2019 45.8%, 2022 **58.5%**, 2023 51.7%. The headline 37% median is flattered by
short windows ending in the recent bull; a long-horizon expectation is low-20s.

Drawdown is the weak point: median 51.3%, >50% on 58/100 runs, >60% on 18/100.
MQR does **not** reliably cut drawdown vs Scanner (better on only 43/100,
median −2.2 pts), so the "regime filter reduces drawdown" premise is not
supported by this sample.

Already ruled out elsewhere in this repo: the sell/rotation decision has no
exploitable variance (phase-3 oracle: `sell_oracle` is byte-identical to the
current rule at 10/20/40-day horizons), and phase 1–2 found no justified change
to the exit constants. All remaining upside is buy-side candidate selection —
`docs/superpowers/specs/2026-10-01-mqr-candidate-scoring-design.md`, whose oracle
ceiling is **+6.96 CAGR pts at a 20-day horizon and +10.26 at 40 days**.
