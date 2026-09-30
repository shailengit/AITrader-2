# MQR Exit Replay — Phase 1 Design (Evidence First)

Date: 2026-09-30
Status: draft for review
Roadmap position: phase 1 of 3

## 1. Purpose

**Entries in this stack are systematic; exits are arbitrary.** The screener ranks the
universe daily and picks the top 5 by a defined rule. The exits, by contrast, are
hand-chosen constants — a 12% trailing stop, a +50% take profit, a 120-day time stop, a
20% hard stop. Nobody derived those numbers; they were guessed and then tuned by
single-run backtests.

This design builds the evidence needed to replace them with measured rules.

Phase 1 produces **evidence, not a changed strategy**. Phase 2 turns the evidence into a
new deterministic exit rule. Phase 3 explores a learned policy.

## 2. Roadmap context

| Phase | Output | Status |
|---|---|---|
| 1. Evidence first | Deterministic exit replay over MQR's fixed entries; MFE/MAE + regret + alternative-policy ranking | **this spec** |
| 2. Better deterministic exit rule | A changed exit rule, validated via multi-start / batch (never a single run) | later |
| 3. Learned policy | Local trainable decision model (**Nimble**), walk-forward validated | later |

**Phase 3 model choice, resolved:** Jev (TypeSafe) is a hosted model with undisclosed
training — it cannot be trained on our data, only called. **Nimble** (Bespoke Labs,
Qwen3.5-9B + LoRA, Apache 2.0, served via Ollama 0.35+) ships a public training recipe and
datasets, so it *is* trainable on our data. It is the phase-3 candidate. Its contrastive
data-curation method — training pairs constructed so a single fact flips the answer —
maps directly onto hold-vs-exit decisions.

## 3. Why this is trustworthy where today's earlier work was not

Every lever comparison attempted earlier on 2026-09-29/30 was invalidated by **path
chaos**: `shares = int(target_value / price)` truncates, so a negligible input change
reshuffles the whole trade sequence, and a 0.30%/yr cost moved CAGR by +32 points
(bit-identically reproduced).

This design avoids that failure by construction:

> **The entry set is frozen and only exits are replayed.**

With entries fixed and forward prices taken from the real panel, there is no
size-truncation feedback loop and therefore no chaos. The screener's entry edge is held
constant; only the arbitrary part varies. This is the single most important property of
the design.

Secondary advantage: the **label is real market data**. The simulator determines *which*
(ticker, entry_date) pairs we observe, but the forward path — and therefore the outcome
of any exit rule — comes from actual OHLCV, not from the simulator's decisions.

## 4. Scope

**In scope**
- Strategy: **momentum_quality_rotation only** (pilot). `strategy_id = 8e78e543-18e2-4b7d-abff-04e754e33015`.
- Price-based exit rules only: hard stop, trailing stop, take profit, time stop.
- Forward horizon capped at **180 trading days** past entry.

**Out of scope (explicit)**
- **Rotation is fixed, not replayable.** `Rotated Out` is 33.3% of MQR exits and fires on
  a cross-sectional ranking change, not a price move. Replaying a different rotation rule
  would require re-running the screener as-of every date, reintroducing chaos and
  enlarging the project. Rotation is treated as an external event that caps each replay at
  that trade's actual rotation date. Rotation *quality* is measured by evidence
  (what did the price do after we rotated?) but not replayed.
- Other strategies (GCVR, daily_golden_cross, sector_scanner_top5_rotation_v3).
- Any change to entries, sizing, or the screening logic.
- Any model training (phase 3).

## 5. Verified data facts

`journal_trade` is PostgreSQL, one row per **closed round trip** (both `entry_px`/`entry_at`
and `exit_px`/`exit_at` populated).

| Fact | Value |
|---|---|
| Raw MQR rows (`source='backtest'`) | 29,736 |
| **Distinct positions (the actual analysis set)** | **2,013** |
| Duplicate rows dropped | 27,723 (max multiplicity 110, mean 14.8) |
| Side | `long` for all rows |
| Bad or zero prices | 0 |
| Null `exit_at` | 0 |
| Entry date range | 2020-01-03 → 2026-05-19 |
| Hold period range | **1 → 122 days** |
| Fully-observed forward window (≥180 trading days) | 26,391 (88.8%) |
| Censored at data end (2026-01-09 boundary) | 3,345 (11.2%), essentially all of 2026 |

> **CORRECTED 2026-09-30 — this originally claimed there was no `exit_reason`.**
> That was wrong. Every backtest row carries `notes = 'backtest:<Reason>'`:
> `Trailing Stop` 50.5%, `Rotated Out` 34.6%, `Take Profit` 12.3%, `Time Stop` 2.1%,
> `Stop Loss` 0.5% — matching the batch report exactly. The reason is read directly;
> §7's structural signature is retained only as a cross-check, not as the source of
> labels. (The original text inferred a limitation from the column *names* without
> inspecting `notes`' values.)

Columns present but **0% populated** across the whole corpus, and unusable as they stand:
`mae`, `mfe`, `stop_px`, `target_px`, `regime_at_entry`, `regime_at_exit`, `signal_id`.
Filling `mae`/`mfe` is a phase-1 byproduct.

Exit mix is **not** derivable from `journal_trade`; it comes from the 100-run batch report:
Trailing Stop 50.5%, Rotated Out 34.6%, Take Profit 12.3%, Time Stop 2.1%, Stop Loss 0.5%.
The four price-based rules cover **65.4%** of exits.

Two independent consistency signals worth noting: max hold is **122 days** against a
120-day time stop (so the time stop is confirmed to be barely binding), and 20.5% of trades
were held under 14 days, which rotation by construction cannot have exited.

Exact split counts on the analysis set (`source='backtest'`):

| Bucket | Distinct positions |
|---|---|
| Fit — 2020-2023 | 1,360 |
| Validate — 2024-2025 | 545 |
| 2026 (gate only) | 108 |

> **CORRECTED — the raw rows were 97% duplicates.** All 29,736 rows were written in
> a two-minute window on 2026-09-05, and `(ticker, entry_date)` collapses to 2,013
> positions. Crucially the multiplicity *rises by entry year* (2.5× in 2020 → 31.5×
> in 2026), so counting rows would have made the fit/validate comparison
> multiplicity-weighted and non-comparable. The earlier claim that the two halves
> were "nearly equal" (13,088 vs 13,245 rows) was an artifact of that replication:
> by distinct position the split is 1,360 / 545. All analysis runs on the deduplicated
> set, and duplicate count is reported on every run.

## 6. Architecture

Four units, each independently testable. Units communicate through a frozen artifact and
plain data structures — no unit reaches into another's internals.

### 6.1 Entry-set extractor
Reads MQR's `journal_trade` rows and writes a **frozen, versioned entry-set artifact**
(parquet). One row per trade: `ticker, entry_date, entry_px, qty, actual_exit_date,
actual_exit_px, actual_reason, hold_days`.

*Why frozen:* every policy comparison must run on byte-identical entries. Regenerating
entries mid-analysis would silently invalidate cross-policy comparisons.

### 6.2 Price-window loader
Given the entry set, loads forward OHLCV per ticker — **one query per ticker, cached**,
not per trade. Returns, per trade, the bar series from the day after entry to
`min(entry + 180 trading days, data end)`.

### 6.3 Replay engine (pure)
`replay(entry, bars, policy) -> ReplayOutcome`

Returns `exit_date, exit_px, exit_reason, mae, mfe, hold_days, observed_fully`.

Rule functions are **pure** — they take bars plus a position snapshot and return an exit
signal or `None`, mirroring the pattern already in `app/services/backtest/exit_engine.py`.
Semantics must mirror `strategy_backtest_adapter.py` exactly (that is what makes §7
possible): rule precedence `hard_stop → trailing_stop → take_profit → time_stop`, fills at
the **next open**, trailing measured from peak with the activation threshold respected.

`observed_fully=False` when the outcome required a bar beyond the data end.

### 6.4 Evaluator / reporter
Aggregates `ReplayOutcome`s across the entry set per policy, applies the out-of-sample
split (§9), ranks by dollars, emits the report.

## 7. The correctness gate (keystone)

`journal_trade` has no `exit_reason` column (§5), so the gate cannot select "price-rule
trades" directly. It uses a structural signature instead:

> **`min_hold_days = 14` gates rotation.** Rotation cannot exit a position before 14 days.
> Therefore **any trade held < 14 days was necessarily exited by a price rule.**

That yields a hard, falsifiable requirement on **6,093 trades (20.5% of the analysis set)**.

**Hard requirement.** For every trade held < 14 days, replaying MQR's current price rules
must reproduce the recorded `(exit_at, exit_px)`. Any mismatch is an unexplained semantic
divergence from `strategy_backtest_adapter.py`, and **every downstream conclusion is void
until it is fixed.** No results are reported while this fails.

**Soft expectation (corroboration, not a tolerance).** For the 23,643 trades held ≥ 14 days,
mismatches are legitimately attributable to rotation. Combining two independent numbers —
price rules cause 65.4% of exits, and 20.5% of trades are held < 14 days — predicts:

    65.4% − 20.5% = 44.9% of all trades  →  ≈56% of the ≥14-day trades should reproduce

A reproduced fraction far below ~56% on ≥ 14-day trades means price semantics are wrong
there too, and that rotation does not explain the gap. This is a checkable prediction.

Comparison tolerances: prices to 2 decimals (the column's precision) or one tick; dates by
trading-calendar position, not calendar-day difference.

Both fractions are reported in the phase-1 output. The gate passes on the hard requirement;
the soft expectation is reported either as corroboration or as a second-order bug.

### 7.1 Gate outcome (verified 2026-09-30, after corrections)

Run exhaustively over the 2,013 deduplicated positions:

| Measure | Result |
|---|---|
| Price-rule trades reproduced (date **and** price) | **1,342 / 1,349 = 0.9948** |
| Semantic mismatches (wrong trigger date or censored) | **0** |
| Label inconsistencies (held < 14d carrying a rotation label) | **0** |
| Capped corroboration, all trades capped at recorded exit | 1,349 / 2,013 = 0.6667 |
| Rotation-exited trades (excluded from the hard requirement) | 664 |

`label_inconsistencies` is the surviving value of the original structural
signature: the recorded labels agree with the rules, so the signature was sound
even though it turned out to be unnecessary.

**The 7 residual price differences are one data-vintage class, all in one ticker
(ALB).** ALB entered 2022-06-02, triggered 2022-06-13 — both dates correct and the
reason `Trailing Stop` correct — records a fill of 211.91, a value that appears in
**no bar of ALB's 8,203-row history**, as neither a close nor an open on any date.
The panel's close is 210.14 and the next open 211.32. The price data was revised
after those backtests wrote their rows. This is **common-mode** across policies
(every policy replays the same panel), so it cannot bias a *comparison*.

**Consequence:** the engine's rule semantics are established — 100% date agreement
and zero semantic mismatches over every price-rule trade. Absolute price levels
carry a residual vintage uncertainty confined to a single ticker.

## 8. Policies evaluated

Baseline: MQR's current price rules (hard stop 0.20, trailing 0.12, activation 0.0,
take profit 0.50, time stop 120).

**`off` means the rule is disabled entirely** — it never fires, so the position exits only
via the remaining rules or at the rotation cap. `trailing_stop` off, for example, asks
"what if we never trailed at all?"

Variants — one lever at a time, then combinations of the winners:
- `trailing_stop` ∈ {0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, off}
- `trailing_stop_activation` ∈ {0.0, 0.05, 0.10, 0.15, 0.20}
- `take_profit` ∈ {0.25, 0.35, 0.50, 0.75, 1.00, off}
- `time_stop_days` ∈ {40, 60, 90, 120, 180, off}
- `hard_stop_loss` ∈ {0.10, 0.15, 0.20, 0.30, off}

"off" matters: today's analysis showed the 20% hard stop fires on only 0.5% of exits at
baseline (a 12% trail always fires first), so its value is an open question rather than an
assumed one.

## 9. Evaluation and honesty guards

1. **Time-based out-of-sample split.** Fit on 2020-2023 entries (**1,360** distinct
   positions), validate on 2024-2025 (**545**). 2026 is excluded from the comparison
   (108 positions) but still contributes to §7's gate.

   **Corrected:** this originally claimed the halves were "nearly equal" (13,088 vs
   13,245). That was true only of the *raw* row counts, which were 97% duplicates with
   multiplicity rising by year — so counting rows made the two halves look comparable
   when by distinct position they are 1,360 vs 545. The split remains a clean
   time-based holdout; what changed is that it is no longer described as balanced, and
   the multiplicity confound is removed.
2. **Policy-dependent censoring.** A trade is dropped for a *given policy* only when that
   policy needed data past the data end — not blanket-excluded by trade. Aggregates report
   the count dropped per policy, so a policy that looks good only because its losing
   tail was censored is visible as such.
3. **Rank by dollars, not percent.** Report total P&L impact on the fixed entry set; a
   percentage improvement on a small position is not a decision.
4. **Fill convention matches the recorded data — and is verified, not assumed.**
   AMENDED 2026-09-30 during implementation: this originally read "next-open fills
   only, never the signal day's close". That makes the recorded baseline
   irreproducible, because **the historic `journal_trade` data is CLOSE-filled**.
   Verified directly: of 600 sampled short-hold trades, **600 matched the trigger
   day's close and 0 matched the next open**. The adapter's next-open logic
   postdates the rows that wrote `journal_trade`.

   So the primary convention is `fill="close"` (gate, and the apples-to-apples
   baseline for every policy). `fill="next_open"` is retained and is reported as
   a **sensitivity check** on winning policies, so the look-ahead optimism of
   trading at an observed close is quantified rather than assumed away.
5. **Report the censored count and the delisted/missing-ticker count.** Delisting
   correlates with poor outcomes, so silently dropping those trades flatters every policy.
6. **A policy is only a candidate if it wins out-of-sample.** In-sample winners are
   reported as such and not promoted.

## 10. Error handling

| Condition | Handling |
|---|---|
| Ticker missing from panel (delisted/renamed) | Mark `censored_missing`; report count; exclude from policy comparison |
| Forward window shorter than needed | `observed_fully=False`; excluded from that policy's aggregate |
| No bars after entry date | Skip, count, report |
| Zero/negative price in window | Skip bar, log ticker+date, count |
| Duplicate (ticker, entry_date) in entry set | Keep both (distinct positions); assert no exact-duplicate rows |

All counts surface in the report. Nothing is silently dropped.

## 11. Testing

- **Replay reproduces recorded exits** (§7) — the keystone test.
- Unit tests per rule function: trailing arming/threshold boundaries, take-profit
  boundary, time-stop boundary, precedence when two rules fire on one bar, next-open fill.
- Determinism: identical inputs → identical outputs, asserted across two runs.
- Censoring: a synthetic trade near the data end yields `observed_fully=False` and is
  excluded from aggregates.
- Entry-set freeze: artifact checksum stable across regeneration from unchanged DB state.
- No-look-ahead: assert no bar with `date <= entry_date` is consumed; assert the fill
  price is the next open, not the trigger bar's close.

## 12. Deliverables

1. Frozen MQR entry-set artifact + extractor.
2. Price-window loader (per-ticker cached).
3. Replay engine + unit tests.
4. Keystone correctness test (§7).
5. Policy grid evaluator with the time split and censoring accounting.
6. Report at `docs/reports/` — per-exit-reason regret, MFE/MAE distributions, policy
   ranking (in-sample vs out-of-sample), dollars at stake, censoring counts.
7. Optional backfill of `mae`/`mfe` into `journal_trade` (also repairs the pre-existing
   broken `tests/coach/test_analytics.py::test_mae_mfe_scatter_shape`).

## 13. Non-goals (YAGNI)

- No model training or inference.
- No changes to `strategy_backtest_adapter.py` behaviour.
- No multi-strategy comparison yet.
- No rotation-rule optimisation.
- No live-trading integration.

## 14. Risks

| Risk | Mitigation |
|---|---|
| Replay semantics diverge from the adapter, making results meaningless | §7 keystone gate blocks all conclusions until it passes |
| In-sample winner overfits to 2020-21 | §9 time split; in-sample winners never promoted |
| Entries are simulator-selected, so the entry set carries the screener's own bias | Out of scope by design (entries held fixed); recorded as a limitation. Results describe *exit* behaviour on this entry distribution, not a universal exit law |
| 2026 largely unusable for full-horizon replay | Accepted; 52 usable full-horizon entries still feed the correctness gate |
| Policy grid invites multiple-comparisons overfitting | One-lever-at-a-time first; combinations only from out-of-sample winners; report all, promote few |

## 15. Success criteria

1. §7 gate passes with all mismatches in enumerated, explained classes.
2. A ranked, out-of-sample-validated list of exit-rule candidates with dollar impact on
   MQR's real entry set.
3. MFE/MAE distributions per exit reason, answering concretely whether the 12% trailing
   stop and +50% take profit destroy value.
4. Every number traceable to the frozen entry set, the policy config, and the censoring
   accounting.

## 16. Phase 1 results (verified 2026-09-30)

Baseline = MQR's current price rules. Figures are the validate bucket (2024-2025)
as summed per-trade P&L at a constant $20k notional — an approximate but
rank-preserving scale (see §9). The capped bound equals baseline **to the cent**
for all 27 policies, which is the pipeline's end-to-end validation: constrained to
the recorded exit dates the replay reproduces reality exactly.

| Lever | Variants (validate P&L; baseline $648,076) |
|---|---|
| Trailing stop | 0.08 $495,581 · 0.10 $512,331 · **0.12 $648,076** · 0.15 $800,423 · 0.20 $964,331 · 0.25 $1,152,329 · **0.30 $1,156,189** · off $1,152,181 |
| Trailing activation | 0.05 $754,857 · 0.10 $837,701 · 0.15 $910,780 · **0.20 $953,306** · off(0.0) $648,076 |
| Take profit | 0.25 $537,619 · 0.35 $601,950 · **0.50 $648,076** · 0.75 $661,476 · 1.00 $664,951 · **off $687,753** |
| Time stop | 40 $484,216 · 60 $636,054 · 90 $664,365 · **120 $648,076** · 180 $670,344 · off $680,615 |
| Hard stop | 0.10 $645,957 · 0.15 $648,076 · 0.30 $648,076 · off $648,076 |

**Finding (PER-TRADE ONLY — see §17 for the retraction).** Every price-based exit
*looks* better when loosened, monotonically, in both halves: the 12% trailing stop,
the activation threshold and the +50% take profit all appear to cut winners short.
The hard stop is inert (0.15 / 0.30 / off identical to baseline, because a 12% trail
always fires first), confirming the earlier turnover audit.

**This ranking must NOT be read as a portfolio result.** §17 shows it does not
survive the full adapter, because the replay has no slot opportunity cost.

**Bounds.** The primary figures replay price-exited trades uncapped to the
180-trading-day horizon while rotation exits stay capped, so they are an **upper
bound**: rotation is held fixed and could have removed a name sooner. A policy
that wins only on the upper bound is not a candidate.

**Next-open sensitivity.** For `trail_0.30`, next-open fills give $1,178,046
against $1,156,189 close-filled — so the close-fill convention is *conservative*
here rather than inflating the result.

**Phase 2 candidate:** widen the trailing stop (0.20-0.30, or disable it) and/or
loosen take profit, re-validated on fresh data with the multi-start / batch
methodology — never a single run.

## 17. Phase 2 outcome — the frozen-entry ranking does NOT survive deployment

Phase 2 was to turn the §16 evidence into a better deterministic exit rule,
selected on fit and confirmed on the held-out validate bucket. That protocol was
followed (`scripts/mqr_phase2_select.py`, `_combo.py`) and it produced exactly the
result §16 predicts:

| | fit-selected winner | held-out validate |
|---|---|---|
| single lever | `trail_off` | +77.8%, ranks #3 of 27 |
| combination | `trail_off + act20 + tp_off` | **+135.3%, ranks #1 of 9** |

Both with **0% censored**, so neither is a censoring artifact.

**Then the deployment-realistic check contradicted it.** Running the same rules
through the full `StrategyBacktestAdapter` (paired across 6 start dates, because
entries drift there by construction):

| rule | CAGR median | CAGR wins | Sharpe |
|---|---|---|---|
| conservative (trail 0.30 + act 0.20 + tp off) | **−7.26** | 1/6 | worse on **6/6** |
| aggressive (trail off + act 0.20 + tp off) | −2.44 | 3/6 | worse on 2/6 |

### Why — and the retraction

**A frozen-entry replay has no slot opportunity cost.** Its entire "advantage" is
holding the *same* position longer:

| | mean hold | mean return/trade |
|---|---|---|
| baseline | 29.0 days | 4.47% |
| trail_off + act20 + tp_off | **69.0 days** | **10.26%** |

But the true alternative to holding longer is not holding cash — it is holding a
*different stock*. The live adapter frees the slot and refills it with the next
ranked candidate, which earns its own return. The frozen replay cannot see that.

**Therefore:**
- The frozen harness is valid for **per-trade** questions: excursions, forward-return
  regret, exit-reason decomposition, "was this winner sold too early?".
- It is **invalid for ranking exit policies at portfolio level.** That question
  requires the full adapter with multi-start.
- §16's ranking is accordingly retracted as a portfolio result; its *descriptive*
  content (the exit mix, the inert hard stop, the 0%-vs-21% censoring contrast) stands.

### Verdict on phase 2

**No exit-rule change is justified.** The candidates that look best on frozen
entries are neutral-to-worse through the adapter, the conservative one degrading
Sharpe in 6 of 6 starts. MQR's current exit constants stay.

One genuine signal survives in the noise: the conservative rule improved max
drawdown on 4 of 6 starts (−2.24 median), consistent with §16's direction. So
loosening the trail is a **risk/return trade** (less drawdown, worse Sharpe), not a
free improvement — which is a coherent thing to consider later on its own merits,
not as a return play.

### What phase 2 established methodologically

To make a frozen-entry replay answer a *portfolio* question you must model the slot
refill, which requires the cross-sectional ranking — at which point the analysis is
no longer frozen and the chaos returns. So the two questions need two harnesses:

| question | harness | why |
|---|---|---|
| was this trade exited badly? | frozen entry set | deterministic, no chaos |
| is this exit rule better? | full adapter, multi-start, paired | models the refill; entries drift, so average over starts |

Corollary, and a real trap this work hit: the aggregate **excludes censored trades**,
so a policy whose non-exits correlate with outcome can be scored by censoring alone.
`trail30+act20+tp_off+time_off` scored −142.7% purely because 21% of trades never
exited and the observed remainder was dominated by hard-stop losses (its per-trade
*mean* was positive). Always read `n_censored` before believing a ranking.
