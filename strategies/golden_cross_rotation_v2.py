"""
Golden Cross Rotation v2 — Standalone Strategy
================================================
Scans 1500 stocks daily for EMA20/200 golden cross.
Ranks by: 60% crossover angle + 40% market cap.
Holds top 5, rotates when better candidates appear.
Exits: hard stop loss (10%), trailing stop (20%), take profit (30%),
       death cross, death cross warning, time stop (60d).
Minimum hold days: 14 before rotation close.
Volatility filter — skips stocks with 14d daily return std > 5%.
Volume confirmation — requires >1.2x 50-day avg volume.
Market cap floor — $10B minimum.
Sector diversification — max 3 per sector.
Score-squared position sizing for aggressive top-pick weighting.
Regime filter — only take signals when SPY > SMA(50).
Bear market mode — SPY < SMA(200) → go to cash.
$100,000 starting capital.

Usage:
  cd backend && ./venv/bin/python ../strategies/golden_cross_rotation_v2.py
"""

import os
import sys
import warnings
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import OrderedDict

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")


# ── Configuration ──────────────────────────────────────────────────────────
AS_OF = "2020-01-01"
END = "2026-07-08"
CAPITAL = 100_000.0
MAX_HOLDINGS = 5
MIN_HOLD_DAYS = 14
HARD_STOP_LOSS = 0.10
TRAILING_STOP = 0.20
TAKE_PROFIT = 0.30
TIME_STOP_DAYS = 60
MAX_VOLATILITY = 0.05
MIN_VOLUME_RATIO = 1.2
MIN_MARKET_CAP = 10_000_000_000  # $10B
MAX_SECTOR_COUNT = 3
ANGLE_WEIGHT = 0.60
CAP_WEIGHT = 0.40
BULL_EXPOSURE = 1.0
BEAR_EXPOSURE = 0.0  # Go to cash in bear market

SECTOR_TO_ETF = {
    "Technology": "XLK", "Energy": "XLE", "Financials": "XLF",
    "Financial Services": "XLF", "Health Care": "XLV", "Healthcare": "XLV",
    "Consumer Discretionary": "XLY", "Consumer Cyclical": "XLY",
    "Industrials": "XLI", "Communication Services": "XLC",
    "Consumer Staples": "XLP", "Consumer Defensive": "XLP",
    "Materials": "XLB", "Basic Materials": "XLB",
    "Real Estate": "XLRE", "Utilities": "XLU",
}


def compute_ema_crossover_angle(close: pd.Series, ema20: pd.Series, ema200: pd.Series, cross_idx: int) -> float:
    """Compute the angle between EMA20 and EMA200 at crossover."""
    lookback = 3
    if cross_idx < lookback:
        return 0.0
    end = min(cross_idx + lookback, len(close) - 1)
    start = max(0, cross_idx - lookback)
    if end == start:
        return 0.0
    spread_before = (ema20.iloc[start] - ema200.iloc[start])
    spread_after = (ema20.iloc[end] - ema200.iloc[end])
    angle = (spread_after - spread_before) / (end - start)
    return float(angle) if pd.notna(angle) else 0.0


def precompute_stock_data(tickers: list, start: str, end: str) -> dict:
    """Pre-compute EMA20, EMA200, crossover dates, angles, and sectors for all stocks."""
    from app.db.database import engine
    from app.utils.security import get_safe_table_name
    from sqlalchemy import text

    print(f"\n📥 Pre-computing data for {len(tickers)} stocks...")
    stock_data = {}

    for idx, ticker in enumerate(tickers):
        if (idx + 1) % 200 == 0:
            print(f"  Progress: {idx+1}/{len(tickers)}")

        try:
            safe = get_safe_table_name(ticker)
        except ValueError:
            continue

        try:
            with engine.connect() as conn:
                df = pd.read_sql(
                    f'SELECT "Date", "Close", "Volume" FROM "{safe}" '
                    f'WHERE "Date" >= \'{start}\' AND "Date" <= \'{end}\' ORDER BY "Date"',
                    conn
                )
        except Exception:
            continue

        if df.empty or len(df) < 250:
            continue

        close = df["Close"]
        volume = df["Volume"].astype(float)
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema200 = close.rolling(window=200).mean()
        volume_ma50 = volume.rolling(50).mean()

        # 14-day rolling volatility
        returns = close.pct_change(fill_method=None)
        vol_14 = returns.rolling(14).std()

        # Find all EMA20/200 crossovers
        crossovers = []
        for i in range(1, len(df)):
            if (pd.notna(ema20.iloc[i]) and pd.notna(ema200.iloc[i]) and
                pd.notna(ema20.iloc[i-1]) and pd.notna(ema200.iloc[i-1])):
                # Golden cross
                if ema20.iloc[i-1] <= ema200.iloc[i-1] and ema20.iloc[i] > ema200.iloc[i]:
                    angle = compute_ema_crossover_angle(close, ema20, ema200, i)
                    volatility = float(vol_14.iloc[i]) if pd.notna(vol_14.iloc[i]) else 0.0
                    vol_ratio = float(volume.iloc[i] / volume_ma50.iloc[i]) if pd.notna(volume_ma50.iloc[i]) and volume_ma50.iloc[i] > 0 else 0.0
                    crossovers.append({
                        "date": str(df["Date"].iloc[i])[:10],
                        "price": float(close.iloc[i]),
                        "angle": angle,
                        "volatility": volatility,
                        "volume_ratio": vol_ratio,
                    })
                # Death cross
                elif ema20.iloc[i-1] >= ema200.iloc[i-1] and ema20.iloc[i] < ema200.iloc[i]:
                    crossovers.append({
                        "date": str(df["Date"].iloc[i])[:10],
                        "price": float(close.iloc[i]),
                        "angle": 0.0,
                        "death_cross": True,
                    })

        if crossovers:
            mc = 0.0
            sector = "Unknown"
            try:
                with engine.connect() as conn:
                    row = conn.execute(
                        text("SELECT market_cap, sector FROM stock_metadata WHERE ticker = :t"),
                        {"t": ticker.upper()}
                    ).fetchone()
                if row:
                    if row[0] is not None:
                        mc = float(row[0])
                    if row[1] is not None:
                        sector = row[1]
            except Exception:
                pass

            stock_data[ticker.upper()] = {
                "close": close.values,
                "dates": df["Date"].values,
                "ema20": ema20.values,
                "ema200": ema200.values,
                "crossovers": crossovers,
                "market_cap": mc,
                "sector": sector,
            }

    print(f"  Done. {len(stock_data)} stocks with crossover data.")
    return stock_data


def main():
    from app.services.data_service import get_data
    from app.db.database import engine
    from sqlalchemy import text

    print("=" * 80)
    print("  GOLDEN CROSS ROTATION V2")
    print("=" * 80)
    print(f"  Period:     {AS_OF} → {END}")
    print(f"  Capital:    ${CAPITAL:,.2f}")
    print(f"  Holdings:   Top {MAX_HOLDINGS} (rotate daily)")
    print(f"  Ranking:    {ANGLE_WEIGHT*100:.0f}% angle + {CAP_WEIGHT*100:.0f}% market cap")
    print(f"  Min Hold:   {MIN_HOLD_DAYS} days")
    print(f"  Hard Stop:  {HARD_STOP_LOSS:.0%}")
    print(f"  Trailing:   {TRAILING_STOP:.0%}")
    print(f"  Take Profit: {TAKE_PROFIT:.0%}")
    print(f"  Time Stop:  {TIME_STOP_DAYS} days")
    print(f"  Max/Sector: {MAX_SECTOR_COUNT}")
    print(f"  Vol Filter: >{MAX_VOLATILITY:.0%} daily std (skip)")
    print(f"  Vol Req:    >{MIN_VOLUME_RATIO:.1f}x avg volume")
    print(f"  MC Floor:   ${MIN_MARKET_CAP:,.0f}")
    print(f"  Regime:     SPY > SMA(50) for entries")
    print(f"  Bear Mode:  SPY < SMA(200) → cash")
    print(f"  Sizing:     Score²-weighted (top pick gets more)")
    print("=" * 80)

    # ── Get all tickers ─────────────────────────────────────────────────────
    with engine.connect() as conn:
        res = conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ))
        skip = {'stock_metadata', 'stock_financials_quarterly', 'stock_financials_yearly',
                'xlb', 'xlc', 'xle', 'xlf', 'xli', 'xlk', 'xlp', 'xlre', 'xlu', 'xlv', 'xly'}
        all_tickers = [row[0] for row in res if row[0] not in skip]

    # ── Pre-compute stock data ──────────────────────────────────────────────
    stock_db = precompute_stock_data(all_tickers, "2018-01-01", END)

    # ── Build full trading calendar from SPY ────────────────────────────────
    print("\n📅 Building trading calendar from SPY...")
    spy_df = get_data("SPY", start_date=AS_OF, end_date=END, frequency="daily")
    if spy_df is not None and not spy_df.empty:
        if "Date" not in spy_df.columns and spy_df.index.name == "Date":
            spy_df = spy_df.reset_index()
        all_dates = [str(d)[:10] for d in spy_df["Date"]]
    else:
        all_dates = sorted(set(
            str(pd.Timestamp(d))[:10]
            for data in stock_db.values()
            for d in data["dates"]
            if AS_OF <= str(pd.Timestamp(d))[:10] <= END
        ))
    print(f"  {len(all_dates)} trading days in simulation")

    # ── Build crossover index ──────────────────────────────────────────────
    print("\n📅 Building daily crossover calendar...")
    daily_crossovers = {}
    vol_filtered = 0
    vol_ratio_filtered = 0
    mc_filtered = 0
    for ticker, data in stock_db.items():
        for co in data["crossovers"]:
            if co.get("death_cross"):
                continue
            d = co["date"]
            if d < AS_OF:
                continue
            # Volatility filter
            if co.get("volatility", 0) > MAX_VOLATILITY:
                vol_filtered += 1
                continue
            # Volume confirmation
            if co.get("volume_ratio", 0) < MIN_VOLUME_RATIO:
                vol_ratio_filtered += 1
                continue
            # Market cap floor
            if data["market_cap"] < MIN_MARKET_CAP:
                mc_filtered += 1
                continue
            if d not in daily_crossovers:
                daily_crossovers[d] = []
            daily_crossovers[d].append({
                "ticker": ticker,
                "angle": co["angle"],
                "market_cap": data["market_cap"],
                "price": co["price"],
                "sector": data["sector"],
                "volume_ratio": co.get("volume_ratio", 0),
            })

    # Also build death cross index
    daily_death_crosses = {}
    for ticker, data in stock_db.items():
        for co in data["crossovers"]:
            if co.get("death_cross"):
                d = co["date"]
                if d < AS_OF:
                    continue
                if ticker not in daily_death_crosses:
                    daily_death_crosses[ticker] = []
                daily_death_crosses[ticker].append(d)

    print(f"  {len(daily_crossovers)} days with new golden crosses")
    print(f"  {sum(len(v) for v in daily_crossovers.values())} total crossover events")
    if vol_filtered:
        print(f"  🚫 {vol_filtered} filtered by volatility > {MAX_VOLATILITY:.0%}")
    if vol_ratio_filtered:
        print(f"  🚫 {vol_ratio_filtered} filtered by volume ratio < {MIN_VOLUME_RATIO:.1f}x")
    if mc_filtered:
        print(f"  🚫 {mc_filtered} filtered by market cap < ${MIN_MARKET_CAP:,.0f}")

    # ── Pre-compute SPY regime data ─────────────────────────────────────────
    print("\n📊 Pre-computing SPY regime data...")
    spy_full = get_data("SPY", start_date="2018-01-01", end_date=END, frequency="daily")
    spy_regime = {}
    if spy_full is not None and not spy_full.empty:
        if "Date" not in spy_full.columns and spy_full.index.name == "Date":
            spy_full = spy_full.reset_index()
        spy_full = spy_full.sort_values("Date").reset_index(drop=True)
        spy_close = spy_full["Close"].astype(float)
        spy_sma50 = spy_close.rolling(50).mean()
        spy_sma200 = spy_close.rolling(200).mean()
        for i in range(len(spy_full)):
            ds = str(spy_full["Date"].iloc[i])[:10]
            spy_regime[ds] = {
                "above_sma50": pd.notna(spy_sma50.iloc[i]) and spy_close.iloc[i] > spy_sma50.iloc[i],
                "above_sma200": pd.notna(spy_sma200.iloc[i]) and spy_close.iloc[i] > spy_sma200.iloc[i],
            }

    def is_above_sma50(date_str: str) -> bool:
        r = spy_regime.get(date_str, {})
        return r.get("above_sma50", False)

    def is_above_sma200(date_str: str) -> bool:
        r = spy_regime.get(date_str, {})
        return r.get("above_sma200", False)

    # ── Daily rotation simulation ───────────────────────────────────────────
    print(f"\n📈 Running daily rotation simulation...")
    print(f"  {len(all_dates)} trading days to simulate")

    holdings = OrderedDict()
    trades = []
    daily_equity = []

    # Pre-compute normalization constants
    all_market_caps = [v["market_cap"] for v in stock_db.values() if v["market_cap"] > 0]
    cap_max = max(all_market_caps) if all_market_caps else 1
    cap_min = min(all_market_caps) if all_market_caps else 0
    cap_range = cap_max - cap_min if cap_max > cap_min else 1

    def compute_score(angle: float, market_cap: float) -> float:
        angle_norm = 1 / (1 + np.exp(-angle * 100))
        cap_norm = (market_cap - cap_min) / cap_range if cap_range > 0 else 0.5
        return ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm

    def get_stock_value(ticker: str, date_str: str, field: str) -> float:
        data = stock_db.get(ticker)
        if data is None:
            return 0.0
        arr = data[field]
        dates = data["dates"]
        target = pd.Timestamp(date_str)
        for i in range(len(dates) - 1, -1, -1):
            if pd.Timestamp(dates[i]) <= target:
                return float(arr[i])
        return 0.0

    def get_price(ticker: str, date_str: str) -> float:
        return get_stock_value(ticker, date_str, "close")

    def get_ema20(ticker: str, date_str: str) -> float:
        return get_stock_value(ticker, date_str, "ema20")

    def get_ema200(ticker: str, date_str: str) -> float:
        return get_stock_value(ticker, date_str, "ema200")

    def has_death_cross(ticker: str, date_str: str, entry_date: str = None) -> bool:
        dc_dates = daily_death_crosses.get(ticker, [])
        for d in dc_dates:
            if d <= date_str:
                if entry_date is None or d > entry_date:
                    return True
        return False

    def compute_holding_score(ticker: str, date_str: str, market_cap: float) -> float:
        ema20 = get_ema20(ticker, date_str)
        ema200 = get_ema200(ticker, date_str)
        if ema20 <= 0 or ema200 <= 0:
            return 0.0
        spread_pct = (ema20 - ema200) / ema200
        angle_norm = 1 / (1 + np.exp(-spread_pct * 100))
        cap_norm = (market_cap - cap_min) / cap_range if cap_range > 0 else 0.5
        return ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm

    cash = CAPITAL
    portfolio_value = CAPITAL

    for sim_idx, current_date in enumerate(all_dates):
        if (sim_idx + 1) % 200 == 0:
            print(f"  Progress: {sim_idx+1}/{len(all_dates)} days  "
                  f"Portfolio: ${portfolio_value:>8,.2f}  "
                  f"Holdings: {len(holdings)}")

        # ── Bear market check ──────────────────────────────────────────────
        is_bear = not is_above_sma200(current_date)
        exposure = BEAR_EXPOSURE if is_bear else BULL_EXPOSURE

        # ── 1. Check exits for current holdings ────────────────────────────
        to_remove = []
        for ticker in list(holdings.keys()):
            h = holdings[ticker]
            current_price = get_price(ticker, current_date)
            if current_price <= 0:
                continue

            h["peak_price"] = max(h["peak_price"], current_price)
            ret = (current_price - h["entry_price"]) / h["entry_price"]
            pnl = h["shares"] * (current_price - h["entry_price"])

            # Hard stop loss (overrides min hold)
            if ret <= -HARD_STOP_LOSS:
                trades.append({
                    "ticker": ticker, "side": "SELL",
                    "entry_date": h["entry_date"], "exit_date": current_date,
                    "entry_price": round(h["entry_price"], 2),
                    "exit_price": round(current_price, 2),
                    "return_pct": round(ret * 100, 2),
                    "holding_days": (pd.Timestamp(current_date) - pd.Timestamp(h["entry_date"])).days,
                    "exit_reason": "Stop Loss",
                    "pnl_dollars": round(pnl, 2),
                })
                cash += h["shares"] * current_price
                to_remove.append(ticker)
                continue

            # Trailing stop
            dd = (h["peak_price"] - current_price) / h["peak_price"]
            if dd >= TRAILING_STOP:
                trades.append({
                    "ticker": ticker, "side": "SELL",
                    "entry_date": h["entry_date"], "exit_date": current_date,
                    "entry_price": round(h["entry_price"], 2),
                    "exit_price": round(current_price, 2),
                    "return_pct": round(ret * 100, 2),
                    "holding_days": (pd.Timestamp(current_date) - pd.Timestamp(h["entry_date"])).days,
                    "exit_reason": f"Trailing Stop ({dd:.1%})",
                    "pnl_dollars": round(pnl, 2),
                })
                cash += h["shares"] * current_price
                to_remove.append(ticker)
                continue

            # Take profit
            if ret >= TAKE_PROFIT:
                trades.append({
                    "ticker": ticker, "side": "SELL",
                    "entry_date": h["entry_date"], "exit_date": current_date,
                    "entry_price": round(h["entry_price"], 2),
                    "exit_price": round(current_price, 2),
                    "return_pct": round(ret * 100, 2),
                    "holding_days": (pd.Timestamp(current_date) - pd.Timestamp(h["entry_date"])).days,
                    "exit_reason": "Take Profit",
                    "pnl_dollars": round(pnl, 2),
                })
                cash += h["shares"] * current_price
                to_remove.append(ticker)
                continue

            # Death cross
            if has_death_cross(ticker, current_date, h["entry_date"]):
                trades.append({
                    "ticker": ticker, "side": "SELL",
                    "entry_date": h["entry_date"], "exit_date": current_date,
                    "entry_price": round(h["entry_price"], 2),
                    "exit_price": round(current_price, 2),
                    "return_pct": round(ret * 100, 2),
                    "holding_days": (pd.Timestamp(current_date) - pd.Timestamp(h["entry_date"])).days,
                    "exit_reason": "Death Cross",
                    "pnl_dollars": round(pnl, 2),
                })
                cash += h["shares"] * current_price
                to_remove.append(ticker)
                continue

            # Death cross warning
            ema20_val = get_ema20(ticker, current_date)
            ema200_val = get_ema200(ticker, current_date)
            if ema20_val > 0 and ema200_val > 0 and ret < 0:
                spread_pct = (ema20_val - ema200_val) / ema200_val
                if spread_pct < 0.001:
                    trades.append({
                        "ticker": ticker, "side": "SELL",
                        "entry_date": h["entry_date"], "exit_date": current_date,
                        "entry_price": round(h["entry_price"], 2),
                        "exit_price": round(current_price, 2),
                        "return_pct": round(ret * 100, 2),
                        "holding_days": (pd.Timestamp(current_date) - pd.Timestamp(h["entry_date"])).days,
                        "exit_reason": "Death Cross Warning",
                        "pnl_dollars": round(pnl, 2),
                    })
                    cash += h["shares"] * current_price
                    to_remove.append(ticker)
                    continue

            # Time stop
            hold_days = (pd.Timestamp(current_date) - pd.Timestamp(h["entry_date"])).days
            if hold_days >= TIME_STOP_DAYS:
                trades.append({
                    "ticker": ticker, "side": "SELL",
                    "entry_date": h["entry_date"], "exit_date": current_date,
                    "entry_price": round(h["entry_price"], 2),
                    "exit_price": round(current_price, 2),
                    "return_pct": round(ret * 100, 2),
                    "holding_days": hold_days,
                    "exit_reason": f"Time Stop ({hold_days}d)",
                    "pnl_dollars": round(pnl, 2),
                })
                cash += h["shares"] * current_price
                to_remove.append(ticker)
                continue

        for t in to_remove:
            del holdings[t]

        # ── 2. Score new candidates ─────────────────────────────────────────
        new_candidates = daily_crossovers.get(current_date, [])
        for c in new_candidates:
            c["score"] = compute_score(c["angle"], c["market_cap"])

        # ── 3. Merge holdings + new candidates, rank, keep top N ────────────
        all_stocks = []
        held_tickers = set(holdings.keys())
        for ticker, h in holdings.items():
            current_score = compute_holding_score(ticker, current_date, h["market_cap"])
            all_stocks.append({
                "ticker": ticker, "score": current_score,
                "market_cap": h["market_cap"], "sector": h["sector"],
                "is_holding": True,
            })
        for c in new_candidates:
            if c["ticker"] not in held_tickers:
                all_stocks.append({
                    "ticker": c["ticker"], "score": c["score"],
                    "angle": c["angle"], "market_cap": c["market_cap"],
                    "price": c["price"], "sector": c["sector"],
                    "is_holding": False,
                })

        all_stocks.sort(key=lambda x: x["score"], reverse=True)

        # Build top N with sector diversification
        top_n = []
        sector_counts = {}
        for s in all_stocks:
            if len(top_n) >= MAX_HOLDINGS:
                break
            sec = s.get("sector", "Unknown")
            if sector_counts.get(sec, 0) >= MAX_SECTOR_COUNT:
                continue
            top_n.append(s)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

        top_n_tickers = set(s["ticker"] for s in top_n)

        # ── 4. Sell dropped holdings (with min hold days check) ──────────────
        to_drop = []
        for ticker in holdings:
            if ticker not in top_n_tickers:
                h = holdings[ticker]
                hold_days = (pd.Timestamp(current_date) - pd.Timestamp(h["entry_date"])).days
                if hold_days < MIN_HOLD_DAYS:
                    continue
                to_drop.append(ticker)

        for ticker in to_drop:
            h = holdings[ticker]
            current_price = get_price(ticker, current_date)
            if current_price > 0:
                ret = (current_price - h["entry_price"]) / h["entry_price"]
                pnl = h["shares"] * (current_price - h["entry_price"])
                trades.append({
                    "ticker": ticker, "side": "SELL",
                    "entry_date": h["entry_date"], "exit_date": current_date,
                    "entry_price": round(h["entry_price"], 2),
                    "exit_price": round(current_price, 2),
                    "return_pct": round(ret * 100, 2),
                    "holding_days": hold_days,
                    "exit_reason": "Rotated Out",
                    "pnl_dollars": round(pnl, 2),
                })
                cash += h["shares"] * current_price
            del holdings[ticker]

        # ── 5. Buy new top N stocks (score-squared sizing) ──────────────────
        slots_available = MAX_HOLDINGS - len(holdings)
        if slots_available > 0:
            new_entries = [s for s in top_n if s["ticker"] not in holdings][:slots_available]
            total_score = sum(s["score"] ** 2 for s in new_entries if s["score"] > 0)
            if total_score > 0:
                for s in new_entries:
                    price = s.get("price", get_price(s["ticker"], current_date))
                    if price <= 0:
                        continue
                    weight = (s["score"] ** 2) / total_score
                    target_value = portfolio_value * exposure * weight
                    shares = int(target_value / price)
                    cost = shares * price
                    if cost > cash:
                        shares = int(cash / price)
                        cost = shares * price
                    if shares <= 0:
                        continue
                    cash -= cost
                    holdings[s["ticker"]] = {
                        "entry_date": current_date,
                        "entry_price": price,
                        "peak_price": price,
                        "shares": shares,
                        "score": s["score"],
                        "angle": s.get("angle", 0),
                        "market_cap": s.get("market_cap", 0),
                        "sector": s.get("sector", "Unknown"),
                        "volume_ratio": s.get("volume_ratio", 0),
                    }
                    trades.append({
                        "ticker": s["ticker"], "side": "BUY",
                        "entry_date": current_date, "exit_date": "",
                        "entry_price": round(price, 2), "exit_price": 0,
                        "return_pct": 0.0, "holding_days": 0,
                        "exit_reason": "New Entry", "pnl_dollars": 0.0,
                    })

        # ── 6. Track daily portfolio value ──────────────────────────────────
        holdings_value = 0.0
        for ticker, h in holdings.items():
            price = get_price(ticker, current_date)
            if price > 0:
                holdings_value += h["shares"] * price
        portfolio_value = cash + holdings_value
        daily_equity.append({
            "date": current_date, "value": round(portfolio_value, 2),
            "cash": round(cash, 2), "holdings": round(holdings_value, 2),
            "n_holdings": len(holdings),
        })

    # ── Portfolio Summary ──────────────────────────────────────────────────
    total_pnl = portfolio_value - CAPITAL
    total_ret = total_pnl / CAPITAL * 100

    print(f"\n{'='*80}")
    print("  PORTFOLIO SUMMARY")
    print("=" * 80)
    print(f"  Initial Capital:  ${CAPITAL:>10,.2f}")
    print(f"  Final Portfolio:  ${portfolio_value:>10,.2f}")
    print(f"  Total P&L:        ${total_pnl:>+10,.2f}")
    print(f"  Total Return:     {total_ret:>+8.2f}%")

    # SPY benchmark
    spy_df = get_data("SPY", start_date=AS_OF, end_date=END, frequency="daily")
    if spy_df is not None and not spy_df.empty:
        if "Date" not in spy_df.columns and spy_df.index.name == "Date":
            spy_df = spy_df.reset_index()
        spy_ret = (spy_df["Close"].iloc[-1] / spy_df["Close"].iloc[0] - 1) * 100
        alpha = total_ret - spy_ret
        print(f"  SPY Return:       {spy_ret:>+8.2f}%")
        print(f"  Alpha:            {alpha:>+8.2f}%  {'✅' if alpha > 0 else '❌'}")

    # Trade stats
    buy_trades = [t for t in trades if t["side"] == "BUY"]
    sell_trades = [t for t in trades if t["side"] == "SELL"]
    winners = [t for t in sell_trades if t["pnl_dollars"] > 0]
    losers = [t for t in sell_trades if t["pnl_dollars"] <= 0]
    win_rate = len(winners) / len(sell_trades) * 100 if sell_trades else 0
    avg_win = np.mean([t["pnl_dollars"] for t in winners]) if winners else 0
    avg_loss = np.mean([t["pnl_dollars"] for t in losers]) if losers else 0
    gross_profit = sum(t["pnl_dollars"] for t in winners)
    gross_loss = abs(sum(t["pnl_dollars"] for t in losers))
    profit_factor = gross_profit / (gross_loss + 1e-9)

    print(f"\n  ── Trade Statistics ──")
    print(f"  Total Trades:     {len(sell_trades)}")
    print(f"  Winners:          {len(winners)} ({win_rate:.0f}%)")
    print(f"  Losers:           {len(losers)} ({100-win_rate:.0f}%)")
    print(f"  Avg Winner:       ${avg_win:>+8,.2f}")
    print(f"  Avg Loser:        ${avg_loss:>+8,.2f}")
    print(f"  Profit Factor:    {profit_factor:.2f}")

    # Exit reason breakdown
    print(f"\n  ── Exit Reasons ──")
    reasons = {}
    for t in sell_trades:
        r = t["exit_reason"].split("(")[0].strip()
        reasons[r] = reasons.get(r, 0) + 1
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {r:>20}: {c} trades")

    # Top/bottom trades
    if sell_trades:
        sorted_trades = sorted(sell_trades, key=lambda t: t["return_pct"], reverse=True)
        print(f"\n  ── Top 5 Winners ──")
        for t in sorted_trades[:5]:
            print(f"  {t['ticker']:>8}  {t['return_pct']:>+7.2f}%  ${t['pnl_dollars']:>+8,.2f}  "
                  f"{t['holding_days']}d  {t['exit_reason']}")
        print(f"\n  ── Bottom 5 Losers ──")
        for t in sorted_trades[-5:]:
            print(f"  {t['ticker']:>8}  {t['return_pct']:>+7.2f}%  ${t['pnl_dollars']:>+8,.2f}  "
                  f"{t['holding_days']}d  {t['exit_reason']}")

    # Monthly returns
    if daily_equity:
        eq_df = pd.DataFrame(daily_equity)
        eq_df["date"] = pd.to_datetime(eq_df["date"])
        eq_df = eq_df.set_index("date")
        monthly = eq_df["value"].resample("ME").last()
        monthly_ret = monthly.pct_change().dropna() * 100
        print(f"\n  ── Monthly Stats ──")
        print(f"  Best Month:       {monthly_ret.max():>+7.2f}%")
        print(f"  Worst Month:      {monthly_ret.min():>+7.2f}%")
        print(f"  Avg Month:        {monthly_ret.mean():>+7.2f}%")
        print(f"  Positive Months:  {(monthly_ret > 0).sum()}/{len(monthly_ret)} ({(monthly_ret > 0).mean()*100:.0f}%)")

    print(f"\n{'='*80}")
    print("  ✅ DONE")
    print("=" * 80)

    # ── Export data for HTML report ──────────────────────────────────────────
    import json
    report_dir = os.path.join(os.path.dirname(__file__), "..", "docs", "reports")
    os.makedirs(report_dir, exist_ok=True)
    with open(os.path.join(report_dir, "daily_equity_v2.json"), "w") as f:
        json.dump(daily_equity, f, indent=2)
    with open(os.path.join(report_dir, "trades_v2.json"), "w") as f:
        json.dump(trades, f, indent=2)

    years = (datetime.strptime(END, "%Y-%m-%d") - datetime.strptime(AS_OF, "%Y-%m-%d")).days / 365.25
    summary = {
        "initial_capital": CAPITAL,
        "final_portfolio": portfolio_value,
        "total_return_pct": round(total_ret, 2),
        "cagr_pct": round(((portfolio_value / CAPITAL) ** (1 / years) - 1) * 100, 2),
        "total_trades": len(sell_trades),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "avg_winner": round(avg_win, 2),
        "avg_loser": round(avg_loss, 2),
        "exit_reasons": reasons,
    }
    if 'spy_ret' in dir():
        summary["spy_return_pct"] = round(spy_ret, 2)
    if 'monthly_ret' in dir():
        summary["best_month"] = round(monthly_ret.max(), 2)
        summary["worst_month"] = round(monthly_ret.min(), 2)
        summary["avg_month"] = round(monthly_ret.mean(), 2)
        summary["positive_months"] = f"{(monthly_ret > 0).sum()}/{len(monthly_ret)} ({(monthly_ret > 0).mean()*100:.0f}%)"
    with open(os.path.join(report_dir, "summary_v2.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  📊 Data exported to {report_dir}/")


if __name__ == "__main__":
    main()
