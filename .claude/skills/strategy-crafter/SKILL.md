---
name: strategy-crafter
description: Use when turning a plain-English trading strategy idea into generated, backtested code in the AITrader-2 stack — creating a new rotation strategy, producing its standalone script alongside its in-app Strategy ABC class, confirming the two agree, or building the HTML performance report for a strategy or batch backtest.
---

# Strategy Crafter — Natural Language to Verified, Reported Strategy

A multi-phase skill that transforms a plain English strategy idea into:
1. A **standalone CLI wrapper** (`strategies/<name>.py`) — runnable on its own, but a thin entry point that delegates to the in-app class through `StrategyBacktestAdapter`
2. A **Strategy ABC subclass** (plugs into the app's backtesting adapter and Alpaca runner)
3. A **comprehensive HTML performance report** with equity curve, trade milestones, and strategy details

**Core principle:** Both versions of the strategy MUST produce identical performance results on the same date range. Because the standalone delegates to the same adapter and the same class, this is **guaranteed by construction** — not established by comparing two independent simulations.

---

## Phase 1: Clarify & Coach

Before writing any code, engage the user in a structured dialogue. For each topic:

1. **Ask** what the user wants
2. **Provide examples** of common approaches
3. **Critique** the user's choice if it has known weaknesses
4. **Recommend** better alternatives when appropriate

### Topics to cover (in order):

**1. Entry Signal**
- *Examples:* "EMA20/50/200 crossovers, RSI oversold/overbought, Bollinger squeeze, volume breakout, ATH breakout, or a combination"
- *Critique:* "A single EMA crossover alone can be noisy — combining with a volume or volatility filter often improves reliability"

**2. Candidate Ranking / Scoring**
- *Examples:* "60% crossover angle + 40% market cap, pure momentum (N-day return), RSI strength, composite score"
- *Critique:* "Pure momentum scores can concentrate in small-cap blowups — adding a market cap or volatility component adds stability"

**3. Exit Rules** (in priority order)
- *Examples:* "Death cross, trailing stop (15-25%), take profit (20-30%), time stop (60-120 days), hard stop loss (10%)"
- *Critique:* "A trailing stop below 15% is very tight for trending strategies — golden cross strategies routinely see 10-15% pullbacks within uptrends"

**4. Position Sizing**
- *Examples:* "Equal weight, score-weighted, score-squared (top-heavy), fixed percentage"
- *Critique:* "Score-weighted sizing concentrates capital in your best ideas — equal weight is safer but leaves edge on the table"

**5. Risk Management**
- *Examples:* "Sector caps (2-3 per sector), volatility filter (skip >5% daily std), bear market cash mode (SPY < SMA200)"
- *Critique:* "No sector cap means you can end up 5 positions deep in one sector — a sector-wide downturn hits the whole portfolio"

**6. Parameters**
- Max holdings (3-10)
- Min hold days (7-14 recommended)
- Take profit level (20-30%)
- Trailing stop (15-25%)
- Time stop (60-120 days)
- Hard stop loss (5-15%)

**7. Special Filters**
- Volume ratio minimum
- Market cap minimum
- Regime detection (Markov, SPY trend)
- Crisis override

### Output of Phase 1:
A structured spec document saved to `docs/strategies/<name>-spec.md` with all decisions recorded.

---

## Phase 2: Generate

Two files, **one implementation**. The in-app class holds all the strategy logic; the
standalone is a thin wrapper that delegates to it through the adapter. They differ only
in interface, never in behaviour.

### File 1: Standalone Script (thin CLI wrapper)
**Path:** `strategies/<name>.py`

Follow the `strategies/daily_golden_cross_rotation.py` pattern: a **wrapper**, not a
simulator. It imports the in-app class, hands it to the adapter, and prints/serialises
the result.

```python
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.<name> import <ClassName>

adapter = StrategyBacktestAdapter(<ClassName>())
result = adapter.run(as_of=AS_OF, end=END, capital=CAPITAL)
```

- Sets `sys.path`, DB env defaults, and constants (`AS_OF`, `END`, `CAPITAL`)
- `main()` calls `adapter.run(...)` and prints a summary from `result["summary"]`
- Exports `result` for HTML report generation
- Runnable with: `cd backend && ./venv/bin/python ../strategies/<name>.py`

**Do NOT give the standalone its own `precompute_stock_data()`, daily simulation loop,
position management, or exit logic.** That duplicates the in-app class and is the single
most reliable way to make the two versions diverge. The `golden_cross_rotation_v2.py`
lineage does hand-roll its loop — that architecture is superseded here; do not copy it
into a new strategy.

**Key patterns to follow (inside the in-app class):**
- `from app.db.database import engine` for DB access
- `from app.utils.security import get_safe_table_name`
- `from sqlalchemy import text`
- Guard `market_cap` against NULL
- Use `np.searchsorted(dates, np.datetime64(date_str))` for date lookups
- Use `pd.Timestamp(x).strftime("%Y-%m-%d")` for numpy datetime64 conversion
- Call `.mean()` on `.ewm()` before accessing `.values`
- All KPI values must be JSON-safe (no Infinity/NaN)

### File 2: In-App Strategy ABC Subclass
**Path:** `backend/app/services/strategies/<name>.py`

Follow the `Strategy` ABC pattern from `app.services.strategy_base`:
- Subclass `Strategy`
- Implement `get_name()`, `get_signals()`, `should_exit()`, `max_holdings`, `sizing_pcts`
- `get_signals()` queries the DB for the given `as_of_date`
- `should_exit()` checks death cross, death cross warning
- Optionally override `precompute_signals(all_dates, engine)` (`strategy_base.py`) to compute
  all signals once, vectorized — this is the hook the indicator-warmup rule below applies to
- Built-in exits (trailing stop, take profit, time stop) are handled by the `StrategyBacktestAdapter`

### Critical: Identical Performance Requirement

Both versions MUST produce identical results — this is the skill's core principle. It is
met **structurally**, not by matching two codebases:

1. **One implementation** — the in-app class holds all entry conditions, scoring formula,
   and exit rules. The standalone contains none of it.
2. **One simulator** — both paths run the same `StrategyBacktestAdapter`.
3. **One wiring** — the wrapper must construct the same class with the same
   `as_of` / `end` / `capital`. That is the only thing that can differ.

If you catch yourself writing strategy logic a second time in `strategies/<name>.py`,
stop: you have broken the guarantee.

---

## Phase 3: Verify

After generating both files, run a verification suite:

### Step 1: Syntax Check
```python
import ast
ast.parse(open("strategies/<name>.py").read())
ast.parse(open("backend/app/services/strategies/<name>.py").read())
```

### Step 2: Standalone Smoke Test
Run the standalone script with a short date range (e.g., 2023-01-01 to 2024-01-01):
```bash
cd backend && ./venv/bin/python ../strategies/<name>.py
```
Check: exits cleanly, prints summary, produces non-zero trades.

### Step 3: In-App Smoke Test
Run the in-app version through the backtesting adapter:
```python
from app.services.strategies.<name> import <ClassName>
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
adapter = StrategyBacktestAdapter(<ClassName>())
result = adapter.run(as_of="2023-01-01", end="2024-01-01", capital=100_000.0)
```
Check: `result["summary"]["total_trades"] > 0`

### Step 4: Structural Parity Check
Parity is by construction, so do not diff two simulations — verify the construction:

```bash
grep -c "StrategyBacktestAdapter" strategies/<name>.py        # expect >= 1
grep -cE "for .* in .*dates|precompute_stock_data" strategies/<name>.py  # expect 0
```

If the standalone has its own loop or its own copy of the strategy logic, that is the
bug — delete it and delegate to the adapter instead. A numeric comparison of two
independently-reimplemented simulators is not a useful check: any drift it catches, it
catches only after the logic has already been duplicated.

### Step 5: Report Results
Present a summary table to the user:
```
Verification Results:
  Syntax:         ✅
  Standalone:     ✅ (+X% return, Y trades)
  In-App:         ✅ (+X% return, Y trades)
  Identical:      ✅ (wrapper delegates to the adapter; no duplicated logic)
```

---

## Phase 4: Learn (Interactive)

This phase happens OUTSIDE the skill — in the app's terminal.

**Flow:**
1. User runs experiments in the Strategy Lab (app UI)
2. User opens the terminal (`/terminal`) and runs `claude`
3. User describes the performance to Claude Code (or shares the HTML report path)
4. Claude Code analyzes the results and suggests improvements
5. User decides which changes to apply
6. Claude Code updates the strategy files and re-verifies

**What Claude Code should do in this phase:**
- Read the HTML report to understand performance
- Identify weak areas (high drawdown, low win rate, poor Sharpe)
- Suggest specific parameter changes with rationale
- Offer to implement changes and re-verify

---

## Phase 5: Report

Generate a single, comprehensive HTML report that combines the best of both existing formats.

### Report Structure

**1. Hero Section** (top of report)
- Strategy name, date range, number of runs
- Big stat cards: Mean Return, Median Return, Sharpe, Win Rate, Max DD, Profit Factor
- Color-coded (green for positive, red for negative)

**2. Strategy Details** (collapsible)
- Entry signal description
- Scoring formula
- Exit rules (in priority order)
- All parameters in a table
- Full source code in a collapsible `<pre>` block

**3. Performance Distribution** (for multi-run batches)
- Decile table showing min/max/avg return per decile
- Bar chart or distribution visualization

**4. Sortable Run Table** (interactive, JavaScript-powered)
- Columns: Run#, Start, Duration, Ann Return, Total Return, Alpha, Final Value, Trades, Win%, Profit Factor, Max DD
- Click column headers to sort
- Click any row to expand and show:
  - **Trade list** — all buy/sell trades for that run with ticker, entry/exit price, return, holding days, exit reason
  - **Exit breakdown** — count, win rate, and total P&L by exit reason
  - **Equity curve** — SVG line chart with buy/sell milestone markers

**5. Equity Curve with Milestones**
- SVG line chart showing portfolio value over time
- **Green dots** at buy points (with ticker label on hover)
- **Red dots** at sell points (with exit reason on hover)
- Tooltip shows: date, ticker, action (buy/sell), price, P&L

**6. Top & Bottom Trades** (across all runs)
- Top 10 winners: ticker, return, P&L, exit reason
- Top 10 losers: ticker, return, P&L, exit reason

**7. Exit Analysis**
- Table: Exit Reason | Count | % of Total | Win Rate | Total P&L
- Horizontal bar chart showing relative frequency

**8. Improvement Log** (from Phase 4)
- Table of changes made, with before/after KPIs
- Timestamped entries

### Technical Implementation
- Single self-contained HTML file (no external dependencies)
- CSS inlined in `<style>` block
- JavaScript for sorting, filtering, expand/collapse
- SVG for equity curve charts
- Dark theme (matching the app's aesthetic)
- Responsive layout

---

## Reference Files

When generating strategies, study these reference implementations:

- **Standalone reference:** `strategies/daily_golden_cross_rotation.py` — the gold standard: a thin wrapper that delegates to the adapter
- **In-app reference:** `backend/app/services/strategies/daily_golden_cross.py` — the gold standard for Strategy ABC subclasses
- **Superseded *for this skill's output* (do not copy its architecture):** `strategies/golden_cross_rotation_v2.py` — the only file with a hand-rolled `precompute_signals` loop. Its vectorization techniques remain the reference for the separate **Strategy Lab** codegen lineage (see project `CLAUDE.md`); they are not the pattern for the two-file output this skill produces.
- **Strategy ABC:** `backend/app/services/strategy_base.py` — the base class and data types
- **Backtesting adapter:** `backend/app/services/strategy_backtest_adapter.py` — runs Strategy ABC subclasses through daily simulation
- **Report reference 1:** `docs/reports/golden_cross_rotation_report.html` — static report with hero stats, deciles, exit analysis
- **Report reference 2:** `docs/reports/run_viewer.html` — interactive report with sortable table, expandable run details

## Known Pitfalls (from accumulated learnings)

When generating code, avoid these common issues:

1. **`create_engine()`** — exhausts PostgreSQL connections. Use `from app.db.database import engine`
2. **`get_safe_table_name`** — import from `app.utils.security`, NOT `app.db.database`
3. **`market_cap` can be NULL** — always guard with `if market_cap is None: continue`
4. **`.ewm().values`** — call `.mean()` first: `close.ewm(span=20, adjust=False).mean().values`
5. **Triple-quoted f-strings for SQL** — use single-line f-strings instead
6. **`holding_score` returning 1.0** — disables rotation, produces losing strategies
7. **`TAKE_PROFIT = 999.0`** — winners never locked in, they reverse
8. **`TIME_STOP_DAYS = 9999`** — stale positions held forever
9. **`MIN_HOLD_DAYS = 0`** — excessive churn
10. **NaN/Infinity in KPIs** — sanitize with `_json_safe()` before serialization
11. **Hand-rolled standalone loop** — giving `strategies/<name>.py` its own
    `precompute_stock_data()`, daily loop, or exit logic instead of delegating to
    `StrategyBacktestAdapter`. Duplicates the in-app class and breaks the parity
    guarantee by construction. See Phase 2, File 1.
12. **Ranking levers from single runs** — see "Single-run comparisons are invalid" below

## Empirical Findings (Golden Cross Volume Rotation, 2020-2026 backtest)

These are measured results from a real sweep on the AITrader-2 stack. They are
strong priors for future rotation strategies, not guarantees.

These are **design priors**, measured on the Golden Cross Volume Rotation lineage.
They concern what the strategy *does* (indicator choices, filters, exit levels), so they
transfer to any rotation strategy regardless of which harness runs it — they are not
claims about file architecture.

### Crossover MA choice (the single biggest lever)
- **EMA10/EMA200 is the sweet spot** (+766% ret, 38.2% CAGR, alpha +22.8%,
  Sharpe 1.59, PF 3.06). Fast EMA catches trends early; 200-day EMA slow line
  keeps it in genuine uptrends.
- **EMA20/EMA200** is solid but weaker (+341%, 24.9% CAGR, Sharpe 1.13).
- **EMA5/EMA200 is too fast** (+73%, alpha -6.8%, 146 death crosses = whipsaw).
- **SMA slow line collapses the edge**: EMA20/SMA200 and SMA10/SMA200 both
  drop to ~83-85% return, negative alpha, worse drawdowns. The **EMA slow line
  is critical** — do not use SMA for the 200-day trend line.
- Rule of thumb: fast EMA 10 > 20 > 5; slow line must be EMA200, not SMA200.

### Volume confirmation
- **1.5x 50-day volume filter is too restrictive** — keeps the strategy
  chronically underinvested (baseline +28% vs SPY +160%). Loosening to **1.0x**
  (volume just above the 50-day average) was the single biggest single-lever
  win (+168% ret, alpha +0.6, Sharpe 0.81, PF 1.60).
- A volume filter that's too tight starves the strategy of candidates. When a
  strategy underperforms SPY, check whether it's underinvested before tuning exits.
- **Spike-window confirmation (volume 1.5x the 10-day avg at any point in a
  recent window) does NOT beat a simple 1.0x cross-day check.** On the EMA10/200
  base, every spike-window variant (win 3/5/7/10) underperformed the 1.0x
  cross-day reference (766.5%). The looser the volume filter, the better — the
  spike requirement is still a drag. Best spike window was 5d (549.8%); 2.0x
  was catastrophic (28.7%, maxDD 59.8%).

### Bear market cash mode
- **0% exposure (full cash) is too aggressive** — misses the recovery.
  **50% exposure** is the better drawdown reducer (bear_0.5: +61% vs baseline
  +28%, Sharpe 0.45). Full cash mode leaves too much upside on the table.

### Exits (individual levers, on EMA20/50 base)

**Read this subsection with the caveat in "Single-run comparisons are invalid" below.**
These numbers came from one-at-a-time sweeps on single runs. The *direction* of a lever
(tighter trailing stop good, wider bad) survived later multi-start re-testing, but the
magnitudes did not — and any *ranking* between these levers is not trustworthy.

- **time_stop 120d** (+103%, Sharpe 0.62, maxDD 29.7) and **take_profit 0.30**
  (+90%, PF 1.43) both help vs baseline (+28%).
- **trailing_stop 0.25/0.30** hurt badly (+5%) — wider trail stops let winners
  reverse. Keep trailing stop tight (0.20).
- **min_hold 7** and **min_hold 14** both hurt — 10 is the sweet spot.
- **hold_rank 15** is catastrophic (-21%); **hold_rank 20** is neutral. The
  top-10 hold band is right; widening it too far holds stale names.

### Methodology
- Make the strategy parameterizable (overrides with pinned defaults and unknown-key
  rejection, so a typo'd sweep key raises instead of silently re-running the baseline)
  so you can sweep configs without editing files. Run one-at-a-time sweeps first, then
  stack the winners in a combo sweep.
- The standalone script and in-app class share the same `StrategyBacktestAdapter`,
  so identical performance is guaranteed by construction — Phase 3 Step 4 verifies the
  wiring structurally, so no numeric two-simulation comparison is needed.
- Always compare against SPY (alpha), not just raw return. A strategy can be
  profitable yet badly underperform buy-and-hold.

### Single-run comparisons are invalid — use multi-start medians
Integer share counts (`shares = int(target_value / price)`) make a single backtest
path-chaotic: a tiny cost drag shrinks cash, which shrinks portfolio value, which flips
a share count, which produces a *different trajectory*. Reproduced bit-identically —
varying only `cost_bps` moved CAGR by **+32 points** at a 0.30%/yr drag.
- Never rank levers from single runs. Use multi-start sampling (6+ start dates) or a
  100-run batch, and compare **medians**.
- A lever that looks like a large win in one run may be noise. Confirm with paired
  multi-start before believing it.
- Corollary: `bear_exposure = 0.50` was confirmed optimal this way against
  0.00/0.25/0.35/0.75/1.00 — none wins. It is also a poor drawdown control: it scales
  NEW entries only and never force-exits holdings, so it forgoes the recovery without
  avoiding the decline, and drawdown is therefore *not* ordered by exposure.

### Indicator warmup is a silent backtest killer
- **`precompute_signals` must load data from an early fixed date (e.g. 2008),
  NOT from a date near the simulation start.** A hardcoded `load_start="2018-01-01"`
  truncated history so early-2020 dates had only ~500 bars — EMA200 needs ~830
  bars to converge. That produced slightly different golden-cross detections in
  early 2020 (only ~0.8% of signals differed), but those few different entries
  compounded over the 2020-21 bull run into a **325% return gap** (766.5% vs the
  correct 441.4%). The inflated number looked "locked in" but was an artifact.
- **Symptom to watch for:** a strategy's headline return changes dramatically
  when you change how much history is loaded, even for a start date that should
  be fully warmed. That means indicators weren't converged.
- **Fix:** always load from an early fixed date (2008) with a generous LIMIT
  (5000), so every simulated date has full indicator warmup. Do NOT derive
  load_start from `first_date - N days` — for early simulation starts that can
  push it later than a fixed early date and truncate warmup.
- **Verification:** after changing warmup, confirm the baseline is unchanged for
  a late start (e.g. 2020) — if it moves, indicators weren't converged before.
- **A/B in fresh subprocesses:** module-cache contamination can make two configs
  look identical when they differ, or vice versa. To isolate a load-config effect,
  run each variant in a fresh `python -c` subprocess, not the same interpreter.
