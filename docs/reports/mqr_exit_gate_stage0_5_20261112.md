# MQR exit veto — Stage 0.5 deterministic sweep

Date: 2026-11-12. Script: `backend/scripts/mqr_exit_gate_100run.py`.
Raw: `/tmp/mqr_exit_gate/stage0_5.json`. Plan:
`.claude/plans/lets-try-a-few-squishy-crescent.md`.

## Question

Before training a model or calling an LLM: **is there any selective exit-veto
signal at portfolio level at all?** Ten transparent rules, each expressed as a
predicate over the position's own state, were run through the full
`StrategyBacktestAdapter` — 100 distinct start dates, common end 2026-11-11,
paired per start, length-normalized metrics. Every rule may only *veto* a price
exit; hard stops and rotation are never touched.

This is the only valid method here: phase 2 ranked "loosen the trail" a large
winner in frozen-entry replay and then measured it through the adapter at
**−7.26 pts median CAGR, worse Sharpe on 6/6 starts**.

## Results at 0 bps (median of paired deltas, 100 starts)

| Gate | ΔCAGR | wins | ΔSharpe | ΔmaxDD | Δtrades/yr | veto rate |
|---|---|---|---|---|---|---|
| `veto_all_trail` (control) | −1.26 | 41 | −0.040 | +5.11 | | 94.3% |
| `veto_all_tp` (control) | −4.19 | 30 | −0.055 | −1.54 | | 75.0% |
| `veto_all_time` (control) | **+5.33** | 64 | +0.100 | −0.01 | | 54.5% |
| `veto_trail_if_in_profit` | −10.51 | 8 | −0.220 | +8.64 | | 74.3% |
| `veto_trail_if_big_winner` | −4.25 | 32 | −0.060 | +0.14 | | 16.3% |
| `veto_trail_if_shallow_pullback` | −8.96 | 15 | −0.180 | +4.92 | | 59.6% |
| **`veto_trail_if_young`** (`hold_days < 10`) | **+5.64** | **75** | +0.070 | −1.68 | | 27.1% |
| `veto_trail_if_large_peak` (`peak_gain > 0.30`) | +3.38 | 61 | +0.030 | −1.09 | | 67.2% |
| `veto_tp_if_not_extended` | −4.19 | 30 | −0.055 | −1.54 | | 75.0% |
| `veto_time_if_in_profit` | +5.33 | 64 | +0.100 | −0.01 | | 54.5% |

Notes: `veto_tp_if_not_extended` is identical to `veto_all_tp` because the take
profit only fires at +50%, where `peak_gain > 0.50` is always true — the
predicate is redundant, not a second experiment. `veto_time_if_in_profit` is
identical to `veto_all_time`, which says the time stop only ever fires on
positions still in profit.

## Cost check at 10 bps per side

| Gate | ΔCAGR | wins | median CAGR | ΔSharpe | ΔmaxDD | Δtrades/yr |
|---|---|---|---|---|---|---|
| baseline | — | — | 32.16 | 0.905 | 51.80 | 60.14 |
| **`veto_trail_if_young`** | **+5.33** | **66** | **36.55** | +0.040 | +1.17 | −3.11 |
| `veto_all_time` | +1.75 | 55 | 34.95 | +0.030 | +2.06 | −3.09 |
| `veto_trail_if_large_peak` | +0.28 | 54 | 33.90 | +0.015 | +0.19 | −6.09 |

Sign test on the win counts (100 paired starts), and Bonferroni over the 20
comparisons run here:

| wins/100 | one-sided p | ×20 | verdict |
|---|---|---|---|
| 75 | 2.8e-7 | 5.6e-6 | decisive |
| 66 | 8.9e-4 | 0.018 | survives correction |
| 64 | 3.3e-3 | 0.066 | marginal |
| 55 | 0.18 | — | not significant |
| 41, 30, 15, 8 | ≫0.5 | — | no effect / harmful |

## Dose-response: the surviving rule is fragile

The winner is "do not let the trailing stop fire before the position is N days
old". Sweeping N at 10 bps (baseline median CAGR 32.16, maxDD 51.80):

| N (days) | ΔCAGR | wins | ΔSharpe | ΔmaxDD | median CAGR |
|---|---|---|---|---|---|
| 5 | −0.08 | 50/100 | −0.020 | +0.35 | 32.70 |
| 7 | +7.56 | 73/100 | +0.070 | +3.33 | 36.84 |
| 10 | +5.33 | 66/100 | +0.040 | +1.17 | 36.55 |
| 14 | −4.58 | 31/100 | −0.090 | −2.12 | 27.57 |

The response is **not monotone**: nothing at 5 days, a peak at 7, a good result at
10, and a large loss at 14. A genuine mechanism should improve smoothly with the
protection window. This pattern means the exact threshold matters more than the
idea, and picking 7 because it scored best is selection on the same 100 starts
used to report significance. Treat the threshold as unfitted: 10 days is the
defensible a-priori choice because it sits just under the strategy's existing
14-day rotation minimum, and its result (+5.33, 66/100) survives Bonferroni;
7 days does not deserve to be preferred on this evidence.

## The LLM arm (Stage A)

A local model (`qwen3:8b`, native Ollama `/api/chat`, `think:false`, temperature
0) was asked the real decision contexts collected from 20 baseline starts:
**8,474 consultations collapse to 1,571 distinct contexts** (5.4× recurrence), so
a content-addressed cache makes a full sweep tractable.

Two polarities were measured on the same 119-context stratified sample, labelled
by the slot-aware 20-day hindsight answer (base rate of "holding was better" =
**0.252**):

| Policy | veto rate | precision | recall | AUC |
|---|---|---|---|---|
| `hold_confidence` (veto only when confident holding wins) | **0.0%** | — | 0.0 | 0.531 |
| `exit_confidence` (proceed only when confident; user's policy) | 15.1% | 0.278 | 0.167 | 0.551 |
| simple rule `hold_days < 10`, same sample | 10.1% | 0.250 | 0.100 | — |

Neither the model nor the simple rule shows per-decision discrimination: 0.278
precision against a 0.252 base rate is nothing. The model under the
`hold_confidence` framing was completely inert — it never once held.

**Important methodological point:** per-decision precision is *not* what makes
this lever work. The simple `hold_days < 10` rule has the same chance-level
precision and yet produces +5.3 pts of CAGR through the adapter. The value is a
path/compounding effect — which positions get to keep compounding and what gets
bought later — not classification accuracy. A model trained on the per-decision
hindsight label would therefore miss the lever entirely, and an AUC screen can
reject a policy that actually helps. The adapter delta is the only arbiter.

## The LLM arm through the full adapter

`qwen3:8b`, `exit_confidence`, threshold 0.80, 20 paired starts, 10 bps:

| | result |
|---|---|
| ΔCAGR | **+2.08 pts** |
| wins | **12/20** (p = 0.25, not significant) |
| ΔSharpe | −0.025 |
| ΔmaxDD | **+1.17 pts worse** |
| decision-level veto rate | 59.8% |
| fail-open | 0 |
| wall-clock | **5,565 s (93 min) for 20 starts** |

The same 20-start baseline runs in 14.6 s; the 100-start deterministic sweep runs
in ~70 s. The LLM arm therefore costs roughly **1,000× more compute** for a
result that is smaller, not significant, worse on Sharpe, and worse on drawdown
than the one-line rule.

The 59.8% decision-level veto rate is much higher than the 15.1% measured in
Stage A because a deferred exit re-fires the rule the next day and may be
vetoed again — decision-level rates are not exit-level rates, and this is why the
adapter, not the decision sample, is the arbiter.

## What this says

1. **The user's original instinct — veto the trailing stop — is only right when
   conditioned on position age.** Unconditional trail vetoing loses
   (−1.26 pts, 41/100) and makes drawdown 5.1 pts worse. Every profit-based
   condition tested (`ret > 0`, `ret > 0.20`, shallow pullback) loses badly,
   up to −10.5 pts. The one that works is **"do not let the 12% trail stop out a
   position in its first 10 days"**: +5.64 pts / 75-of-100 at 0 bps and
   +5.33 pts / 66-of-100 at 10 bps.
2. **The mechanism is plausible.** The rotation rule already has a 14-day
   minimum hold, but the trailing stop bypasses it. So the strategy regularly
   sells on ordinary early noise, then re-enters the same name the same day
   (11.4% of exits were same-day re-entries). The rule simply extends the
   existing min-hold protection to the trail.
3. **Drawdown does not improve.** At 0 bps the young-veto is 1.7 pts better on
   maxDD; at 10 bps it is 1.2 pts worse. That is a wash, not a risk improvement —
   consistent with the plan's warning that a veto can only produce later exits.
4. **The time-stop result does not survive cost.** +5.33 pts at 0 bps falls to
   +1.75 at 10 bps with 55/100 wins (p=0.18). It is not a finding.
5. **The AI question is now framed correctly.** A learned or LLM gate has to beat
   a one-line rule worth **+5.3 pts at 10 bps**. If it cannot, the simple rule
   ships and no model is needed.

## Caveats

- The universal ones still apply: universe filtered on *current*
  `stock_metadata` market caps (lookahead), survivorship, next-open fills,
  integer share sizing.
- 20 comparisons were run; the table above applies Bonferroni.
- The 100-start design weights starts, not calendar years.
- Costs are a flat 10 bps per side; no slippage or borrow.
