# Refine Strategy & Performance Chatbot Integration

**Date:** 2026-07-30
**Status:** Draft

## Problem

Two issues in the AI Strategy Builder (Strategy Lab):

### Issue 1: Refine Strategy Flow is Broken

After experiments finish, the user clicks "Refine strategy" → AI generates a diff based on worst-performing runs.

- **Problem A**: User has no input into what changes the AI proposes. The AI unilaterally generates a diff based on worst runs, and the user can only Accept or Reject.
- **Problem B**: Accepting the diff emits "Load Failed" error. Root cause: the `apply_diff` function in `strategy_lab_diff.py` tries to match lines between the diff and the current code. If the code has drifted (user edited it in Step 3), the diff doesn't match and application fails. The backend has a fallback that calls `debug_code` to produce a complete fixed file, but this can also fail.

### Issue 2: Performance Chatbot Doesn't Integrate with Strategy Lifecycle

When the user asks the chatbot to suggest code changes, the AI shows modified code in the chat but:

- **Problem A**: The code is shown in chat but not auto-verified against real data
- **Problem B**: It doesn't save as a newer version in the strategy library
- **Problem C**: It doesn't allow re-running experiments with the same starting dates for apples-to-apples comparison

## Solution

A unified approach that replaces the fragile diff-based refine flow with the proven `refineDirect` approach (complete file replacement + backtest validation), enhanced with user input, auto-versioning, and re-run prompting.

### Architecture

The design involves changes to 5 files:

1. `backend/app/services/strategy_lab_llm.py` — New function for refine-with-context
2. `backend/app/routers/strategy_lab.py` — Modified refine endpoint
3. `frontend/src/pages/StrategyLab/StepBacktest.tsx` — New refine flow UI
4. `frontend/src/components/strategy-lab/ChatPanel.tsx` — Auto-save + re-run
5. `frontend/src/lib/strategyLab.ts` — Updated API types

### Backend Changes

#### New function: `refine_strategy_with_instruction()`

In `strategy_lab_llm.py`, add a function that:

1. Accepts: `current_code`, `instruction` (user's focus), `batch_summary`, `worst_runs_table`, `model`
2. Builds a prompt with all context (current code, user instruction, batch performance data, worst runs)
3. Calls LLM to produce a **complete modified file** (not a diff)
4. Validates syntax and anti-patterns
5. Returns `(modified_code, summary, error)`

The prompt instructs the LLM to:
- Output the COMPLETE modified Python file in a ```python block
- Keep all imports, engine wiring, and CONFIG unchanged
- Only change strategy logic
- Explain what changed and why in a brief summary

#### Modified endpoint: `POST /sessions/{session_id}/batches/{batch_id}/refine`

Replace the current diff-based implementation:

```python
class RefineStrategyRequest(BaseModel):
    instruction: str = ""  # User's pre-refine instruction (optional)
    model: Optional[str] = None
    validation_runs: int = 10

class RefineStrategyResponse(BaseModel):
    code: str = ""
    summary: str = ""           # Human-readable summary of changes
    rationale: str = ""         # AI's reasoning
    before_kpis: dict = {}      # KPIs from the previous batch
    after_kpis: dict = {}       # KPIs from validation runs
    validation_log: List[str] = []
    validation_status: str = "unknown"  # "passed" | "partial" | "failed"
    version: Optional[dict] = None  # Auto-saved library version info
```

The endpoint will:
1. Load session code, batch stats (worst runs), and batch summary
2. Call `refine_strategy_with_instruction()` to generate modified code
3. Run validation backtests (N runs with random start dates within the same date range as the original batch)
4. Compute before/after KPI comparison:
   - `before_kpis`: Aggregate stats (median return, sharpe, max_dd, win_rate, trades) from the completed runs in the batch
   - `after_kpis`: Aggregate stats from the validation backtest runs
5. Auto-save to library with generated name + AI change description
6. Return the result

#### Auto-save to library

After a successful refine, auto-save to the strategy library:
- Name: `{session-name}-v{next_version}` (e.g., "sma_crossover-v2")
- Change description: AI's summary of what changed
- The version info is returned in the response

### Frontend Changes

#### StepBacktest.tsx — New Refine Flow

Replace the `DiffReview` component with a multi-step refine flow:

**Step 1 — Pre-refine input:**
When user clicks "Refine strategy", show a text input:
```
┌─────────────────────────────────────────────┐
│ // Refine strategy                          │
│                                             │
│ What should the AI focus on? (optional)     │
│ ┌─────────────────────────────────────────┐ │
│ │ e.g. "reduce max drawdown"              │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ [Cancel]  [Generate changes]               │
└─────────────────────────────────────────────┘
```

**Step 2 — Review panel (replaces DiffReview):**
```
┌─────────────────────────────────────────────┐
│ // AI suggested changes                     │
│                                             │
│ Rationale: The worst runs show high         │
│ drawdown during bear markets. Added a       │
│ SPY > 200d MA regime filter...              │
│                                             │
│ ┌─── KPI Comparison ──────────────────────┐ │
│ │              Before      After    Δ      │ │
│ │ Return       +12.3%     +18.7%   +6.4%  │ │
│ │ Sharpe       0.82        1.15     +0.33  │ │
│ │ Max DD       -22.1%      -15.3%   +6.8%  │ │
│ │ Win Rate     45.2%       51.3%    +6.1%  │ │
│ │ Trades       47          52       +5     │ │
│ └──────────────────────────────────────────┘ │
│                                             │
│ Change summary: Adjusted trailing stop      │
│ from 20% to 25%, added SPY > 200d MA filter │
│                                             │
│ Follow-up: [________________________] [Go]  │
│                                             │
│ [Reject]  [Accept & Save as v2]             │
└─────────────────────────────────────────────┘
```

**Step 3 — Post-accept:**
```
┌─────────────────────────────────────────────┐
│ ✅ Change applied and saved as "sma_crossover-v2" │
│                                             │
│ [Re-run with same dates (10 runs)]          │
│ [Dismiss]                                   │
└─────────────────────────────────────────────┘
```

#### ChatPanel.tsx — Auto-save + Re-run

After a successful `applyChange`:

1. **Auto-save to library**: Call `saveToLibrary` automatically with:
   - Name: `{session-name}-v{version}`
   - Description: The `[CODE_CHANGE: ...]` instruction text

2. **Show result in chat**:
   ```
   ✅ Change applied and saved as "sma_crossover-v2"
   [Re-run with same dates]
   ```

3. **Re-run button**: When clicked:
   - If the ChatPanel is rendered inside StepBacktest (has access to batch context): trigger a new batch directly with the fixed start dates from the previous batch
   - If the ChatPanel is rendered inside StepCode (no batch context): navigate to StepBacktest, passing the fixed start dates via session state or URL params
   - The user can adjust the number of runs before the new batch starts

### Data Flow

```
User describes focus
  → POST /refine (with instruction + batch context)
    → LLM generates complete modified file
    → Validates syntax + anti-patterns
    → Runs N validation backtests
    → Computes before/after KPI comparison
    → Auto-saves to library
    → Returns code + KPIs + version info
  → Frontend shows review panel
    → User iterates with follow-up instructions
    → User accepts
  → Frontend shows "Re-run with same dates" button
    → User clicks → starts new batch with fixed start dates
    → Results are comparable (apples-to-apples)
```

### Error Handling

| Scenario | Handling |
|----------|----------|
| LLM call fails | Show error in refine panel with "Retry" button |
| Validation fails | Show which runs failed and why, let user iterate |
| Auto-save fails | Log error, don't block — code is saved to session |
| Re-run fails | Show error in batch config form |

### Files Modified

1. **`backend/app/services/strategy_lab_llm.py`** — Add `refine_strategy_with_instruction()`
2. **`backend/app/routers/strategy_lab.py`** — Modify `refine_strategy_after_batch` endpoint
3. **`frontend/src/pages/StrategyLab/StepBacktest.tsx`** — New refine flow UI
4. **`frontend/src/components/strategy-lab/ChatPanel.tsx`** — Auto-save + re-run button
5. **`frontend/src/lib/strategyLab.ts`** — Update API types

### Files Deprecated

- **`backend/app/services/strategy_lab_diff.py`** — No longer needed (diff-based approach replaced)
- **`frontend/src/components/strategy-lab/DiffReview.tsx`** — No longer needed (replaced by KPI comparison panel)

### Key Design Decisions

1. **Complete file replacement over diffs**: The `refineDirect` approach (complete file + backtest validation) is proven in the ChatPanel. It eliminates the fragile diff-application step that caused "Load Failed" errors.

2. **KPI comparison over visual diff**: A before/after KPI table is more informative than a line-by-line diff. The user cares about whether the strategy improved, not which lines changed.

3. **Auto-save with AI description**: Every change is automatically versioned in the library with the AI's change description. This creates an audit trail and makes it easy to roll back.

4. **Fixed start dates for apples-to-apples**: The `previousStartDates` mechanism already exists in StepBacktest. The refine flow reuses it to ensure re-runs use the same time windows.
