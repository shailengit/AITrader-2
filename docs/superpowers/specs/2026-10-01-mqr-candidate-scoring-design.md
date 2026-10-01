# MQR Candidate Scoring Model — Phase 3 Design

Date: 2026-10-01
Status: draft for review
Roadmap position: phase 3 (learned policy)
Predecessors: `2026-09-30-mqr-exit-replay-design.md` (phase 1–2)

## 1. Purpose

Improve MQR's **CAGR** by learning which candidate to buy when a slot frees, replacing
the raw momentum-score ranking on the buy side.

This is a narrower problem than the original phase-3 framing, and deliberately so — see
§2, which is the spike's result and the reason for the reframing.

## 2. What the spike established

A deterministic rotation-only simulation (validated as described in §3) compared four
arms over 2020-01-01 → 2026-05-19, five equal slots, at most one swap/day:

| horizon | current | sell_oracle | buy_oracle | perfect |
|---|---|---|---|---|
| 10d | 20.55% (40 swaps) | 20.55% (40) | **11.71%** (12) | 11.71% (12) |
| 20d | 20.55% (40) | 20.55% (40) | **27.51%** (11) | 28.27% (14) |
| 40d | 20.55% (40) | 20.55% (40) | **30.81%** (12) | 31.05% (15) |

Three conclusions drive this spec:

1. **The sell side has no exploitable variance.** `sell_oracle` is byte-identical to
   `current` at every horizon (same CAGR, same 40 swaps). The sell trigger (outside the
   top-5, not protected, past min-hold) typically leaves exactly ONE evictable name, so
   there is no choice for a model to make. The original "which holding gives up its slot"
   half of the idea is therefore dropped.
2. **All the value is buy-side, and it is large**: +6.96 CAGR points at 20 days and
   +10.26 at 40 days, with *lower* max drawdown (65.2% → 54%). `perfect` barely exceeds
   `buy_oracle`, confirming the ceiling is almost entirely on the buy side.
3. **The horizon is a first-class design parameter**: at 10 days the buy-side oracle is
   *negative* (−8.84 pts). A single-number horizon choice would have hidden this.

**Caveat carried forward:** the absolute levels (~20.5% CAGR) are NOT comparable to MQR's
recorded 52.8% — this simulation is rotation-only, with no trailing stop, take profit or
hard stop. Only the deltas are meaningful. Every oracle arm is hindsight, so it is a
ceiling nobody can reach.

## 3. Scope

**In scope**
- A learned **candidate scoring function**: `score(candidate, date) -> float`, used to
  choose the buy when a slot frees.
- Strategy: MQR only.
- Training data built from the validated ranking reconstruction.

**Out of scope**
- The sell/rotation-out decision (no variance — §2.1).
- Exit rules (phase 1/2 concluded no change is justified).
- Nimble or any learned model over *unstructured* state. There is no usable text state at
  decision time (verified: `hypotheses` 6 rows of placeholder text, no news/sentiment
  table). The state is numeric, so a GBM is the appropriate tool.
- Position sizing, universe definition, bear-exposure regime handling.

## 4. The foundation, and its validation

`app/services/exit_replay/ranking.py` reconstructs the daily ranking: a `dates × tickers`
score matrix where `score = sigmoid(perf_3m × 10)`, `perf_3m = close/close(90 calendar
days earlier) − 1`, with the strategy's universe filter applied (market cap ≥ $5B,
14-day return std ≤ 5%) and a sector cap of 2.

**Validated before use:** on a date when MQR recorded a new entry, that ticker appears in
the reconstructed top-5 for **2,012 of 2,013 entries (100.0%)**. The single miss is DDOG
2020-07-06. An earlier version scored 25.6% because it omitted the universe filter — the
validation caught that before any oracle ran, which is why it runs first.

**Known pre-existing look-ahead, inherited not introduced:** `stock_metadata.market_cap`
is a CURRENT value, not as-of. The strategy uses it as a filter, so the reconstruction
mirrors it for fidelity, but it is a leak in the strategy itself. It is declared here and
**must not be used as a model feature** (§6).

## 5. The decision, and the label horizon

**Decision:** when a slot frees on date D, choose the candidate with the highest model
score instead of the highest momentum score.

**Label:** the candidate's forward return over **H trading days**, `close(D+H)/close(D) − 1`.

H is the highest-leverage choice in this design, and it is chosen as follows:

- **H is selected on the FIT period only** (entries ≤ 2023-12-31), never on the held-out
  period. Choosing it on all data is exactly the selection contamination that invalidated
  phase 1's ranking.
- **"Best H" means the largest CAGR improvement over the momentum-score baseline in the
  rotation simulation, measured on the fit period only**, at 5 bps/side. It is not chosen
  by label RMSE: a lower RMSE that does not convert into portfolio CAGR is not the
  objective, and the two can disagree.
- **H ∈ {20, 40, 60}** is swept; the value that maximises fit-period improvement is taken
  forward. 10 is excluded because the spike shows it is *negative* — a 10-day foresight
  picks names about to spike and revert — and excluding it is a decision made on evidence
  from the ceiling analysis, not on the test set.
- The full H sweep is reported in-sample and out-of-sample regardless of which H is
  selected, so the sensitivity is visible rather than hidden.
- **Justification for H ≈ holding period:** MQR's average hold is ~29 days, so a label
  horizon near 40 days matches "how the candidate is expected to perform while we hold it".
  H = 60 is included to test whether a longer view helps.

**Label caveat, stated rather than hidden:** the realised return of a bought position
depends on the exit rules, not on a fixed H. A fixed-H forward return is a *proxy* for the
value of the slot. It is the right proxy for a ranking problem (monotone in the quantity we
care about) but it is not the P&L, and the evaluation in §8 measures P&L directly.

## 6. Features

All features must be **as-of D** — computed only from bars up to and including D. No
feature may use `stock_metadata.market_cap` (§4).

| group | features |
|---|---|
| momentum | `perf_3m` (raw, unsigmoided), `perf_5d`, `perf_10d`, `perf_20d`, `perf_60d`, `perf_120d` |
| volatility | 14-day and 60-day return std |
| position in range | distance from 52-week high, distance from 52-week low |
| trend | close vs SMA20 / SMA50 / SMA200 (ratios) |
| oscillators | RSI(14) |
| liquidity | volume / 50-day average volume |
| calendar | days until next earnings report (`earnings_calendar`), days since last |
| pair context | candidate's rank in the day's list, score gap to the incumbent being replaced |
| market | SPY vs SMA200 (regime flag), SPY 20-day return |
| sector | sector label (categorical; the GBM handles categories natively) |

**Why raw `perf_3m` matters:** the current rule ranks on `sigmoid(perf_3m × 10)`, which
saturates. Raw momentum is the strongest single signal to beat, and the model needs it
unsquashed to combine with anything.

**Explicitly excluded:** `market_cap` (leak, §4), `beta` (current-value, same leak class),
anything derived from the trade's actual outcome.

## 7. Model

**Primary: `sklearn.ensemble.HistGradientBoostingRegressor`** — a gradient-boosted tree
regressor, available in the installed sklearn 1.8.0 with no new dependency, fast on
~10^5 rows, handles categoricals natively, and supports permutation importance.

**Also fit: `Ridge`** as an interpretable linear baseline and a sanity floor. If the GBM
cannot beat Ridge out-of-sample, the relationship is essentially linear and the extra
complexity is not earning anything.

**Also available if the first two disappoint:** `xgboost` 3.2.0 is installed. Not used by
default because it adds no capability the above lacks for this shape of problem.

**Model-agnostic interface.** The scorer is consumed behind a single call:

    score_candidates(features: pd.DataFrame) -> np.ndarray

so the evaluation harness, the rotation simulator, and the adapter all depend on that
signature and never on the model type. This is what keeps a future swap to a different
model — including a decision model — a one-file change rather than a rewrite.

**Target normalisation:** fit on forward returns as-is. No cross-sectional demeaning, so
that the model is comparable to the momentum score it replaces (which is also absolute).
Cross-sectional ranking is applied only at selection time (pick the argmax), not in the
label.

## 8. Training data and evaluation

### 8.1 Training rows
For every trading day D in the training window, take the top-K (K = 20) candidates from the
reconstructed, universe-filtered ranking and emit one row: features at D, label = forward
H-day return.

**Distribution caveat, stated:** this samples candidate-days broadly, including days with no
free slot. That is deliberate — it yields far more rows than sampling only the baseline's
own decision days, and the deployment test in §8.3 is what validates the shift. A model
trained only on the baseline's decisions would inherit the baseline's blind spots.

### 8.2 Split, with purging
- **Train:** D ≤ 2023-12-31.
- **Test (held out):** D ≥ 2024-01-01.
- **Purge:** because a label at D uses data through D+H, training rows whose label window
  crosses the boundary are dropped (last H days of the training window). Without this,
  training leaks the test period's prices. This is a correctness requirement, not a
  refinement.

### 8.3 Evaluation — two harnesses, in this order

1. **Rotation simulation (primary).** The §2 simulator, with the buy arm replaced by the
   model's argmax. Reports CAGR, max drawdown, and swap count, on the held-out period, next
   to the momentum-score baseline on identical dates and identical slot constraints.
   **Context:** the spike's `buy_oracle` figure for the same horizon, so the captured
   fraction of the ceiling is explicit.
2. **Full adapter confirmation.** The model plugged in as the candidate ranker behind
   `StrategyBacktestAdapter`, multi-start across the six standard start dates, compared as
   paired per-start deltas. This is the deployment-realistic number and it includes entry
   drift; it is reported as such, and it is the number that decides whether to ship.

Cost assumption: the rotation simulation must charge a per-side cost, because a model that
wins by swapping more is not winning. A cost of **5 bps per side** is applied and the
sensitivity at 0 and 10 bps reported.

### 8.4 Guardrails
- Features as-of D; no forward-looking feature may be constructed (§6).
- Purge of H days around the split (§8.2).
- Permutation importances reported, and inspected for a single dominant feature that would
  indicate a leak rather than signal.
- The momentum-score baseline is re-measured on the same rows, in the same harness, in the
  same run. A model that only looks better against a stale baseline number is not better.
- **If the model does not beat the baseline out-of-sample on the held-out period, it is not
  shipped and that is the reported result.**

## 9. Deliverables

1. `features.py` — as-of feature builder over the ranking panel + `earnings_calendar`.
2. `label.py` or equivalent — forward H-day return labels with the purge applied.
3. `train.py` — fits Ridge + HistGradientBoosting, selects H on fit, writes a model artifact
   plus a metrics JSON.
4. `score.py` — the model-agnostic `score_candidates` interface, loading the artifact.
5. Rotation-simulator evaluation with cost, held-out, versus baseline and versus the ceiling.
6. Adapter multi-start confirmation.
7. An HTML report following the phase-1 report's conventions, including the H sensitivity,
   feature importances, and the ceiling-capture fraction.
8. Tests: feature as-of correctness (a feature computed at D must be unchanged by appending
   future bars), purge correctness, split correctness, and a no-leak check that no feature
   correlates suspiciously with the label beyond the expected momentum relationship.

## 10. Non-goals (YAGNI)

- No sell-side model.
- No exit-rule changes.
- No deep learning. ~10^5 tabular rows with ~25 features is GBM territory; torch is
  installed but a neural net is not justified here and would be harder to interpret.
- No live-trading integration.
- No multi-strategy generalisation yet (daily_golden_cross has entries too, but that is a
  separate question).

## 11. Risks

| Risk | Mitigation |
|---|---|
| **It may not work.** Cross-sectional return prediction is hard, and momentum is already a strong signal — most of the +7/+10 ceiling is hindsight luck, not learnable | Baseline is re-measured in-harness; the ceiling-capture fraction is reported so the shortfall is visible; a negative result is a legitimate outcome |
| H overfitted to fit period | H chosen on fit only; full sweep reported on both periods |
| Label leakage across the split | Purge of H days; feature as-of test |
| `market_cap`/`beta` leak inherited from the strategy | Declared, and excluded from features |
| Model wins by churning more | Costs charged at 5 bps/side with 0/10 sensitivity |
| Rotation sim and adapter disagree (phase 2's lesson) | Both are run; the adapter is the shipping decision, the sim is the diagnostic |
| Feature set drifts into look-ahead during implementation | The as-of test is a required test, not optional |

## 12. Success criteria

1. Feature builder passes the as-of test; purge and split are covered by tests.
2. The model beats the momentum-score **baseline** on the held-out period in the rotation
   simulation, net of 5 bps/side costs, and the comparison is against a baseline measured
   in the same run.
3. The adapter multi-start confirms the direction (median CAGR delta > 0, and not worse on
   Sharpe).
4. The captured fraction of the spike's buy-side ceiling is reported explicitly.
5. If criteria 2–3 fail, the model is not shipped and the honest result is reported — that
   is an acceptable outcome of this phase, not a failure of it.
