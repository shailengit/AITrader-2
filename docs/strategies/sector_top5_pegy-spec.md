# Strategy Spec — Sector Top-5 Momentum + PEGY

**Status:** Confirmed (all decisions made via clarify dialogue) — **revised 2026-08-20: PEGY gate 1.0→2.0, blend 50/50→80/20**
**Date:** 2026-08-20
**Strategy name:** `Sector Top-5 Momentum + PEGY`
**Class:** `SectorTop5MomentumPEGY`
**Files:**
- In-app: `backend/app/services/strategies/sector_top5_pegy.py`
- Standalone: `strategies/sector_top5_pegy.py` (thin wrapper → adapter)

---

## 1. Concept

Combine the **Sector Scanner Top-5 Rotation v3** momentum engine with a
**PEGY fundamental** screen. Momentum selects the universe; PEGY vets and
re-ranks it. The v3 "ride the winners" exit behavior (no rotation churn) is
preserved.

---

## 2. Entry Signal (universe filter — a name qualifies only if ALL hold)

1. **Scanner sector filter:** the stock's 3-month return (`perf_3m`) beats its
   own sector ETF's momentum. `min_perf = 0` if `sector_3m > 0.20`, else
   `sector_3m * 0.5`. (Unchanged from v3.)
2. **Market cap ≥ $5B.** (Unchanged.)
3. **14-day daily-return std ≤ 5%** (volatility filter). (Unchanged.)
4. **PEGY hard filter (NEW):** as-of PEGY is computable **and** `PEGY < 2.0`.
   A stock with no valid as-of PEGY is **not buyable** (skip — does not
   default to buyable). *(revised from 1.0 → 2.0)*

> PEGY = P/E ÷ (Earnings Growth % + Dividend Yield %), where
> Earnings Growth = YoY growth in trailing-12-mo `diluted_eps`, and the
> dividend yield uses trailing-12-mo dividends. **As-of aware:** only annual
> reports with `report_date <= trade_date` and that day's close are used —
> no look-ahead.

---

## 3. Candidate Ranking / Scoring

**Composite score (80/20 blend, revised from 50/50):**

```
composite = 0.80 * momentum_score + 0.20 * pegy_score

momentum_score = 1 / (1 + e^(-perf_3m * 10))   # sigmoid of 3-month momentum (unchanged)
pegy_score     = 1 / (1 + PEGY)                 # lower PEGY → higher score
```

- `composite` is used for **both ranking and linear position sizing**.
- If `PEGY` is missing / ≤ 0 → no `pegy_score` → name is not buyable.

---

## 4. Exit Rules (in priority order) — identical to v3

| Priority | Exit | Rule |
|----------|------|------|
| 1 | Hard stop loss | 20% below entry (overrides min hold) |
| 2 | Trailing stop | 10% from peak |
| 3 | Take profit | +50% |
| 4 | Time stop | disabled (0) |
| 5 | Rotation | **disabled** (`min_hold_days = 1,000,000`) — no churn |

`re_score_holdings = True` so existing holdings are re-scored with the current
composite each day and compete fairly with new candidates for the top-5; but
because rotation's min-hold never triggers, they ride until a real exit fires.

---

## 5. Position Sizing

- **Linear (score-proportional)** on the composite score — higher-composite
  names get larger positions. `sizing_method = "linear"`.

---

## 6. Parameters

| Parameter | Value |
|-----------|-------|
| Max holdings | 5 |
| Max per sector | 2 |
| Market cap min | $5B |
| Max volatility | 5% (14-day daily-return std) |
| Momentum K (sigmoid steepness) | 10.0 |
| PEGY threshold | 2.0 |
| Momentum weight | 0.80 |
| PEGY weight | 0.20 |
| Hard stop | 20% |
| Trailing stop | 10% |
| Take profit | 50% |
| Time stop | disabled |
| Rotation min-hold | disabled (`1,000,000`) |
| Bear exposure | 1.0 (no reduction) |

---

## 7. Backtest Configuration

- **Range:** 2021-01-01 → 2025-12-31 (constrained by PEGY annual data coverage,
  which spans report_dates 2021-02-28 → 2025-12-31).
- **Capital:** $100,000.
- **Data source:** PostgreSQL `sp1500_1d` (per-ticker price tables,
  `stock_metadata`, `stock_financials_yearly`).

---

## 8. Look-ahead-bias controls

- PEGY uses only annual reports with `report_date <= as-of date`.
- PEGY price uses that day's close (`Close <= as-of date`), never a future close.
- Same data source and same date range for both standalone and in-app versions.
- Identical-results check: total return within 0.1%, trade count exact, win
  rate within 0.1%, Sharpe within 0.01.

---

## 9. Verification Plan

1. Syntax check both files (`ast.parse`).
2. Standalone smoke run 2021-2025 → non-zero trades, clean exit.
3. In-app run through `StrategyBacktestAdapter` → `total_trades > 0`.
4. Identical-performance comparison (the standalone reuses the in-app class, so
   the comparison is structural; still confirm numbers match).
5. Generate interactive HTML report with hero stats, equity curve, trade table.
