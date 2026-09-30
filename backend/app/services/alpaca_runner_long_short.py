"""Daily long/short strategy runner for Alpaca paper trading.

Extends the golden cross rotation strategy with a short leg:
- Long:  EMA20/200 golden cross + Entry B (momentum continuation)
- Short: EMA20/200 death cross + Entry B (bearish breakdown)
- Holds top 5 longs and top 5 shorts
- Exits on inverse crossover, trailing stop (20%), or rotation
- 60/40 capital split (long/short) to account for short's higher risk

Designed to run on a separate Alpaca account from the long-only strategy.
"""

import os
import logging
import time
from datetime import datetime
from typing import List, Dict, Any

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from app.services.alpaca_client import AlpacaClient

logger = logging.getLogger(__name__)

# ── Strategy Parameters ──────────────────────────────────────────────
ANGLE_WEIGHT = 0.60
CAP_WEIGHT = 0.40
MAX_LONG_HOLDINGS = 5
MAX_SHORT_HOLDINGS = 5
MIN_HOLD_DAYS = 10
LONG_SIZING_PCTS = [0.30, 0.25, 0.20, 0.15, 0.10]
SHORT_SIZING_PCTS = [0.30, 0.25, 0.20, 0.15, 0.10]
TRAILING_STOP_PCT = 0.20
TAKE_PROFIT_PCT = 0.20

# Crisis override: when SPY drops this much from its 200-day high
CRISIS_DRAWDOWN = 0.20


class LongShortStrategyRunner:
    """Daily long/short strategy runner connecting the scan engine to Alpaca."""

    def __init__(self):
        self.alpaca = AlpacaClient(prefix="2")
        self.db_url = (
            f"postgresql://{os.getenv('DB_USER', 'postgres')}:"
            f"{os.getenv('DB_PASSWORD')}@"
            f"{os.getenv('DB_HOST', '127.0.0.1')}:"
            f"{os.getenv('DB_PORT', '5431')}/"
            f"{os.getenv('DB_NAME', 'sp1500_1d')}"
        )
        self.engine = create_engine(self.db_url)
        # Borrow cache: ticker -> bool (avoids 1500 API calls per run)
        self._borrow_cache: Dict[str, bool] = {}

    # ── Data Helpers ─────────────────────────────────────────────────

    def get_all_tickers(self) -> List[str]:
        """Get all stock tickers from the database."""
        skip = {'stock_metadata', 'stock_financials_quarterly', 'stock_financials_yearly',
                'xlb', 'xlc', 'xle', 'xlf', 'xli', 'xlk', 'xlp', 'xlre', 'xlu', 'xlv', 'xly', 'vix'}
        with self.engine.connect() as conn:
            res = conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ))
            return [row[0] for row in res if row[0] not in skip]

    def get_latest_date(self) -> str:
        """Get the latest trading date from the database."""
        with self.engine.connect() as conn:
            result = conn.execute(text('SELECT MAX("Date") FROM aapl')).scalar()
            return str(result)[:10] if result else datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def compute_ema_crossover_angle(close, ema20, ema200, cross_idx):
        """Compute the angle between EMA20 and EMA200 at crossover.

        Positive angle = EMA20 diverging upward (bullish for longs).
        Negative angle = EMA20 diverging downward (bearish for shorts).
        """
        lookback = 3
        if cross_idx < lookback or cross_idx + lookback >= len(close):
            return 0.0
        spread_before = (ema20.iloc[cross_idx - lookback] - ema200.iloc[cross_idx - lookback])
        spread_after = (ema20.iloc[cross_idx + lookback] - ema200.iloc[cross_idx + lookback])
        angle = (spread_after - spread_before) / (lookback * 2)
        return float(angle) if pd.notna(angle) else 0.0

    # ── Long Scan ────────────────────────────────────────────────────

    def scan_and_rank_longs(self, as_of_date: str) -> List[Dict[str, Any]]:
        """Scan all stocks for golden cross + Entry B signals, rank by score.

        Returns top MAX_LONG_HOLDINGS candidates with scores and metadata.
        """
        from app.utils.security import get_safe_table_name

        tickers = self.get_all_tickers()
        candidates = []

        for ticker in tickers:
            try:
                safe = get_safe_table_name(ticker)
            except ValueError:
                continue

            try:
                with self.engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Open", "High", "Low", "Close", "Volume" FROM "{safe}" '
                        f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 300',
                        conn
                    )
            except Exception:
                continue

            if df.empty or len(df) < 250:
                continue

            df = df.sort_values("Date").reset_index(drop=True)
            close = df["Close"]
            volume = df["Volume"]
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema200 = close.rolling(window=200).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()

            # RSI(14)
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / (avg_loss + 1e-9)
            rsi = 100 - (100 / (1 + rs))

            vol_ma50 = volume.rolling(50).mean()

            # Entry A: EMA20/200 golden cross on the most recent trading day only
            entry_a = None
            i = len(df) - 1
            if (pd.notna(ema20.iloc[i]) and pd.notna(ema200.iloc[i]) and
                pd.notna(ema20.iloc[i-1]) and pd.notna(ema200.iloc[i-1])):
                if ema20.iloc[i-1] <= ema200.iloc[i-1] and ema20.iloc[i] > ema200.iloc[i]:
                    angle = self.compute_ema_crossover_angle(close, ema20, ema200, i)
                    entry_a = {
                        "angle": angle,
                        "price": float(close.iloc[i]),
                        "date": str(df["Date"].iloc[i])[:10],
                    }

            # Entry B: Price > EMA50 > EMA200 AND RSI > 60 AND volume > 1.2x avg
            entry_b = None
            last = df.iloc[-1]
            if (pd.notna(ema50.iloc[-1]) and pd.notna(ema200.iloc[-1]) and
                pd.notna(rsi.iloc[-1]) and pd.notna(vol_ma50.iloc[-1]) and vol_ma50.iloc[-1] > 0):
                if (last["Close"] > ema50.iloc[-1] and ema50.iloc[-1] > ema200.iloc[-1] and
                    rsi.iloc[-1] > 60 and last["Volume"] > vol_ma50.iloc[-1] * 1.2):
                    slope = (ema50.iloc[-1] - ema50.iloc[-5]) / ema50.iloc[-5] if len(df) >= 5 else 0
                    entry_b = {
                        "angle": float(slope * 100),
                        "price": float(last["Close"]),
                        "date": str(last["Date"])[:10],
                    }

            if entry_a or entry_b:
                mc = self._get_market_cap(ticker)
                entry = entry_a or entry_b
                angle_norm = 1 / (1 + np.exp(-entry["angle"] * 100))
                cap_norm = min(1.0, mc / 100e9)
                score = ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm

                candidates.append({
                    "ticker": ticker.upper(),
                    "score": round(score, 4),
                    "angle": round(entry["angle"], 4),
                    "price": entry["price"],
                    "entry_date": entry["date"],
                    "entry_type": "A" if entry_a else "B",
                    "market_cap": mc,
                })

        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates[:MAX_LONG_HOLDINGS]

    # ── Short Scan ────────────────────────────────────────────────────

    def scan_and_rank_shorts(self, as_of_date: str) -> List[Dict[str, Any]]:
        """Scan all stocks for death cross + bearish Entry B signals, rank by score.

        Mirror of the long scan:
        - Entry A (Short): EMA20 crosses BELOW EMA200 (death cross)
        - Entry B (Short): Price < EMA50 < EMA200, RSI < 40, volume surge
        - Score: steeper decline (more negative angle) = stronger short signal

        Returns top MAX_SHORT_HOLDINGS candidates.
        """
        from app.utils.security import get_safe_table_name

        tickers = self.get_all_tickers()
        candidates = []

        for ticker in tickers:
            try:
                safe = get_safe_table_name(ticker)
            except ValueError:
                continue

            try:
                with self.engine.connect() as conn:
                    df = pd.read_sql(
                        f'SELECT "Date", "Open", "High", "Low", "Close", "Volume" FROM "{safe}" '
                        f'WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 300',
                        conn
                    )
            except Exception:
                continue

            if df.empty or len(df) < 250:
                continue

            df = df.sort_values("Date").reset_index(drop=True)
            close = df["Close"]
            volume = df["Volume"]
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema200 = close.rolling(window=200).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()

            # RSI(14)
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / (avg_loss + 1e-9)
            rsi = 100 - (100 / (1 + rs))

            vol_ma50 = volume.rolling(50).mean()

            # Entry A (Short): EMA20/200 death cross on the most recent trading day only
            entry_a = None
            i = len(df) - 1
            if (pd.notna(ema20.iloc[i]) and pd.notna(ema200.iloc[i]) and
                pd.notna(ema20.iloc[i-1]) and pd.notna(ema200.iloc[i-1])):
                if ema20.iloc[i-1] >= ema200.iloc[i-1] and ema20.iloc[i] < ema200.iloc[i]:
                    angle = self.compute_ema_crossover_angle(close, ema20, ema200, i)
                    entry_a = {
                        "angle": angle,       # Negative = steep decline = strong short
                        "price": float(close.iloc[i]),
                        "date": str(df["Date"].iloc[i])[:10],
                    }

            # Entry B (Short): Price < EMA50 < EMA200 AND RSI < 40 AND volume > 1.2x avg
            entry_b = None
            last = df.iloc[-1]
            if (pd.notna(ema50.iloc[-1]) and pd.notna(ema200.iloc[-1]) and
                pd.notna(rsi.iloc[-1]) and pd.notna(vol_ma50.iloc[-1]) and vol_ma50.iloc[-1] > 0):
                if (last["Close"] < ema50.iloc[-1] and ema50.iloc[-1] < ema200.iloc[-1] and
                    rsi.iloc[-1] < 40 and last["Volume"] > vol_ma50.iloc[-1] * 1.2):
                    slope = (ema50.iloc[-1] - ema50.iloc[-5]) / ema50.iloc[-5] if len(df) >= 5 else 0
                    entry_b = {
                        "angle": float(slope * 100),   # Negative = declining = strong short
                        "price": float(last["Close"]),
                        "date": str(last["Date"])[:10],
                    }

            if entry_a or entry_b:
                # Skip stocks that can't be shorted on Alpaca
                if not self._is_shortable(ticker.upper()):
                    continue

                mc = self._get_market_cap(ticker)
                entry = entry_a or entry_b

                # For shorts: more negative angle = stronger signal.
                # sigmoid(-angle) maps negative angles to high scores.
                angle_norm = 1 / (1 + np.exp(entry["angle"] * 100))
                cap_norm = min(1.0, mc / 100e9)
                score = ANGLE_WEIGHT * angle_norm + CAP_WEIGHT * cap_norm

                candidates.append({
                    "ticker": ticker.upper(),
                    "score": round(score, 4),
                    "angle": round(entry["angle"], 4),
                    "price": entry["price"],
                    "entry_date": entry["date"],
                    "entry_type": "A" if entry_a else "B",
                    "market_cap": mc,
                })

        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates[:MAX_SHORT_HOLDINGS]

    # ── Market Data Helpers ───────────────────────────────────────────

    def _is_shortable(self, ticker: str) -> bool:
        """Check if a stock is shortable on Alpaca, with caching."""
        if ticker in self._borrow_cache:
            return self._borrow_cache[ticker]

        info = self.alpaca.check_borrow_availability(ticker)
        shortable = info.get("shortable", False) and info.get("easy_to_borrow", False)
        self._borrow_cache[ticker] = shortable
        if not shortable:
            logger.debug("Skipping %s: not shortable (status=%s, easy_to_borrow=%s)",
                         ticker, info.get("status"), info.get("easy_to_borrow"))
        return shortable

    def _get_market_cap(self, ticker: str) -> float:
        """Fetch market cap from stock_metadata."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT market_cap FROM stock_metadata WHERE ticker = :t"),
                    {"t": ticker.upper()}
                ).fetchone()
            if row and row[0] is not None:
                return float(row[0])
        except Exception:
            pass
        return 0.0

    # ── Risk Checks ───────────────────────────────────────────────────

    def check_crisis_override(self, as_of_date: str) -> bool:
        """Check if SPY has dropped >20% from its 200-day high.

        When true: close all longs (market crashing). Shorts remain open
        since they profit from the decline.
        """
        try:
            with self.engine.connect() as conn:
                spy = pd.read_sql(
                    f'SELECT "Date", "Close" FROM spy WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 200',
                    conn
                )
            if spy.empty or len(spy) < 200:
                return False
            spy = spy.sort_values("Date")
            spy_high = spy["Close"].max()
            spy_current = spy["Close"].iloc[-1]
            drawdown = (spy_high - spy_current) / spy_high
            return drawdown >= CRISIS_DRAWDOWN
        except Exception:
            return False

    def check_death_cross(self, ticker: str, as_of_date: str) -> bool:
        """Check if a stock has a death cross (EMA20 below EMA200).

        Used as exit signal for long positions.
        """
        try:
            from app.utils.security import get_safe_table_name
            safe = get_safe_table_name(ticker)
            with self.engine.connect() as conn:
                df = pd.read_sql(
                    f'SELECT "Date", "Close" FROM "{safe}" WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 250',
                    conn
                )
            if df.empty or len(df) < 50:
                return False
            df = df.sort_values("Date").reset_index(drop=True)
            ema20 = df["Close"].ewm(span=20, adjust=False).mean()
            ema200 = df["Close"].rolling(window=200).mean()
            return bool(ema20.iloc[-1] < ema200.iloc[-1]) if pd.notna(ema20.iloc[-1]) and pd.notna(ema200.iloc[-1]) else False
        except Exception:
            return False

    def check_golden_cross(self, ticker: str, as_of_date: str) -> bool:
        """Check if a stock has a golden cross (EMA20 above EMA200).

        Used as exit signal for short positions — if the trend turns
        bullish, cover the short.
        """
        try:
            from app.utils.security import get_safe_table_name
            safe = get_safe_table_name(ticker)
            with self.engine.connect() as conn:
                df = pd.read_sql(
                    f'SELECT "Date", "Close" FROM "{safe}" WHERE "Date" <= \'{as_of_date}\' ORDER BY "Date" DESC LIMIT 250',
                    conn
                )
            if df.empty or len(df) < 50:
                return False
            df = df.sort_values("Date").reset_index(drop=True)
            ema20 = df["Close"].ewm(span=20, adjust=False).mean()
            ema200 = df["Close"].rolling(window=200).mean()
            return bool(ema20.iloc[-1] > ema200.iloc[-1]) if pd.notna(ema20.iloc[-1]) and pd.notna(ema200.iloc[-1]) else False
        except Exception:
            return False

    # ── Order Submission ──────────────────────────────────────────────

    def submit_short_bracket_order(self, symbol: str, qty: int, entry_price: float) -> Dict[str, Any]:
        """Submit a short bracket order with inverted take profit and stop loss.

        Uses a limit order with 0.5% tolerance to avoid bad fills at market open.
        For shorts: limit price = entry_price × (1 - tolerance) — sell slightly below
        yesterday's close to ensure entry in case of gap down.

        For shorts:
        - Take profit: buy to cover at entry_price × (1 - TAKE_PROFIT_PCT)
          (price drops → profit)
        - Stop loss: buy to cover at entry_price × (1 + TRAILING_STOP_PCT)
          (price rises → loss, stop out)
        """
        limit_tolerance = 0.005
        limit_price = round(entry_price * (1 - limit_tolerance), 2)
        tp_price = round(entry_price * (1 - TAKE_PROFIT_PCT), 2)
        stop_price = round(entry_price * (1 + TRAILING_STOP_PCT), 2)

        order = self.alpaca.api.submit_order(
            symbol=symbol,
            qty=qty,
            side="sell",
            type="limit",
            limit_price=str(limit_price),
            time_in_force="gtc",
            order_class="bracket",
            take_profit={"limit_price": str(tp_price)},
            stop_loss={
                "stop_price": str(stop_price),
                "trail_percent": str(TRAILING_STOP_PCT * 100),
            },
        )
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": int(order.qty),
            "side": order.side,
            "status": order.status,
            "type": order.type,
            "submitted_at": str(order.submitted_at),
        }

    # ── Protection Re-Attachment ─────────────────────────────────────

    def _get_hold_days(self, ticker: str, as_of_date: str) -> int:
        """Estimate how many trading days a position has been held."""
        entry_date = self.alpaca.get_entry_date(ticker)
        if not entry_date:
            return 999
        try:
            from app.utils.security import get_safe_table_name
            safe = get_safe_table_name(ticker)
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(f'SELECT COUNT(*) FROM "{safe}" WHERE "Date" > \'{entry_date}\' AND "Date" <= \'{as_of_date}\'')
                ).scalar()
                return int(row) if row else 0
        except Exception:
            from datetime import datetime
            try:
                ed = datetime.strptime(entry_date[:10], "%Y-%m-%d")
                ad = datetime.strptime(as_of_date[:10], "%Y-%m-%d")
                return (ad - ed).days
            except Exception:
                return 999

    def re_attach_protection(self, current_positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Check each position for active trailing-stop orders and re-attach if missing.

        Bracket orders submitted with "day" TIF expire at market close, leaving
        positions unprotected. This method detects missing trailing stops and
        submits standalone trailing stop orders to restore protection.

        Returns list of protection orders submitted.
        """
        protection_orders = []

        for pos in current_positions:
            ticker = pos["ticker"]
            qty = abs(pos["qty"])

            try:
                status = self.alpaca.get_position_protection_status(ticker)

                if status["has_sl"]:
                    logger.debug("Trailing stop already active for %s", ticker)
                    continue

                # Cancel any stale orders for this symbol before re-submitting
                for o in status["all_orders"]:
                    try:
                        self.alpaca.api.cancel_order(o["id"])
                    except Exception:
                        pass

                # Alpaca reserves the position qty while an order is open, and a
                # cancel doesn't release it instantly. Submitting immediately
                # after a cancel can fail with "insufficient qty available
                # (requested: N, available: 0)". Retry with a short delay so the
                # cancel propagates and the trailing stop actually lands.
                side = "sell" if pos["qty"] > 0 else "buy"
                order = None
                for attempt in range(3):
                    try:
                        order = self.alpaca.submit_trailing_stop(
                            symbol=ticker,
                            qty=qty,
                            side=side,
                            trail_percent=TRAILING_STOP_PCT * 100,
                        )
                        break
                    except Exception as e:
                        if attempt < 2:
                            logger.warning(
                                "Trailing stop submit for %s failed (attempt %d/3): %s — retrying",
                                ticker, attempt + 1, e,
                            )
                            time.sleep(2)
                        else:
                            raise
                protection_orders.append({
                    "ticker": ticker,
                    "qty": qty,
                    "side": "long" if pos["qty"] > 0 else "short",
                    "trail_percent": TRAILING_STOP_PCT,
                    "order_id": order["id"],
                })
                logger.info("ATTACH TRAILING STOP %s: %d shares @ %.0f%% trail (%s)",
                            ticker, qty, TRAILING_STOP_PCT * 100,
                            "long" if pos["qty"] > 0 else "short")

            except Exception as e:
                logger.error("Failed to re-attach trailing stop for %s: %s", ticker, e)

        return protection_orders

    # ── Main Pipeline ────────────────────────────────────────────────

    def run_daily(self) -> Dict[str, Any]:
        """Execute the daily long/short strategy pipeline.

        Flow:
        1. Check crisis override (SPY drawdown)
        2. Scan for long candidates (golden cross + Entry B)
        3. Scan for short candidates (death cross + bearish Entry B)
        4. Compare with current Alpaca positions
        5. Close positions that no longer belong
        6. Open new long and short positions
        """
        as_of_date = self.get_latest_date()
        logger.info("Running daily long/short strategy for %s", as_of_date)

        result = {
            "date": as_of_date,
            "status": "running",
            "long_orders_placed": [],
            "short_orders_placed": [],
            "positions_closed": [],
            "protection_attached": [],
            "errors": [],
            "crisis_mode": False,
        }

        # ── Step 1: Crisis check ──
        crisis = self.check_crisis_override(as_of_date)
        if crisis:
            logger.warning("CRISIS OVERRIDE ACTIVE — closing longs, keeping shorts")
            result["crisis_mode"] = True

        # ── Step 2: Scan longs ──
        logger.info("Scanning for golden cross signals (longs)...")
        desired_longs = self.scan_and_rank_longs(as_of_date)
        logger.info("Top %d long candidates: %s", len(desired_longs),
                     [c["ticker"] for c in desired_longs])

        # ── Step 3: Scan shorts ──
        logger.info("Scanning for death cross signals (shorts)...")
        desired_shorts = self.scan_and_rank_shorts(as_of_date)
        logger.info("Top %d short candidates: %s", len(desired_shorts),
                     [c["ticker"] for c in desired_shorts])

        # ── Step 4: Get current positions ──
        current_positions = self.alpaca.get_positions()
        current_long_tickers = {p["ticker"] for p in current_positions if p["qty"] > 0}
        current_short_tickers = {p["ticker"] for p in current_positions if p["qty"] < 0}
        desired_long_tickers = {c["ticker"] for c in desired_longs}
        desired_short_tickers = {c["ticker"] for c in desired_shorts}

        # ── Step 4b: Re-attach trailing stops on existing positions ──
        if current_positions:
            logger.info("Checking protection on %d existing positions...", len(current_positions))
            result["protection_attached"] = self.re_attach_protection(current_positions)

        # ── Step 5: Close stale positions ──
        for pos in current_positions:
            ticker = pos["ticker"]
            qty = abs(pos["qty"])

            if pos["qty"] > 0:  # Long position
                has_dc = self.check_death_cross(ticker, as_of_date)
                rotated_out = ticker not in desired_long_tickers

                if crisis:
                    should_close = True
                    reason = "Crisis Override"
                elif has_dc:
                    should_close = True
                    reason = "Death Cross"
                elif rotated_out:
                    hold_days = self._get_hold_days(ticker, as_of_date)
                    if hold_days < MIN_HOLD_DAYS:
                        logger.info("HOLD LONG %s: held %d/%d days, skipping rotation close",
                                    ticker, hold_days, MIN_HOLD_DAYS)
                        continue
                    should_close = True
                    reason = "Rotated Out"
                else:
                    should_close = False

                if should_close:
                    try:
                        self.alpaca.submit_market_order(ticker, qty, "sell")
                        result["positions_closed"].append({
                            "ticker": ticker, "qty": qty, "side": "long", "reason": reason
                        })
                        logger.info("CLOSE LONG %s: %d shares (%s)", ticker, qty, reason)
                    except Exception as e:
                        result["errors"].append(f"Failed to close long {ticker}: {e}")

            else:  # Short position (qty is negative in Alpaca)
                has_gc = self.check_golden_cross(ticker, as_of_date)
                rotated_out = ticker not in desired_short_tickers

                if has_gc:
                    should_close = True
                    reason = "Golden Cross"
                elif rotated_out:
                    hold_days = self._get_hold_days(ticker, as_of_date)
                    if hold_days < MIN_HOLD_DAYS:
                        logger.info("HOLD SHORT %s: held %d/%d days, skipping rotation close",
                                    ticker, hold_days, MIN_HOLD_DAYS)
                        continue
                    should_close = True
                    reason = "Rotated Out"
                else:
                    should_close = False

                if should_close:
                    try:
                        self.alpaca.submit_market_order(ticker, qty, "buy")  # Buy to cover
                        result["positions_closed"].append({
                            "ticker": ticker, "qty": qty, "side": "short", "reason": reason
                        })
                        logger.info("COVER SHORT %s: %d shares (%s)", ticker, qty, reason)
                    except Exception as e:
                        result["errors"].append(f"Failed to cover short {ticker}: {e}")

        # ── Step 6: Open new positions — respect MAX_HOLDINGS ──
        # Re-fetch positions to get accurate count after closes
        remaining_positions = self.alpaca.get_positions()
        remaining_long = {p["ticker"] for p in remaining_positions if p["qty"] > 0}
        remaining_short = {p["ticker"] for p in remaining_positions if p["qty"] < 0}
        long_slots = MAX_LONG_HOLDINGS - len(remaining_long)
        short_slots = MAX_SHORT_HOLDINGS - len(remaining_short)

        account = self.alpaca.get_account()
        portfolio_value = float(account["equity"])

        # Split capital: 60% long, 40% short
        long_capital = portfolio_value * 0.60
        short_capital = portfolio_value * 0.40

        # Open long positions (up to available slots)
        if long_slots <= 0:
            logger.info("Long portfolio full (%d positions), no new long entries", len(remaining_long))
        else:
            opened = 0
            for rank, candidate in enumerate(desired_longs):
                if opened >= long_slots:
                    break
                ticker = candidate["ticker"]
                if ticker in remaining_long:
                    continue
                if crisis:
                    break

                target_pct = LONG_SIZING_PCTS[rank] if rank < len(LONG_SIZING_PCTS) else 0.10
                target_value = long_capital * target_pct
                price = candidate["price"]
                qty = max(1, int(target_value / price))

                try:
                    self.alpaca.submit_bracket_order(
                        symbol=ticker,
                        qty=qty,
                        side="buy",
                        take_profit_pct=TAKE_PROFIT_PCT,
                        trailing_stop_pct=TRAILING_STOP_PCT,
                        entry_price=price,
                    )
                    result["long_orders_placed"].append({
                        "ticker": ticker, "qty": qty, "price": price,
                        "score": candidate["score"], "angle": candidate["angle"],
                        "entry_type": candidate["entry_type"],
                    })
                    logger.info("BUY  %s: %d shares @ $%.2f (score=%.2f, angle=%.4f) [slot %d/%d]",
                                ticker, qty, price, candidate["score"], candidate["angle"],
                                opened + 1, long_slots)
                    opened += 1
                except Exception as e:
                    result["errors"].append(f"Failed to buy {ticker}: {e}")

        # Open short positions (up to available slots)
        if short_slots <= 0:
            logger.info("Short portfolio full (%d positions), no new short entries", len(remaining_short))
        else:
            opened = 0
            for rank, candidate in enumerate(desired_shorts):
                if opened >= short_slots:
                    break
                ticker = candidate["ticker"]
                if ticker in remaining_short:
                    continue

                target_pct = SHORT_SIZING_PCTS[rank] if rank < len(SHORT_SIZING_PCTS) else 0.10
                target_value = short_capital * target_pct
                price = candidate["price"]
                qty = max(1, int(target_value / price))

                try:
                    self.submit_short_bracket_order(
                        symbol=ticker,
                        qty=qty,
                        entry_price=price,
                    )
                    result["short_orders_placed"].append({
                        "ticker": ticker, "qty": qty, "price": price,
                        "score": candidate["score"], "angle": candidate["angle"],
                        "entry_type": candidate["entry_type"],
                    })
                    logger.info("SHORT %s: %d shares @ $%.2f (score=%.2f, angle=%.4f) [slot %d/%d]",
                                ticker, qty, price, candidate["score"], candidate["angle"],
                                opened + 1, short_slots)
                    opened += 1
                except Exception as e:
                    result["errors"].append(f"Failed to short {ticker}: {e}")

        result["status"] = "completed"
        return result


def main():
    """Entry point for the daily long/short strategy run."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    runner = LongShortStrategyRunner()
    result = runner.run_daily()

    print(f"\n{'='*60}")
    print(f"  GOLDEN CROSS ROTATION — LONG/SHORT")
    print(f"  Date:   {result['date']}")
    print(f"  Status: {result['status']}")
    print("=" * 60)

    if result.get("crisis_mode"):
        print("  🛑 CRISIS OVERRIDE — Longs closed, shorts remain")

    print(f"\n  Long orders placed: {len(result['long_orders_placed'])}")
    for o in result["long_orders_placed"]:
        print(f"    BUY  {o['ticker']:>6}  {o['qty']:>4} shares  "
              f"score={o['score']:.2f}  angle={o['angle']:.4f}")

    print(f"\n  Short orders placed: {len(result['short_orders_placed'])}")
    for o in result["short_orders_placed"]:
        print(f"    SHORT {o['ticker']:>6}  {o['qty']:>4} shares  "
              f"score={o['score']:.2f}  angle={o['angle']:.4f}")

    print(f"\n  Positions closed: {len(result['positions_closed'])}")
    for c in result["positions_closed"]:
        print(f"    {c['side'].upper():>5} {c['ticker']:>6}  {c['qty']:>4} shares  "
              f"reason={c['reason']}")

    if result["errors"]:
        print(f"\n  Errors: {len(result['errors'])}")
        for e in result["errors"]:
            print(f"    ❌ {e}")

    print("=" * 60)
    return result


if __name__ == "__main__":
    main()
