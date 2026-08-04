# Refine Strategy & Chatbot Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragile diff-based refine flow with a complete-file approach, add user input before/after refinement, auto-version to library, and prompt re-run with same start dates.

**Architecture:** Backend adds `refine_strategy_with_instruction()` that produces a complete modified file (not a diff) with batch context + user instruction. Frontend replaces `DiffReview` with a multi-step refine panel showing KPI comparison, follow-up input, and auto-save. ChatPanel auto-saves to library after apply and shows re-run button.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript (frontend), OpenAI-compatible LLM

## Global Constraints

- All LLM calls use `_chat()` from `strategy_lab_llm.py` with `max_tokens=16384`
- All new prompt functions go in `strategy_lab_prompts.py`
- Frontend uses `@tanstack/react-query` mutations for API calls
- Auto-save naming: `{session-name}-v{next_version}`
- KPI comparison uses aggregate stats (median/mean) from batch, not individual runs

---

### Task 1: Update Frontend API Types

**Files:**
- Modify: `frontend/src/lib/strategyLab.ts:108-113`

**Interfaces:**
- Consumes: existing `RefineStrategyResponse` type
- Produces: updated `RefineStrategyResponse` with new fields

- [ ] **Step 1: Replace the old `RefineStrategyResponse`**

Replace lines 108-113 with the new type:

```typescript
export interface RefineStrategyResponse {
  code: string;
  summary: string;
  rationale: string;
  before_kpis: Record<string, any>;
  after_kpis: Record<string, any>;
  validation_log: string[];
  validation_status: string;  // "passed" | "partial" | "failed"
  version: {
    version: number;
    strategy_name: string;
    change_description: string;
  } | null;
  error?: string;
}
```

- [ ] **Step 2: Verify the file compiles**

Run: `cd frontend && npx tsc --noEmit src/lib/strategyLab.ts 2>&1 | head -20`
Expected: No type errors (or only errors unrelated to this file)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/strategyLab.ts
git commit -m "feat(strategy-lab): update RefineStrategyResponse type for new refine flow"
```

---

### Task 2: Add Prompt Builder for Refine-With-Instruction

**Files:**
- Modify: `backend/app/services/strategy_lab_prompts.py` (add function after `make_refine_direct_prompt`)

**Interfaces:**
- Consumes: `current_code: str`, `instruction: str`, `batch_summary: str`, `worst_runs_table: str`
- Produces: `make_refine_strategy_direct_prompt(...)` → `List[Dict[str, str]]`

- [ ] **Step 1: Add the new prompt builder function**

Add after `make_refine_direct_prompt` (line 361):

```python
def make_refine_strategy_direct_prompt(
    current_code: str,
    instruction: str,
    batch_summary: str,
    worst_runs_table: str,
) -> List[Dict[str, str]]:
    """Prompt the LLM to modify strategy code based on batch performance + user instruction.

    The LLM outputs the COMPLETE modified file (not a diff), along with a brief
    summary of what changed and why.
    """
    user_instruction = f"\nThe user specifically asks: {instruction}" if instruction else ""
    return [
        {
            "role": "system",
            "content": (
                "You are a quant strategy refiner. Given a current strategy file, "
                "an AI-generated analysis of backtest runs, the worst-performing runs, "
                "and optionally a user instruction, propose a code change that improves "
                "the strategy.\n\n"
                "OUTPUT FORMAT: a single Python file wrapped in a markdown ```python block, "
                "followed by a brief summary on the last line prefixed with '## SUMMARY:'.\n\n"
                "Example output:\n"
                "```python\nimport ...\n...\n```\n"
                "## SUMMARY: Adjusted trailing stop from 20% to 25%, added SPY > 200d MA filter\n\n"
                "Rules:\n"
                "- Output the COMPLETE modified Python file — not a diff\n"
                "- Keep ALL imports, engine wiring, and CONFIG exactly as they are\n"
                "- Make ONLY the changes needed to address the worst runs and user instruction\n"
                "- The output must be a complete, valid Python file\n"
                "- Common improvements: adjust thresholds, widen/narrow stops, add filters, "
                "change position sizing, adjust take profit / time stop levels\n"
                "- CRITICAL: holding_score() MUST return a DYNAMIC score. "
                "TAKE_PROFIT must be enabled. TIME_STOP_DAYS must be reasonable."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Current strategy code:\n\n```python\n{current_code}\n```\n\n"
                f"Backtest analysis:\n{batch_summary}\n\n"
                f"Worst-performing runs (lowest Sharpe):\n{worst_runs_table}\n"
                f"{user_instruction}\n\n"
                "Output the COMPLETE modified Python file followed by ## SUMMARY: with a one-line description of changes."
            ),
        },
    ]
```

- [ ] **Step 2: Verify syntax**

Run: `cd backend && ./venv/bin/python -c "from app.services.strategy_lab_prompts import make_refine_strategy_direct_prompt; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/strategy_lab_prompts.py
git commit -m "feat(strategy-lab): add make_refine_strategy_direct_prompt for refine-with-instruction"
```

---

### Task 3: Add `refine_strategy_with_instruction()` to LLM Service

**Files:**
- Modify: `backend/app/services/strategy_lab_llm.py` (add function after `refine_strategy` at line 435)

**Interfaces:**
- Consumes: `make_refine_strategy_direct_prompt` from Task 2, `_chat`, `_extract_code_block`, `_validate_strategy_code`, `_fix_common_code_bugs`
- Produces: `refine_strategy_with_instruction(code, instruction, summary, worst_runs, model) → Tuple[Optional[str], Optional[str], Optional[str]]` returning `(modified_code, summary_text, error)`

- [ ] **Step 1: Add the new function**

Add after `refine_strategy` (after line 435):

```python
def refine_strategy_with_instruction(
    current_code: str,
    instruction: str,
    batch_summary: str,
    worst_runs_table: str,
    model: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Modify strategy code based on batch performance + user instruction.

    The LLM produces the COMPLETE modified file (not a diff). Returns
    (modified_code, change_summary, error).
    """
    from app.services.strategy_lab_prompts import make_refine_strategy_direct_prompt

    messages = make_refine_strategy_direct_prompt(
        current_code, instruction, batch_summary, worst_runs_table,
    )
    content, finish_reason, err = _chat(messages, model=model, max_tokens=16384, temperature=0.2)
    if err:
        return None, None, err

    # Extract the code block
    modified = _extract_code_block(content or "")
    if modified is None:
        if finish_reason == "length":
            detail = "response was truncated (finish_reason=length) before closing the ```python fence"
        else:
            detail = "response contained no ```python code block"
        return None, None, f"LLM {detail} (content length={len(content or '')})"

    # Extract the summary from the ## SUMMARY: marker
    summary_text = ""
    summary_match = re.search(r'## SUMMARY:\s*(.+?)(?:\n|$)', content or "")
    if summary_match:
        summary_text = summary_match.group(1).strip()

    # Validate syntax
    import ast
    try:
        ast.parse(modified)
    except SyntaxError as e:
        return None, None, f"Refine produced invalid syntax: {e}"

    # Validate strategy-specific anti-patterns
    warnings = _validate_strategy_code(modified)
    if warnings:
        logger.warning("Refined strategy code validation warnings:\n%s", "\n".join(warnings))

    # Auto-fix common bugs
    modified = _fix_common_code_bugs(modified)

    return modified, summary_text, None
```

- [ ] **Step 2: Verify syntax**

Run: `cd backend && ./venv/bin/python -c "from app.services.strategy_lab_llm import refine_strategy_with_instruction; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/strategy_lab_llm.py
git commit -m "feat(strategy-lab): add refine_strategy_with_instruction for complete-file refinement"
```

---

### Task 4: Modify the Refine Endpoint in the Router

**Files:**
- Modify: `backend/app/routers/strategy_lab.py` (lines 811-850)

**Interfaces:**
- Consumes: `refine_strategy_with_instruction` from Task 3, `get_batch_stats`, `list_batch_summaries`, `svc_get_session`, `svc_update_session`, `save_to_library` (existing)
- Produces: Modified `POST /sessions/{session_id}/batches/{batch_id}/refine` endpoint returning new `RefineStrategyResponse`

- [ ] **Step 1: Update the request/response models**

Replace lines 811-820:

```python
class RefineStrategyRequest(BaseModel):
    instruction: str = Field(default="", description="Optional user instruction for the AI to focus on")
    model: Optional[str] = None
    validation_runs: int = Field(default=10, ge=1, le=50)


class RefineStrategyResponse(BaseModel):
    code: str = ""
    summary: str = ""
    rationale: str = ""
    before_kpis: Dict[str, Any] = Field(default_factory=dict)
    after_kpis: Dict[str, Any] = Field(default_factory=dict)
    validation_log: List[str] = Field(default_factory=list)
    validation_status: str = "unknown"
    version: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
```

- [ ] **Step 2: Replace the endpoint implementation**

Replace lines 822-850 with:

```python
@router.post("/sessions/{session_id}/batches/{batch_id}/refine", response_model=RefineStrategyResponse)
def refine_strategy_after_batch(
    session_id: uuid.UUID,
    batch_id: uuid.UUID,
    body: RefineStrategyRequest,
    db: Session = Depends(get_db),
):
    """LLM proposes a code change based on the worst-performing runs of a batch + user instruction.

    Uses the complete-file approach (not diff) — generates modified code, validates
    with backtest runs, and auto-saves to library.
    """
    from app.services.strategy_lab_experiments import list_experiments, get_batch_stats, list_batch_summaries
    from app.services.strategy_lab_llm import refine_strategy_with_instruction
    from app.services.strategy_lab_session import update_session as svc_update_session

    sess = svc_get_session(db, session_id)
    if sess is None or not sess.code_text:
        raise HTTPException(status_code=400, detail="session has no code_text")

    stats = get_batch_stats(db, batch_id)
    if not stats["worst_3"]:
        raise HTTPException(status_code=400, detail="no completed runs in batch")

    summaries = list_batch_summaries(db, session_id=session_id, batch_id=batch_id)
    summary_text = summaries[0].summary_text if summaries else ""
    worst_table = json.dumps(stats["worst_3"], indent=2, default=str)

    # Compute before_kpis from batch stats
    # get_batch_stats returns: mean_sharpe, best_sharpe, top_3, worst_3, n_total, n_completed, n_failed
    # We compute aggregate KPIs from the top_3 and worst_3 runs
    all_scored = (stats.get("top_3") or []) + (stats.get("worst_3") or [])
    if all_scored:
        rets = [r.get("kpis", {}).get("total_return_pct", 0) or 0 for r in all_scored]
        shs = [r.get("kpis", {}).get("sharpe_ratio", 0) or 0 for r in all_scored]
        wrs = [r.get("kpis", {}).get("win_rate", 0) or 0 for r in all_scored]
        trs = [r.get("kpis", {}).get("total_trades", 0) or 0 for r in all_scored]
        dds = [r.get("kpis", {}).get("max_drawdown_pct", 0) or 0 for r in all_scored]
        before_kpis = {
            "total_return_pct": sum(rets) / len(rets) if rets else None,
            "sharpe_ratio": sum(shs) / len(shs) if shs else None,
            "win_rate": sum(wrs) / len(wrs) if wrs else None,
            "total_trades": sum(trs) / len(trs) if trs else None,
            "max_drawdown_pct": sum(dds) / len(dds) if dds else None,
        }
    else:
        before_kpis = {}

    # Call LLM to generate modified code
    modified_code, change_summary, err = refine_strategy_with_instruction(
        sess.code_text, body.instruction, summary_text, worst_table,
        model=body.model,
    )
    if err or modified_code is None:
        logger.error("Refine strategy failed: %s", err)
        return RefineStrategyResponse(
            code="", summary="", rationale="",
            before_kpis=before_kpis, after_kpis={},
            validation_log=[], validation_status="failed",
            error=err or "LLM returned no code",
        )

    # Run a single validation backtest using the orchestrator's _run_one
    validation_log = []
    validation_status = "passed"
    after_kpis = {}
    try:
        from app.services.strategy_lab_orchestrator import _run_one
        from datetime import datetime

        # Parse date range from the original batch
        batch_experiments = list_experiments(db, session_id, batch_id=batch_id)
        start_dates = [e.start_date for e in batch_experiments if e.start_date and e.status == "completed"]
        if start_dates:
            min_date = min(start_dates).isoformat() if hasattr(min(start_dates), 'isoformat') else str(min(start_dates))
            max_date = max(start_dates).isoformat() if hasattr(max(start_dates), 'isoformat') else str(max(start_dates))
        else:
            min_date = "2020-01-01"
            max_date = "2024-01-01"

        # Run a single validation backtest with the median start date
        import random
        val_start_dates = sorted(set(start_dates)) if start_dates else [min_date]
        median_date = val_start_dates[len(val_start_dates) // 2] if val_start_dates else min_date

        result = _run_one(
            code_text=modified_code,
            session_id=str(session_id),
            as_of=str(median_date)[:10],
            end_date=str(max_date)[:10],
            run_index=999,
        )
        if result["status"] == "completed" and result.get("kpis"):
            k = result["kpis"]
            after_kpis = {
                "total_return_pct": k.get("total_return_pct", 0),
                "sharpe_ratio": k.get("sharpe_ratio", 0),
                "win_rate": k.get("win_rate", 0),
                "total_trades": k.get("total_trades", 0),
                "max_drawdown_pct": k.get("max_drawdown_pct", 0),
            }
            validation_log.append(f"Validation backtest: OK (return={k.get('total_return_pct', 0):.1f}%)")
        else:
            validation_log.append(f"Validation backtest: FAILED ({result.get('error_message', 'unknown')})")
            validation_status = "partial"

    except Exception as e:
        logger.warning("Validation backtest failed: %s", e)
        validation_log.append(f"Validation error: {e}")
        validation_status = "partial"

    # Auto-save to library using save_strategy
    version_info = None
    try:
        from app.services.strategy_lab_library import save_strategy
        meta = save_strategy(
            name=f"{sess.name or 'strategy'}-v{1}",
            code=modified_code,
            prompt=sess.prompt or "",
            plan=sess.plan_text or "",
            kpis=after_kpis or None,
            change_description=change_summary or summary_text[:100] if summary_text else "AI-refined strategy",
            model_id=sess.model_id,
            session_id=str(session_id),
        )
        version_info = {
            "version": meta["version"],
            "strategy_name": meta["strategy_name"],
            "change_description": meta["change_description"],
        }
    except Exception as e:
        logger.warning("Auto-save to library failed: %s", e)

    # Save code to session
    svc_update_session(db, session_id, code_text=modified_code)

    return RefineStrategyResponse(
        code=modified_code,
        summary=change_summary or "Code updated",
        rationale=summary_text[:300] + "..." if summary_text and len(summary_text) > 300 else (summary_text or ""),
        before_kpis=before_kpis,
        after_kpis=after_kpis,
        validation_log=validation_log,
        validation_status=validation_status,
        version=version_info,
    )
```

- [ ] **Step 3: Verify syntax**

Run: `cd backend && ./venv/bin/python -c "from app.routers.strategy_lab import router; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/strategy_lab.py
git commit -m "feat(strategy-lab): replace diff-based refine with complete-file + validation + auto-save"
```

---

### Task 5: Update Frontend API Client

**Files:**
- Modify: `frontend/src/lib/strategyLab.ts` (line 268-269)

**Interfaces:**
- Consumes: Updated `RefineStrategyResponse` from Task 1
- Produces: Updated `refineAfterBatch` call that passes `instruction` field

- [ ] **Step 1: Update the `refineAfterBatch` method**

Replace lines 268-269:

```typescript
  refineAfterBatch: (id: string, batchId: string, body: { model?: string; instruction?: string } = {}) =>
    postJson<RefineStrategyResponse>(`${base}/sessions/${id}/batches/${batchId}/refine`, body),
```

- [ ] **Step 2: Verify the file compiles**

Run: `cd frontend && npx tsc --noEmit src/lib/strategyLab.ts 2>&1 | head -20`
Expected: No type errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/strategyLab.ts
git commit -m "feat(strategy-lab): update refineAfterBatch to accept instruction field"
```

---

### Task 6: New Refine Flow UI in StepBacktest.tsx

**Files:**
- Modify: `frontend/src/pages/StrategyLab/StepBacktest.tsx`

**Interfaces:**
- Consumes: `refineAfterBatch` from Task 5, `saveToLibrary`, `startExperiments`
- Produces: Multi-step refine flow with pre-refine input, KPI comparison, follow-up, auto-save, re-run prompt

- [ ] **Step 1: Add state variables for the new refine flow**

Add after line 31 (`const [refine, setRefine] = useState<RefineStrategyResponse | null>(null);`):

```typescript
  const [refineInstruction, setRefineInstruction] = useState("");
  const [refineStep, setRefineStep] = useState<"idle" | "input" | "review" | "done">("idle");
  const [refineFollowUp, setRefineFollowUp] = useState("");
```

- [ ] **Step 2: Update the refine mutation to pass instruction**

Replace lines 139-142:

```typescript
  const refineMut = useMutation({
    mutationFn: (instruction: string) =>
      strategyLabApi.refineAfterBatch(session.id, batchId!, {
        model: session.model_id,
        instruction,
      }),
    onSuccess: (r) => {
      setRefine(r);
      setRefineStep("review");
    },
  });
```

- [ ] **Step 3: Replace the `PostBatchActions` component's refine section**

Replace the `PostBatchActions` function entirely (lines 617-718) with the new version that includes the multi-step refine flow. The key changes:

1. **Pre-refine input step**: When user clicks "Refine strategy", show a text input for what to focus on
2. **Review step**: Show KPI comparison table + AI rationale + follow-up input
3. **Done step**: Show "Change applied and saved" + "Re-run with same dates" button

```typescript
function PostBatchActions(props: {
  onSummarize: () => void; isSummarizing: boolean;
  onRefine: () => void; isRefining: boolean;
  onAnotherBatch: () => void;
  summary: SummarizeResponse | null;
  refine: RefineStrategyResponse | null;
  onAcceptRefine: (diff: string) => void; onRejectRefine: () => void;
  isApplying: boolean;
  applyError: string | null;
  // NEW props
  refineInstruction: string;
  setRefineInstruction: (v: string) => void;
  refineStep: "idle" | "input" | "review" | "done";
  setRefineStep: (v: "idle" | "input" | "review" | "done") => void;
  refineFollowUp: string;
  setRefineFollowUp: (v: string) => void;
  onRefineWithInstruction: (instruction: string) => void;
  isRefining: boolean;
  onReRun: () => void;
}) {
  return (
    <div style={{ maxWidth: 1280, marginTop: 32, display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Action buttons row */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span className="slab-eyebrow">// After batch</span>
        <div style={{ flex: 1 }} />
        <button type="button" onClick={props.onSummarize} disabled={props.isSummarizing} className="slab-btn">
          <Sparkles size={11} />
          {props.isSummarizing ? "Analyzing…" : "AI summary"}
        </button>
        <button
          type="button"
          onClick={() => props.setRefineStep("input")}
          disabled={props.refineStep === "review" || props.refineStep === "done"}
          className="slab-btn"
        >
          <Sparkles size={11} />
          Refine strategy
        </button>
        <button type="button" onClick={props.onAnotherBatch} className="slab-btn slab-btn--ghost">
          <RotateCcw size={11} />
          New batch
        </button>
      </div>

      <AnimatePresence>
        {/* AI Summary */}
        {props.summary && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="slab-panel">
            <div className="slab-panel__head">
              <span className="slab-eyebrow slab-eyebrow--gold">
                <FileText size={11} style={{ verticalAlign: "middle", marginRight: 6 }} />
                AI summary
              </span>
              <span className="slab-mono slab-mono--xs slab-mono--dim">3 paragraphs</span>
            </div>
            <div className="slab-panel__body">
              <p className="slab-prose" style={{ whiteSpace: "pre-wrap" }}>{props.summary.summary_text}</p>
            </div>
          </motion.div>
        )}

        {/* Step 1: Pre-refine input */}
        {props.refineStep === "input" && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="slab-panel">
            <div className="slab-panel__head">
              <span className="slab-eyebrow slab-eyebrow--gold">// Refine strategy</span>
              <span className="slab-mono slab-mono--xs slab-mono--dim">tell the AI what to focus on</span>
            </div>
            <div className="slab-panel__body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <textarea
                value={props.refineInstruction}
                onChange={(e) => props.setRefineInstruction(e.target.value)}
                rows={3}
                placeholder="e.g. reduce max drawdown, focus on improving Sharpe ratio, or leave empty for AI to decide"
                className="slab-textarea"
              />
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  onClick={() => props.onRefineWithInstruction(props.refineInstruction)}
                  disabled={props.isRefining}
                  className="slab-btn slab-btn--primary"
                >
                  {props.isRefining ? "Generating changes…" : "Generate changes"}
                </button>
                <button type="button" onClick={() => props.setRefineStep("idle")} className="slab-btn slab-btn--ghost">
                  Cancel
                </button>
              </div>
            </div>
          </motion.div>
        )}

        {/* Step 2: Review panel */}
        {props.refine && props.refineStep === "review" && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="slab-panel">
            <div className="slab-panel__head">
              <span className="slab-eyebrow slab-eyebrow--gold">// AI suggested changes</span>
              <span className="slab-mono slab-mono--xs slab-mono--dim">
                {props.refine.validation_status === "passed" ? "✓ validated" : props.refine.validation_status === "partial" ? "⚠ partial" : "✗ failed"}
              </span>
            </div>
            <div className="slab-panel__body" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {/* Rationale */}
              {props.refine.rationale && (
                <p className="slab-prose" style={{ whiteSpace: "pre-wrap" }}>{props.refine.rationale}</p>
              )}

              {/* KPI Comparison Table */}
              {props.refine.before_kpis && props.refine.after_kpis && Object.keys(props.refine.before_kpis).length > 0 && (
                <div style={{ overflowX: "auto" }}>
                  <table className="slab-table" style={{ minWidth: 400 }}>
                    <thead>
                      <tr>
                        <th>Metric</th>
                        <th className="slab-table__num">Before</th>
                        <th className="slab-table__num">After</th>
                        <th className="slab-table__num">Δ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {["total_return_pct", "sharpe_ratio", "max_drawdown_pct", "win_rate", "total_trades"].map((key) => {
                        const before = props.refine!.before_kpis[key];
                        const after = props.refine!.after_kpis[key];
                        if (before == null && after == null) return null;
                        const b = typeof before === "number" ? before : 0;
                        const a = typeof after === "number" ? after : 0;
                        const delta = a - b;
                        const isPct = key.includes("_pct") || key === "win_rate";
                        const fmt = (v: number) => isPct ? `${v >= 0 ? "+" : ""}${v.toFixed(1)}%` : v.toFixed(2);
                        const label = key.replace(/_pct$/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
                        return (
                          <tr key={key}>
                            <td>{label}</td>
                            <td className="slab-table__num">{fmt(b)}</td>
                            <td className="slab-table__num" style={{ color: a >= b ? "var(--slab-terminal)" : "var(--slab-rose)" }}>{fmt(a)}</td>
                            <td className="slab-table__num" style={{ color: delta >= 0 ? "var(--slab-terminal)" : "var(--slab-rose)" }}>
                              {delta >= 0 ? "+" : ""}{fmt(delta)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Change summary */}
              {props.refine.summary && (
                <div style={{ padding: "10px 14px", background: "var(--slab-terminal-glow)", borderRadius: 6 }}>
                  <span className="slab-mono slab-mono--sm" style={{ color: "var(--slab-terminal)" }}>
                    {props.refine.summary}
                  </span>
                </div>
              )}

              {/* Validation log */}
              {props.refine.validation_log.length > 0 && (
                <div>
                  {props.refine.validation_log.map((entry, i) => (
                    <div key={i} className="slab-mono slab-mono--xs" style={{
                      color: entry.includes("FAILED") ? "var(--slab-rose)" : "var(--slab-paper-faint)",
                      padding: "2px 0",
                    }}>
                      {entry}
                    </div>
                  ))}
                </div>
              )}

              {/* Follow-up input */}
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input
                  type="text"
                  value={props.refineFollowUp}
                  onChange={(e) => props.setRefineFollowUp(e.target.value)}
                  placeholder="Follow-up: make the trailing stop tighter..."
                  className="slab-input"
                  style={{ flex: 1, fontSize: 13 }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && props.refineFollowUp.trim()) {
                      props.onRefineWithInstruction(props.refineFollowUp);
                      props.setRefineFollowUp("");
                    }
                  }}
                />
                <button
                  type="button"
                  onClick={() => {
                    props.onRefineWithInstruction(props.refineFollowUp);
                    props.setRefineFollowUp("");
                  }}
                  disabled={!props.refineFollowUp.trim() || props.isRefining}
                  className="slab-btn slab-btn--sm"
                >
                  Refine
                </button>
              </div>

              {/* Accept / Reject */}
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  onClick={() => {
                    props.onAcceptRefine(props.refine!.code);
                    props.setRefineStep("done");
                  }}
                  disabled={props.isApplying}
                  className="slab-btn slab-btn--primary"
                >
                  {props.isApplying ? "Applying…" : "Accept & Save"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    props.onRejectRefine();
                    props.setRefineStep("idle");
                  }}
                  className="slab-btn slab-btn--ghost"
                >
                  Reject
                </button>
              </div>

              {props.applyError && (
                <div className="slab-mono slab-mono--sm slab-mono--rose" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <AlertCircle size={12} />
                  {props.applyError}
                </div>
              )}
            </div>
          </motion.div>
        )}

        {/* Step 3: Done — change applied */}
        {props.refineStep === "done" && props.refine && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="slab-panel">
            <div className="slab-panel__head">
              <span className="slab-eyebrow slab-eyebrow--gold">// Change applied</span>
            </div>
            <div className="slab-panel__body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <CheckCircle size={16} style={{ color: "var(--slab-terminal)" }} />
                <span className="slab-mono slab-mono--sm" style={{ color: "var(--slab-terminal)" }}>
                  {props.refine.version
                    ? `Change applied and saved as "${props.refine.version.strategy_name}"`
                    : "Change applied"}
                </span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button type="button" onClick={props.onReRun} className="slab-btn slab-btn--terminal">
                  <RotateCcw size={11} />
                  Re-run with same dates
                </button>
                <button type="button" onClick={() => props.setRefineStep("idle")} className="slab-btn slab-btn--ghost">
                  Dismiss
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
```

- [ ] **Step 3: Update the `PostBatchActions` usage in the parent component**

Replace the existing `PostBatchActions` call (around line 299-313) with the new version that passes the new props:

```typescript
                {isDone && stats && stats.n_completed > 0 && (
                  <>
                    <PostBatchActions
                      onSummarize={() => summarize.mutate()}
                      isSummarizing={summarize.isPending}
                      onRefine={() => refineMut.mutate()}
                      isRefining={refineMut.isPending}
                      onAnotherBatch={() => { setBatchId(null); setPreviousStartDates(null); }}
                      summary={summary}
                      refine={refine}
                      onAcceptRefine={(d) => apply.mutate(d)}
                      onRejectRefine={() => setRefine(null)}
                      isApplying={apply.isPending}
                      applyError={applyError}
                      // NEW props
                      refineInstruction={refineInstruction}
                      setRefineInstruction={setRefineInstruction}
                      refineStep={refineStep}
                      setRefineStep={setRefineStep}
                      refineFollowUp={refineFollowUp}
                      setRefineFollowUp={setRefineFollowUp}
                      onRefineWithInstruction={(instruction) => refineMut.mutate(instruction)}
                      isRefining={refineMut.isPending}
                      onReRun={() => {
                        // Start a new batch with the same start dates
                        setBatchId(null);
                        // The previousStartDates are already saved from the last batch
                        setTimeout(() => start.mutate(), 100);
                      }}
                    />
                    <ChatPanel
                      sessionId={session.id}
                      defaultModelId={session.model_id}
                    />
                  </>
                )}
```

- [ ] **Step 4: Add missing import for `CheckCircle`**

Add `CheckCircle` to the lucide-react import at line 4:

```typescript
import { Play, Sparkles, RotateCcw, AlertCircle, FileText, ArrowUpDown, ArrowUp, ArrowDown, TrendingUp, CheckCircle } from "lucide-react";
```

- [ ] **Step 5: Verify the file compiles**

Run: `cd frontend && npx tsc --noEmit src/pages/StrategyLab/StepBacktest.tsx 2>&1 | head -30`
Expected: No type errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/StrategyLab/StepBacktest.tsx
git commit -m "feat(strategy-lab): replace DiffReview with multi-step refine flow (pre-input, KPI comparison, follow-up, auto-save)"
```

---

### Task 7: Auto-Save + Re-Run in ChatPanel

**Files:**
- Modify: `frontend/src/components/strategy-lab/ChatPanel.tsx`

**Interfaces:**
- Consumes: `saveToLibrary` from `strategyLabApi`, `startExperiments` (via parent)
- Produces: Auto-save to library after apply, re-run button

- [ ] **Step 1: Add auto-save after successful applyChange**

In the `applyChange` mutation's `onSuccess` handler (line 83-98), add auto-save to library after the status message:

```typescript
    onSuccess: (r) => {
      setApplyingInstruction(null);
      setApplyTimer(0);

      // Auto-save to library
      const changeDesc = lastCodeChangeInstruction || "AI-suggested improvement";
      saveToLib.mutate({
        name: `strategy-${sessionId.slice(0, 8)}-v${Date.now()}`,
        change_description: changeDesc,
      });

      const statusMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: r.validation_status === "passed"
          ? `✅ Change applied and verified with backtest runs.`
          : `⚠️ Change applied but some validation runs failed (${r.validation_status}).`,
        model_id: "system",
        critique_of: undefined,
        code_change_instruction: undefined,
        created_at: new Date().toISOString(),
      };
      setMessages(prev => [...prev, statusMsg]);
    },
```

Note: We need to capture the `lastCodeChangeInstruction` from the message that was applied. Add a ref to track it:

```typescript
  const lastCodeChangeInstruction = useRef<string | null>(null);
```

And update the `handleSend` function to set it:

```typescript
    if (lastBotWithChange && approvalKeywords.some(k => msg.toLowerCase().includes(k))) {
      setApplyingInstruction(lastBotWithChange.code_change_instruction!);
      lastCodeChangeInstruction.current = lastBotWithChange.code_change_instruction!;
      applyChange.mutate(lastBotWithChange.code_change_instruction!);
    }
```

And update the "Apply change" button onClick:

```typescript
                      onClick={() => {
                        setApplyingInstruction(msg.code_change_instruction!);
                        lastCodeChangeInstruction.current = msg.code_change_instruction!;
                        applyChange.mutate(msg.code_change_instruction!);
                      }}
```

- [ ] **Step 2: Add re-run button after successful apply**

After the status message, add a "Re-run with same dates" button. This requires knowing the session ID and having access to the batch context. Since ChatPanel is used in both StepCode and StepBacktest, we need to handle both cases.

Add a new prop for the re-run callback:

```typescript
interface ChatPanelProps {
  sessionId: string;
  defaultModelId: string;
  onReRun?: () => void;  // NEW: callback for re-run
}
```

And after the status message, if `onReRun` is provided, show the button:

```typescript
      {onReRun && pendingSave && (
        <div style={{ display: "flex", gap: 8, padding: "8px 0", borderTop: "1px solid var(--slab-rule)", marginTop: 8 }}>
          <button
            type="button"
            onClick={onReRun}
            className="slab-btn slab-btn--sm slab-btn--terminal"
          >
            <RotateCcw size={10} /> Re-run with same dates
          </button>
          <button
            type="button"
            onClick={() => setPendingSave(false)}
            className="slab-btn slab-btn--sm slab-btn--ghost"
          >
            Dismiss
          </button>
        </div>
      )}
```

- [ ] **Step 3: Add `RotateCcw` to imports**

Add `RotateCcw` to the lucide-react import:

```typescript
import { Send, Bot, User, RefreshCw, AlertCircle, MessageSquare, Wand2, Save, RotateCcw } from "lucide-react";
```

- [ ] **Step 4: Update ChatPanel usage in StepBacktest.tsx**

Pass the `onReRun` callback:

```typescript
                    <ChatPanel
                      sessionId={session.id}
                      defaultModelId={session.model_id}
                      onReRun={() => {
                        setBatchId(null);
                        setTimeout(() => start.mutate(), 100);
                      }}
                    />
```

- [ ] **Step 5: Verify the file compiles**

Run: `cd frontend && npx tsc --noEmit src/components/strategy-lab/ChatPanel.tsx 2>&1 | head -20`
Expected: No type errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/strategy-lab/ChatPanel.tsx
git add frontend/src/pages/StrategyLab/StepBacktest.tsx
git commit -m "feat(strategy-lab): auto-save to library after chat apply + re-run button"
```

---

### Task 8: Deprecate Old Files

**Files:**
- Deprecate: `backend/app/services/strategy_lab_diff.py`
- Deprecate: `frontend/src/components/strategy-lab/DiffReview.tsx`

- [ ] **Step 1: Add deprecation notice to `strategy_lab_diff.py`**

Add at the top of the file:

```python
"""
DEPRECATED: This module is no longer used by the refine flow.
The refine flow now uses complete-file replacement (refine_code_direct)
instead of unified diffs. Kept for reference only.
"""
```

- [ ] **Step 2: Add deprecation notice to `DiffReview.tsx`**

Add at the top of the file:

```typescript
/**
 * DEPRECATED: This component is no longer used by the refine flow.
 * The refine flow now shows KPI comparison tables instead of diffs.
 * Kept for reference only.
 */
```

- [ ] **Step 3: Verify no remaining imports of deprecated files**

Run:
```bash
grep -rn "strategy_lab_diff" backend/app/ --include="*.py" | grep -v "DEPRECATED"
grep -rn "DiffReview" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v "DEPRECATED"
```
Expected: No results (or only the deprecation notices themselves)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/strategy_lab_diff.py
git add frontend/src/components/strategy-lab/DiffReview.tsx
git commit -m "chore(strategy-lab): deprecate diff-based refine files"
```

---

### Task 9: Verify the Full Flow

**Files:** None — manual verification

- [ ] **Step 1: Start the backend**

```bash
cd backend && ./venv/bin/python -m app.main &
sleep 5
```

- [ ] **Step 2: Start the frontend**

```bash
cd frontend && npm run dev &
sleep 3
```

- [ ] **Step 3: Test the refine flow end-to-end**

1. Open the Strategy Lab in the browser
2. Create a session, generate a plan, generate code
3. Run a batch of experiments
4. After batch completes, click "Refine strategy"
5. Verify the pre-refine input appears
6. Enter an instruction and click "Generate changes"
7. Verify the KPI comparison table appears
8. Verify the follow-up input works
9. Click "Accept & Save"
10. Verify the "Re-run with same dates" button appears
11. Click it and verify a new batch starts with the same date range

- [ ] **Step 4: Test the ChatPanel auto-save flow**

1. In the ChatPanel, ask for a code change
2. Click "Apply change"
3. Verify the change is applied and auto-saved
4. Verify the "Re-run with same dates" button appears

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix(strategy-lab): address issues found during end-to-end testing"
```
