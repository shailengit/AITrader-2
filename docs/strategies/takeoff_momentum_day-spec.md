# Day-Trade "Takeoff" Momentum Strategy — Spec

**Name:** `takeoff_momentum_day`
**Type:** Day-trading (intraday execution on 1-minute data, daily screen on daily data)
**Status:** Phase 1 spec (agreed by user 2026-09-03)

---

## Architecture (data flow)

1. **Daily screen** (on `sp1500_1d` daily data for the full ~1500 universe):
   - On signal day `D` (at close), compute the composite score for every stock using
     daily data up to and including `D`.
2. **Intraday execution** (on `sp1500_1m` 1-minute data):
   - On the *next* trading day `D+1`, enter the top-ranked picks intraday and manage
     exits on 1-minute bars. All positions liquidated by 3:55 PM ET.

> **Data constraint:** 1-minute data (`sp1500_1m`) currently only covers
> 2026-07-30 → 2026-08-07 (~7 trading days) for ~1500 stocks, with some partial
> tickers (1,097–2,730 rows vs. full 2,730). Daily data (`sp1500_1d`) covers
> 1962 → 2026-08-28. The intraday backtest window is therefore limited to the
> 7 available trading days (proof-of-concept). The screen itself is validated on
> the full daily history where 1-minute data is unavailable.

---

## 1. Entry Signal — Daily Composite Score

Composite score per stock on day `D`:

```
score = 0.70 * momentum     +
        0.10 * volatility   +
        0.20 * volume
```

### 1a. Momentum Breakout (70%)
- **EMA5** crosses **above EMA200** (5-day EMA > 200-day EMA today, and
  EMA5 ≤ EMA200 yesterday — i.e., a fresh golden cross of the short/fast pair).
- **Price closed yesterday above EMA5** (`close[yesterday] > EMA5[yesterday]`).
- **Angle ranking:** compute the angle between EMA5 and EMA200 using their values
  `LOOKBACK=5` days apart:
  ```
  delta_ema5  = EMA5[D]   - EMA5[D-LOOKBACK]
  delta_200   = EMA200[D] - EMA200[D-LOOKBACK]
  angle       = atan2(delta_ema5 - delta_200, LOOKBACK)   # radians -> degrees
  ```
  Higher angle = faster EMA5 rising vs. EMA200 = stronger takeoff. The lookback is a
  tunable parameter (default 5 days).

### 1b. Volatility Squeeze (10%)
- Bollinger Bands (20-day SMA, 2 std dev). Squeeze when band **width** is *narrow*.
- `bandwidth = (BB_up - BB_low) / SMA20`.
- The *lower* the bandwidth (more squeezed = more energy building to expand), the
  higher the volatility sub-score. Normalized inversely across candidates.

### 1c. Volume Surge (20%)
- `volume_ratio = volume[D] / mean(volume[D-5 ... D-1])` (yesterday-and-prior 5-day average; today excluded).
- Qualify if **volume_ratio ≥ 1.5** (excl-today 5-day avg); higher ratio = higher sub-score.

### Universe
- Include only individual stocks (~1500 universe); **exclude ETFs/sector funds**
  (SPY, QQQ, DIA, IWM, XLB..XLY, VIX, etc.) and any ticker without sector metadata.

### Special filters (apply before ranking)
- **Price filter:** `close > $10`
- **Liquidity filter:** average daily dollar volume > $50M
  (dollar vol = close × volume, averaged over last 20 days)

### Selection
- Score all qualifying stocks; take the **top 5** (may be fewer if fewer qualify).
- **Sector cap:** max **2** positions per sector (enforced after ranking).

---

## 2. Position Sizing — Score-Weighted

- Total day capital: **$100,000** (equity = cash + position value).
- Capital allocated proportional to composite score among selected positions:
  ```
  alloc_i = capital * (score_i / sum(score_j for j in selected))
  shares_i = floor(alloc_i / entry_price_i)
  ```
- If fewer than 5 qualify, remaining capital stays in cash.

---

## 3. Exit Rules (priority order, evaluated each 1-minute bar)

1. **Take-profit:** price ≥ entry × (1 + 0.04)  →  +4%
2. **Stop-loss:**  price ≤ entry × (1 − 0.02)  →  −2%
3. **Trailing stop:** price ≤ high_since_entry × (1 − 0.02)  →  2% trail from running high
4. **End-of-day:** liquidate at **15:55 ET** (market close), no overnight positions

Priority if multiple triggers on same bar: TP → SL → trail → 3:55 close.

---

## 4. Risk Management

- **Sector cap:** max 2 positions per sector (see 1).
- **Liquidity/price filters:** price > $10, avg daily dollar volume > $100M.
- Per-position stop-loss at −1% (see exits).

---

## 5. Parameters (defaults)

| Parameter | Value |
|---|---|
| Total capital | $100,000 |
| Max holdings | 5 |
| Momentum weight | 0.70 |
| Volatility weight | 0.10 |
| Volume weight | 0.20 |
| EMA lookback for angle | 5 days |
| Volume surge threshold | 1.5× (excl-today 5-day avg) |
| Bollinger window / std | 20 / 2 |
| VOLUME_AVG_WINDOW | 5 |
| Price filter | > $10 |
| Min avg daily dollar volume | > $50M |
| Sector cap | 2 |
| Take-profit | +4% |
| Stop-loss | −2% |
| Trailing stop | 2% |
| Trailing window (since entry high) | rolling high |
| Entry timing | wait for a confirmation 1-min bar after open (see below) |
| End-of-day liquidation | 15:55 ET |

### Intraday entry confirmation (Decision 6)
- Do **not** enter the market-open bar blindly.
- **Entry trigger:** enter at the close of the first 1-minute bar on `D+1` whose
  close is **above the prior day's close** (`close[D]`), confirming the takeoff
  continues after the open.
- Entry price = that confirmation bar's close.
- If no confirmation bar occurs before 15:55, no entry that day.

---

## 6. Deliverables

1. **Standalone script:** `strategies/takeoff_momentum_day.py` — self-contained,
   queries both databases, runs daily screen + intraday execution, exports report data.
2. **In-app Strategy subclass:** `backend/app/services/strategies/takeoff_momentum_day.py`.
3. **HTML report:** `docs/reports/takeoff_momentum_day_report.html`.

Both code versions must produce **identical** performance. Verified automatically.

---

## 7. Known limitations / notes

- Intraday backtest is limited to the 7 trading days of 1-minute data (proof-of-concept).
- 2% stop-loss; may trigger on noise — monitor results, tunable.
- Volume surge threshold (2×), ETF exclusion and angle lookback (5d) are tunable in Phase 4.
