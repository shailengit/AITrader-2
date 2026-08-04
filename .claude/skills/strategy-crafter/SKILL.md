# Strategy Crafter — Natural Language to Verified, Reported Strategy

A multi-phase skill that transforms a plain English strategy idea into:
1. A **standalone Python script** (runnable independently, queries PostgreSQL directly)
2. A **Strategy ABC subclass** (plugs into the app's backtesting adapter and Alpaca runner)
3. A **comprehensive HTML performance report** with equity curve, trade milestones, and strategy details

**Core principle:** Both versions of the strategy MUST produce identical performance results on the same date range. This is verified automatically.

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

Generate two versions of the strategy in parallel. Both must implement the EXACT same logic — only the interface differs.

### File 1: Standalone Script
**Path:** `strategies/<name>.py`

Follow the `strategies/daily_golden_cross_rotation.py` pattern:
- Self-contained: sets up DB connection, imports, constants
- `precompute_stock_data()` — loads all ticker data upfront
- `main()` — runs the full daily simulation loop
- Prints summary to stdout
- Exports data for HTML report generation
- Runnable with: `cd backend && ./venv/bin/python ../strategies/<name>.py`

**Key patterns to follow:**
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
- Built-in exits (trailing stop, take profit, time stop) are handled by the `StrategyBacktestAdapter`

### Critical: Identical Performance Requirement

Both versions MUST produce identical results. To ensure this:

1. **Same logic, same constants** — both files use the same entry conditions, scoring formula, exit rules, and parameter values
2. **Same data source** — both query the same PostgreSQL database
3. **Same simulation structure** — daily loop, position management, trade recording

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
result = adapter.run(as_of="2023-01-01", end="2024-01-01")
```
Check: `result["summary"]["total_trades"] > 0`

### Step 4: Identical Performance Check
Run BOTH versions on the SAME date range and compare:
- Total return (within 0.1% tolerance)
- Number of trades (exact match)
- Win rate (within 0.1% tolerance)
- Sharpe ratio (within 0.01 tolerance)

If they diverge, debug the difference and fix before proceeding.

### Step 5: Report Results
Present a summary table to the user:
```
Verification Results:
  Syntax:         ✅
  Standalone:     ✅ (+X% return, Y trades)
  In-App:         ✅ (+X% return, Y trades)
  Identical:      ✅ (return within 0.01%, trades match)
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

- **Standalone reference:** `strategies/daily_golden_cross_rotation.py` — the gold standard for standalone scripts
- **In-app reference:** `backend/app/services/strategies/daily_golden_cross.py` — the gold standard for Strategy ABC subclasses
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
