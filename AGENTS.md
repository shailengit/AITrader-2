# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

TradeCraft is a unified trading platform combining three tools:
1. **Sector Rotation Scanner** - Analyze sector ETF momentum and find leading stocks
2. **AI Stock Screener** - Multi-agent technical and fundamental stock screening
3. **QuantGen Strategy Builder** - AI-powered quantitative strategy generation with VectorBT

## Architecture

```
TradeCraft/
├── backend/                 # FastAPI Python backend
│   ├── app/
│   │   ├── main.py          # FastAPI entry point with CORS, security headers
│   │   ├── routers/         # API endpoints
│   │   │   ├── sectors.py    # Sector rotation: /api/sectors, /api/stocks/:sector
│   │   │   ├── screener.py  # AI screener: /api/screener/scan, /api/screener/parse-filters, /api/screener/status/:id
│   │   │   ├── quantgen.py  # Strategy builder: /api/generate, /api/run, /api/optimize
│   │   │   └── health.py     # Health check: /api/health, /api/db-status
│   │   ├── services/        # Business logic
│   │   │   ├── agno_screener.py  # Multi-agent AI screener (Dormant Giant, Quant Strategy)
│   │   │   └── data_service.py  # PostgreSQL data access (replaces yfinance)
│   │   └── db/
│   │       └── database.py  # SQLAlchemy connection pool, sector ETF mappings
│   └── requirements.txt
├── frontend/                # React + TypeScript + Tailwind CSS
│   ├── src/
│   │   ├── App.tsx          # React Router with tabs
│   │   ├── components/layout/Layout.tsx  # Sidebar navigation
│   │   ├── pages/
│   │   │   ├── Landing.tsx        # Dashboard with three app cards
│   │   │   ├── SectorRotation.tsx # Sector ETF analysis with Recharts
│   │   │   ├── StockScreener.tsx  # AI screener with mode selection
│   │   │   └── QuantGen.tsx       # Strategy builder with Monaco Editor
│   │   └── styles/index.css # Tailwind + dark theme CSS variables
│   ├── vite.config.ts       # Vite with API proxy to FastAPI
│   └── package.json
└── README.md
```

## Commands

### Backend (from `backend/` directory)

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Run development server
python -m app.main
# or
uvicorn app.main:app --reload --port 8000
```

**IMPORTANT:** When running any Python script, always use the virtual environment's Python interpreter from the `backend/` folder:
```bash
cd backend && ./venv/bin/python <script_path>
```

### Frontend (from `frontend/` directory)

```bash
# Install dependencies
npm install

# Run development server
npm run dev
```

### Database

PostgreSQL database `sp1500_1d` must be running with:
- Individual stock tables (e.g., `aapl`, `msft`) with columns: `Date`, `Open`, `High`, `Low`, `Close`, `Volume`
- `stock_metadata` table with sector info
- `stock_financials_quarterly` table with EPS data

Environment variables (defaults in `database.py`):
- `DB_USER` (default: postgres)
- `DB_PASSWORD` (default: sarina00)
- `DB_HOST` (default: 127.0.0.1)
- `DB_PORT` (default: 5431)
- `DB_NAME` (default: sp1500_1d)

## Key Patterns

### AI Screener Modes

Two screening modes with optional AI multi-agent analysis:

1. **Dormant Giant** (`dormant_giant`): Bollinger squeeze + OBV accumulation + EPS acceleration
2. **Quant Strategy** (`quant_strategy`): TA indicators + fundamental health + optional backtesting

Set `use_ai=true` for Agno multi-agent team analysis with natural language reports.

### Quant Strategy Filter System

The Quant Strategy screener applies structured filters deterministically to the full S&P 1500 universe. There is **no** `POST /api/screener/parse-filters` endpoint and no `parse_quant_filters()`/`apply_quant_filters()` functions — the filter system is driven directly by the `filters` object the frontend sends in the scan request.

**Scan flow:**
1. The frontend builds a `filters` object (`{ indicator_filters: [...] }`) from the user's filter controls.
2. `POST /api/screener/scan` (mode `quant_strategy`) starts a scan; the worker (`technical_screener` in `agno_screener.py`) computes indicators per ticker and applies the filters.
3. Results stream via `/api/screener/stream/{scan_id}` and are fetched via `/api/screener/results/{scan_id}`.

**Key functions:**
- `backend/app/services/agno_screener.py:technical_screener()` — parallel worker that computes indicators and applies `filters`
- `backend/app/routers/screener.py:scan()` — FastAPI endpoint that starts the scan

### Database Access Pattern

```python
from app.db import database

# Use the connection pool
with database.engine.connect() as conn:
    result = conn.execute(text("SELECT * FROM table"))
```

### Frontend API Calls

Frontend proxies `/api/*` to backend via Vite config. Use relative paths:

```typescript
const res = await fetch('/api/sectors')
```

### True Walk-Forward Optimization (True WFO)

**Purpose:** Simulates real trading conditions by optimizing on past data only, then trading just one day at a time.

**How It Works:**
1. For each rolling window: optimize parameters on training data (past N days)
2. Pick the best parameters from that training window
3. Generate signal from training window's last day → trade the NEXT day only
4. Position persists across windows (like real trading)
5. Repeat with window shifted forward by 1 day

**Key Differences from Simple WFO:**
- Tests one day at a time vs. multi-day test periods
- Position state carries over between windows
- No future data used in decision-making (avoids curve-fitting)

**Implementation:** `backend/app/services/continuous_wfo.py` — uses `PortfolioTracker` to maintain position state across windows.

## Available Skills

The following Codex skills are used in this project:
- **cli-anything-tradecraft** - General-purpose CLI automation and task execution
- **playwright-cli** - Browser automation, UI testing, and screenshot capture

## Original Repositories

This unified platform combines code from:
- **StockScreener_2** - Multi-agent AI stock screener with Agno/Ollama
- **Sector-Rotation-Scanner** - React/TypeScript sector analysis dashboard
- **QuantGen** - FastAPI/React quantitative strategy builder with VectorBT

## Sector Rotation to QuantGen Export Flow

When a user exports stocks from the Sector Rotation Scanner to the QuantGen Builder, the following parameters are passed via URL query string:
- `tickers` — comma-separated list of filtered stock tickers
- `from_date` — the "As Of" date selected in the Sector Rotation Scanner

The Builder page (`frontend/src/pages/QuantGen/Builder.tsx`) parses these parameters:
- `from_date` becomes the `start_date` for strategy generation and WFO optimization
- `end_date` is fetched from the backend via `/api/latest-date` and represents the latest available trading date in the PostgreSQL database
- Both dates are editable in the Optimization Config panel (`OptimizationConfig.tsx`)

**Key files:**
- `frontend/src/pages/SectorRotation.tsx:163-166` — builds export URL
- `frontend/src/pages/QuantGen/Builder.tsx:78-83` — parses URL params and applies dates
- `frontend/src/components/quantgen/OptimizationConfig.tsx` — date picker UI
- `backend/app/routers/quantgen.py` — `/api/latest-date` endpoint queries `SELECT MAX("Date") FROM aapl`

## Design System Rules
- Max content width: 1280px, centered with auto margins
- Base spacing unit: 8px (use multiples: 8, 16, 24, 32, 48, 64)
- Typography scale: 14/16/18/20/24/32/40/48px
- Grid: 12-column, 24px gutters
- Never use raw pixel values — use spacing tokens or Tailwind classes only
- All pages must look intentional at 1440px+ (no orphaned whitespace)

## Frontend Requirements
- Target display: MacBook Pro 16" with 4K display (3456×2234 native, 
- typically rendered at 1728×1117 in the browser at 2x DPR).
- Design for 1440px–1728px as the primary breakpoint.
- Use shadcn/ui components exclusively. Do not invent custom components when a shadcn equivalent exists.

## UI/UX Standards
- Framework: React + Tailwind CSS + shadcn/ui
- Target viewport: 1440px–1728px primary, must also work at 768px and 1280px
- Content max-width: 1280px centered
- Spacing: 8px base unit, Tailwind spacing scale only (no arbitrary values)
- Layout: CSS Grid preferred over flexbox for page-level layouts
- No layout should have unintentional empty space at 1440px+
- Sidebar widths: 240px (nav), 320px (contextual panels)
- All modals/dialogs: max-width 560px or 720px, never full-width

## Component rules
- Use shadcn/ui before building custom components
- Cards: always use consistent padding (p-6), border-radius (rounded-xl)
- Forms: max-width 480px unless explicitly a wide layout
- Tables: always implement horizontal scroll on mobile

## Troubleshooting Learnings (April 2026)

### Tailwind Spacing Classes Not Applied

**Problem:** Tailwind spacing utilities (`mb-8`, `gap-12`, `py-24`, etc.) were not being applied to components even though:
- TypeScript compilation succeeded
- Dev server was running
- File changes were being detected (extreme visual indicators like red borders worked)

**Root Cause:** Unknown - possibly Tailwind v4 + Vite integration issue where certain classes get tree-shaken or not processed correctly in development mode.

**Solution:** Use inline styles for spacing when Tailwind classes fail:
```tsx
// Instead of:
<div className="mb-24">

// Use:
<div style={{ marginBottom: '96px' }}>
```

**Verification Method:**
1. Add extreme visual indicators (red border, blue background) to verify code changes are being served
2. If indicators appear but Tailwind classes don't → use inline styles
3. Check browser DevTools computed styles to confirm what's actually applied

**Lesson:** When spacing/layout changes don't appear despite correct code:
- Don't assume the code is wrong
- Verify the file is actually being served (extreme test styles)
- Fall back to inline styles for reliable spacing
- This project's Tailwind v4 setup has quirks with spacing utilities in dev mode

### True WFO Window Calculation Bug

**Problem:** True WFO was generating only 1 window when using Ratio split method, resulting in no trades and a tiny date range (e.g., 2022-10-18 to 2022-10-20 instead of 2020-01-01 to 2024-01-01).

**Root Cause:** `calculate_window_configs()` used `step = test_len` (438 days with 0.7 ratio) for all modes. With ratio=0.7, train=1022 days, only `(1461-1022)//438 = 1` window fits. True WFO should step 1 day at a time to trade each day.

**Fix:** Added `is_true_wfo` parameter to `calculate_window_configs()` that forces `step=1`:
```python
# In continuous_wfo.py
window_configs = calculate_window_configs(
    start_date, end_date, n_windows,
    wfo_conf.get("type", "rolling"), wfo_conf,
    is_true_wfo=True  # Forces step=1
)
```

**Files Modified:**
- `backend/app/services/true_wfo_implementation.py` - Added `is_true_wfo` parameter
- `backend/app/services/continuous_wfo.py` - Pass `is_true_wfo=True`

**Lesson:** True WFO must always step 1 day at a time regardless of split method. The step calculation that works for standard WFO (step = test_len) breaks True WFO's continuous trading model.

### VectorBT Optimization Requires Broadcasting (vectorbt 1.0.0)

**Problem:** Strategy backtest works fine, but optimization fails with "Operands are not aligned" / "Can only compare identically-labeled DataFrame objects".

**Root Cause:** This project uses **vectorbt 1.0.0**. The `.vbt.gt()/.lt()` accessors, `vbt.combine_logic()`, and the `jitted=True` kwarg **DO NOT EXIST** in this version. During optimization, parameterized indicators become DataFrames with MultiIndex columns while non-parameterized operands stay Series, so comparing them directly fails.

**Solution:** Use VBT indicators (`.run()`) and broadcast every non-parameterized operand to the parameterized one's shape with a `_bc()` helper, then use plain operators:

```python
def _bc(s, ref):
    # Broadcast s to match ref's shape/columns for safe &/| with MultiIndex columns.
    if isinstance(s, pd.Series) and isinstance(ref, (pd.DataFrame, pd.Series)) and hasattr(ref, 'columns') and ref.columns.nlevels > 1:
        return pd.DataFrame(np.broadcast_to(s.values[:, None], ref.shape), index=ref.index, columns=ref.columns)
    if isinstance(s, pd.DataFrame) and isinstance(ref, pd.DataFrame):
        if s.columns.nlevels != ref.columns.nlevels or s.columns.tolist() != ref.columns.tolist():
            return pd.DataFrame(np.broadcast_to(s.values, ref.shape), index=ref.index, columns=ref.columns)
    return s

fast_ma = vbt.MA.run(close, window=fast_window).ma
slow_ma = vbt.MA.run(close, window=slow_window).ma
ef_bc = fast_ma
es_bc = _bc(slow_ma, fast_ma)
close_bc = _bc(close, fast_ma)
entries = (ef_bc > es_bc) & (close_bc > ef_bc)
exits = ef_bc < es_bc
```

**Portfolio.from_signals flags for optimization:**
```python
pf = vbt.Portfolio.from_signals(
    close,
    entries=entries,
    exits=exits,
    broadcast_kwargs={'keep_pd': True},  # Crucial for optimization/WFO
)
```

**Lesson:**
- Use VBT indicators (`.run()`) for parameterized indicators so params broadcast during optimization
- Broadcast non-parameterized operands to the parameterized one with `_bc()`
- Use plain operators (`>`, `<`, `&`, `|`) on broadcast operands — do NOT use `.vbt.gt()`, `vbt.combine_logic()`, or `jitted=True` (they don't exist in vectorbt 1.0.0)
- Always add `broadcast_kwargs={'keep_pd': True}` to `Portfolio.from_signals`

### Agno Agent API Version Sensitivity

**Problem:** Adding `show_tool_calls=False` to `Agent()` initialization throws `TypeError: Agent.__init__() got an unexpected keyword argument 'show_tool_calls'`.

**Root Cause:** The `agno` library version installed in this project does not support the `show_tool_calls` parameter.

**Solution:** Omit `show_tool_calls` from `Agent()` calls. Use `markdown=False` and `debug_mode=False` for output control instead.

**Lesson:** When working with the Agno SDK in this repo, stick to the minimal set of kwargs: `model`, `instructions`, `tools`, `markdown`, `debug_mode`.

### Null vs Undefined in Frontend Numeric Guards

**Problem:** React crashes with `TypeError: Cannot read properties of null (reading 'toFixed')` even though the code has `!== undefined` checks.

**Root Cause:** The backend returns `null` for missing numeric fields. In JavaScript, `null !== undefined` is `true`, so the guard passes and `null.toFixed()` crashes.

**Solution:** Use `!= null` (loose equality) which matches both `null` and `undefined`:
```tsx
// WRONG - crashes when value is null:
{result.eps_growth_qoq !== undefined && (
  <span>{result.eps_growth_qoq.toFixed(1)}%</span>
)}

// CORRECT - handles both null and undefined:
{result.eps_growth_qoq != null && (
  <span>{result.eps_growth_qoq.toFixed(1)}%</span>
)}
```

**Lesson:** When guarding numeric fields from backend responses, always use `!= null` not `!== undefined`. Check all fields that call `.toFixed()`, `.toLocaleString()`, or any number method.

### Candlestick Chart Already Has Volume Histogram

**Problem:** User requests volume bars on the candlestick chart modal.

**Reality:** The `CandleStickChart` component (`frontend/src/components/quantgen/CandleStickChart.tsx`) already renders a `HistogramSeries` for volume. It is created automatically when the OHLCV data contains non-zero volume values. The volume bars are colored green for up days and red for down days, positioned in the bottom 20% of the chart.

**Lesson:** Before adding volume visualization, verify the component doesn't already support it. The `/api/ohlcv/{ticker}` endpoint returns volume data and the chart consumes it.

### TA Library Column Naming Convention

**Context:** The Quant Strategy screener uses the `ta` library (`add_all_ta_features`) for indicator computation.

**Key column names:**
- `trend_sma_fast` → SMA(20)
- `trend_sma_slow` → SMA(50)
- `momentum_rsi` → RSI(14)
- `trend_macd` → MACD
- `Volume` → raw volume

**Custom fields added per ticker:**
- `ath_proximity` = close / all_time_high
- `volume_ratio` = current_volume / 50_day_avg_volume
- `volume` = raw daily volume
- `volume_ma_50` = 50-day rolling average volume

**Lesson:** When adding new indicators or filters to the technical screener, use the `ta` library's output column names. Custom computed fields should be added in `_worker_ta_analysis` and included in the `ta_to_friendly` mapping in `run_quant_strategy_screener`.