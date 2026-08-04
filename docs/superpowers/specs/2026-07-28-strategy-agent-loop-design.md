# AI Strategy Builder — Server-Side Agent Loop

**Date:** 2026-07-28
**Status:** Implemented

## Problem

The current AI Strategy Builder generates strategy code via a single LLM call, causing:
1. **502 Timeout**: Synchronous HTTP request times out if LLM takes >60s
2. **Poor Strategy Quality**: Single-shot generation without iteration produces weak strategies

## Solution

A server-side agent loop that runs as a background task and streams progress via SSE:

1. **Read Context** — Load template, learnings, reference strategies
2. **Generate** — LLM produces the 4 strategy functions + CONFIG
3. **Validate** — Syntax check, import check, anti-pattern scan
4. **Backtest** — Run single backtest window, collect KPIs
5. **Debug** — If validation/backtest fails, LLM fixes code (max 3×)
6. **Improve** — If KPIs are poor, LLM improves code (max 2×)
7. **Return** — Final code + KPIs + summary

## Architecture

### Backend

- `backend/app/services/strategy_agent.py` — Core agent loop with `StrategyAgent` class
  - `AgentSession` — Holds state for one session, async event queue
  - `StrategyAgent` — Main loop with step methods
  - Tools: `read_file`, `write_file`, `run_backtest_subprocess`, `_call_llm`
  - Reuses existing `strategy_lab_llm.py` for LLM calls

- `backend/app/routers/strategy_agent.py` — FastAPI endpoints
  - `POST /api/strategy-agent/generate` — Start session, returns session_id
  - `GET /api/strategy-agent/{session_id}/stream` — SSE event stream
  - `GET /api/strategy-agent/{session_id}/result` — Get final result

### Frontend

- `frontend/src/components/quantgen/AgentProgress.tsx` — Progress panel
  - SSE connection via EventSource
  - Timeline view with step-by-step status icons
  - Live log view with timestamped entries
  - KPI summary with color-coded tiles
  - Detailed KPI explanations

### SSE Event Types

| Event | Description |
|-------|-------------|
| `step` | Step lifecycle (running/done/failed/skipped) |
| `context` | Context loaded (template, learnings, references) |
| `llm_call` | LLM call started (phase, model, tokens) |
| `code_generated` | Code produced (size, functions, path) |
| `validation` | Validation results (imports, functions, anti-patterns) |
| `validation_warning` | Anti-pattern warning |
| `backtest_result` | Backtest KPIs (return, sharpe, drawdown, etc.) |
| `improvement` | Before/after KPI comparison |
| `error_fatal` | Unrecoverable error |
| `result` | Final result (code + KPIs + summary) |

## Files Created

- `backend/app/services/strategy_agent.py` — Core agent loop
- `backend/app/routers/strategy_agent.py` — FastAPI router
- `frontend/src/components/quantgen/AgentProgress.tsx` — Progress panel

## Files Modified

- `backend/app/main.py` — Registered strategy_agent router
- `frontend/src/pages/QuantGen/Builder.tsx` — Added "Generate with Agent" button and progress panel
- `frontend/src/components/quantgen/index.ts` — Exported AgentProgress

## Key Design Decisions

1. **Tool-based, not function-calling**: Agent outputs structured commands parsed by backend. Works with any model.
2. **Progress streaming via SSE**: Every step emits detailed events. User sees exactly what's happening.
3. **Reuses existing infrastructure**: Template, engine, learnings, and validation from Strategy Lab.
4. **File system isolation**: Generated strategies go to `strategies/_generated/{session_id}/`.
5. **Same model**: Uses deepseek-v4-flash:cloud. Improvement comes from agent loop architecture.
