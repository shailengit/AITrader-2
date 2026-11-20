# MQR_V1 — Momentum Quality Rotation with a delayed trailing stop

Status: implemented 2026-11-13. Class:
`backend/app/services/strategies/momentum_quality_rotation_v1.py`
(`MomentumQualityRotationV1`). Standalone wrapper:
`strategies/momentum_quality_rotation_v1.py`. Validator:
`backend/scripts/mqr_v1_validate.py`.

## Purpose

Take the one exit change that survived a 100-run, paired, cost-aware experiment
and make it deployable — without carrying the AI gate, which did not survive.

## The change (one lever)

**The 12% trailing stop is not armed until a position is 7 calendar days old.**

Everything else is inherited unchanged from `MomentumQualityRotation`: the
universe filter, the momentum score, sector cap, the 20% hard stop, +50% take
profit, 120-day time stop, 14-day rotation minimum, `protect_winners`, and 50%
bear-market exposure.

Mechanism: rotation already waits 14 days, but the trailing stop bypassed that
protection and sold on ordinary early noise — often re-buying the same name the
same day (11.4% of exits were same-day re-entries).

## Evidence

From `docs/reports/mqr_exit_gate_stage0_5_20261112.md`, 100 distinct start dates,
common end, paired, length-normalized:

| N (calendar days) | ΔCAGR @10bps | wins | ΔSharpe | ΔmaxDD |
|---|---|---|---|---|
| 5 | −0.08 | 50/100 | −0.02 | +0.35 |
| **7** | **+7.56** | **73/100** | **+0.07** | **+3.33 worse** |
| 10 | +5.33 | 66/100 | +0.04 | +1.17 worse |
| 14 | −4.58 | 31/100 | −0.09 | −2.12 better |

Controls that failed: vetoing every trail stop (−1.26, DD 5.1 pts worse); any
profit-conditioned trail veto (−4 to −10.5); time-stop veto (+5.33 at 0 bps but
+1.75, 55/100, p=0.18 at 10 bps); an LLM exit gate (+2.08 on 12/20 starts,
Sharpe worse, 93 minutes per 20 starts).

## Threshold caveat — read before changing the number

The dose-response is **not monotone**: nothing at 5 days, the peak at 7, good at
10, a large loss at 14. **7 was the best-scoring value in the same 100 starts
used to measure it**, so the size of the effect (+7.56) is optimistically biased
by selection. 10 days is the pre-registered alternative and the safer default.

Both thresholds are significant against a 50/50 paired sign test even after
correcting for the four thresholds tested (7 days: 73/100, p≈2e-6; 10 days:
66/100, p≈9e-4). The uncertainty is in the **magnitude**, not the direction —
which is exactly why the non-monotone collapse at 14 days matters. Change it
with:

```python
MomentumQualityRotationV1(trailing_stop_min_hold_days=10)
```

Max drawdown does **not** improve at either setting. This is a return lever, not
a risk lever.

## Parameters

| Parameter | Value | Notes |
|---|---|---|
| `trailing_stop` | 0.12 | unchanged |
| `trailing_stop_min_hold_days` | **7** | the only change |
| `trailing_stop_activation` | 0.0 | unchanged (peak-gain arming, separate) |
| `hard_stop_loss` | 0.20 | unchanged; still active during the protected window |
| `take_profit` | 0.50 | unchanged |
| `time_stop_days` | 120 | unchanged |
| `min_hold_days` | 14 | rotation minimum, unchanged |
| `max_sector_count` | 2 | unchanged |
| `protect_winners` | True | unchanged |
| `bear_exposure` | 0.50 | unchanged |
| `re_score_holdings` | True | unchanged |
| `cost_bps` | caller-supplied | the wrapper defaults to 10 bps per side |

## Consistency across the three paths

The rule is implemented once in config and honoured by all three:

| Path | Where |
|---|---|
| Backtest | `StrategyBacktestAdapter` → `trailing_stop_armed(hold_days, min)` |
| Frozen-entry research | `exit_replay.engine.ExitPolicy.trailing_stop_min_hold_days` |
| Live/paper | `alpaca_runner` — entry bracket carries a **fixed 20% hard stop** (no trail); the runner attaches the trailing stop once the position is old enough, cancelling the fixed stop first. A young position with no stop at all gets a fixed hard stop, never a trail. |

`hold_days` is **calendar days** in all three paths. The live runner has a
dedicated `_get_hold_calendar_days`; an unknown entry date counts as 0 (young),
which errs toward keeping the hard stop.

## Deploying to an Alpaca paper account

Paper is the default: `AlpacaClient` uses
`https://paper-api.alpaca.markets` unless `ALPACA_<prefix>_PAPER=false`.
This repo's `.env` defines credential sets `ALPACA_1_*`, `ALPACA_2_*`,
`ALPACA_3_*`; none sets `PAPER=false`.

**Single run on account 3 (paper):**

```bash
cd backend
source venv/bin/activate
python -m app.services.alpaca_runner_by_name momentum_quality_rotation_v1 3
```

This imports the module, finds `MomentumQualityRotationV1`, and runs one daily
cycle against `ALPACA_3_*`. It **places real paper orders**.

**Daily schedule (live since 2026-11-13):** launchd, not cron.

| Piece | Path |
|---|---|
| Runner script | `scripts/run_mqr_v1.sh` (account 3 only) |
| Agent | `~/Library/LaunchAgents/com.tradecraft.alpaca-strategy-mqrv1.plist` |
| Schedule | Mon–Fri 20:00 (after the 18:00 DB update) |
| Logs | `backend/logs/alpaca_mqrv1_YYYYMMDD.log`, `alpaca_mqrv1_heartbeat.log` |
| Alerts | `backend/logs/ALERTS.log` + a macOS notification on failure |

Deliberately **separate** from the shared `com.tradecraft.alpaca-strategy` agent,
which remains disabled. That agent runs `scripts/run_all_strategies.sh` for all
three accounts; re-enabling it would resume accounts 1 and 2
(`DailyGoldenCrossRotation`), dormant since 2026-09-28. The shared launcher does
also contain a `run_one momentum_quality_rotation_v1 "3"` line, so enabling the
shared agent later would run V1 as well — that is intentional so the two paths
agree, not a second schedule.

`RUNNING_STRATEGIES` in `backend/app/services/strategy_accounts.py` lists
`MomentumQualityRotationV1` on prefix 3, so the app shows it as the deployed
strategy for that account.

## Verification

`backend/scripts/mqr_v1_validate.py --runs 100` (end 2026-11-11, 10 bps/side,
100 distinct starts, paired):

| | MQR | MQR_V1 |
|---|---|---|
| Median CAGR | 32.16% | **36.85%** |
| Alpha / yr | 17.84 pp | **22.74 pp** |
| Sharpe | 0.905 | **0.930** |
| Max drawdown | **51.80%** | 56.70% |
| Trades / yr | 60.1 | 57.7 |
| Win rate / PF | 31.8% / 1.42 | 34.6% / 1.65 |

Paired deltas: CAGR **+7.56 pts** (73/100 wins, sign-test p = 2e-6; range
−31.42 to +41.93), Sharpe **+0.07** (59/100), max drawdown **+3.33 pts worse**
(better on only 36/100). This reproduces the Stage 0.5 gate experiment exactly.

- **No lookahead:** end-truncation invariance passed on 3/3 starts (639, 417 and
  493 closed trades each identical when the run is cut at 2023-12-29).
- **Trade audit:** 0 hard issues across 100 runs.
- **Standalone wrapper:** runs and prints the config banner; on the single
  2020-01-01 → 2026-11-11 path it reports CAGR 77.79% / Sharpe 1.51 / DD 43.3%
  vs MQR's 60.56% / 1.29 / 45.3% on the same window. Single paths are
  path-chaotic — the 100-run medians above are the number to trust.

Results JSON: `/tmp/mqr_exit_gate/mqr_v1_validation.json`.

## Known limitations (unchanged from MQR)

- Universe filtered on **current** `stock_metadata` market caps and sectors, so
  the filter reads present-day information at historical dates; delisted names
  are absent (survivorship). Both bias results upward.
- Costs are a flat `cost_bps` per side; no slippage or borrow.
- Integer share sizing makes a single run path-chaotic — judge it only on
  multi-start medians.
- Drawdown is ~51% median. This version does not address it.
