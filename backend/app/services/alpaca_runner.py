"""Generic Alpaca strategy runner — executes any Strategy implementation.

The runner handles all execution, risk management, and Alpaca integration.
The strategy (injected via constructor) answers only two questions:
1. What should I buy/sell?  (get_signals)
2. When should I exit?      (should_exit)

Usage:
    from app.services.strategies.golden_cross_rotation_v2 import GoldenCrossRotationV2
    runner = StrategyRunner(GoldenCrossStrategy())
    result = runner.run_daily()
"""

import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from app.services.alpaca_client import AlpacaClient
from app.services.strategy_base import Strategy, Signal, ExitCheck

logger = logging.getLogger(__name__)

# Runner-level parameters (shared across all strategies)
MIN_HOLD_DAYS = 10
TRAILING_STOP_PCT = 0.20
TAKE_PROFIT_PCT = 0.20
CRISIS_DRAWDOWN = 0.20


class StrategyRunner:
    """Generic daily strategy runner that connects any Strategy to Alpaca."""

    def __init__(self, strategy: Strategy):
        self.strategy = strategy
        self.alpaca = AlpacaClient()
        self.db_url = (
            f"postgresql://{os.getenv('DB_USER', 'postgres')}:"
            f"{os.getenv('DB_PASSWORD')}@"
            f"{os.getenv('DB_HOST', '127.0.0.1')}:"
            f"{os.getenv('DB_PORT', '5431')}/"
            f"{os.getenv('DB_NAME', 'sp1500_1d')}"
        )
        self.engine = create_engine(self.db_url)

    # ── DB Helpers ─────────────────────────────────────────────────────

    def get_latest_date(self) -> str:
        """Get the latest trading date from the database."""
        with self.engine.connect() as conn:
            result = conn.execute(text('SELECT MAX("Date") FROM aapl')).scalar()
            return str(result)[:10] if result else datetime.now().strftime("%Y-%m-%d")

    # ── Risk Management ───────────────────────────────────────────────

    def check_crisis_override(self, as_of_date: str) -> bool:
        """Check if SPY has dropped >20% from its 200-day high."""
        try:
            with self.engine.connect() as conn:
                spy = pd.read_sql(
                    f'SELECT "Date", "Close" FROM spy WHERE "Date" <= \'{as_of_date}\' '
                    f'ORDER BY "Date" DESC LIMIT 200',
                    conn,
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

    # ── Protection ─────────────────────────────────────────────────────

    def re_attach_protection(self, current_positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Check each position for active trailing-stop orders and re-attach if missing."""
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

                order = self.alpaca.submit_trailing_stop(
                    symbol=ticker,
                    qty=qty,
                    side="sell",
                    trail_percent=TRAILING_STOP_PCT * 100,
                )
                protection_orders.append({
                    "ticker": ticker,
                    "qty": qty,
                    "trail_percent": TRAILING_STOP_PCT,
                    "order_id": order["id"],
                })
                logger.info("ATTACH TRAILING STOP %s: %d shares @ %.0f%% trail",
                            ticker, qty, TRAILING_STOP_PCT * 100)

            except Exception as e:
                logger.error("Failed to re-attach trailing stop for %s: %s", ticker, e)

        return protection_orders

    # ── Hold Days ──────────────────────────────────────────────────────

    def _get_hold_days(self, ticker: str, as_of_date: str) -> int:
        """Estimate how many trading days a position has been held."""
        entry_date = self.alpaca.get_entry_date(ticker)
        if not entry_date:
            return 999  # Unknown age — don't force-close

        try:
            from app.utils.security import get_safe_table_name
            safe = get_safe_table_name(ticker)
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(f'SELECT COUNT(*) FROM "{safe}" '
                         f'WHERE "Date" > \'{entry_date}\' AND "Date" <= \'{as_of_date}\'')
                ).scalar()
                return int(row) if row else 0
        except Exception:
            try:
                ed = datetime.strptime(entry_date[:10], "%Y-%m-%d")
                ad = datetime.strptime(as_of_date[:10], "%Y-%m-%d")
                return (ad - ed).days
            except Exception:
                return 999

    # ── Main Pipeline ──────────────────────────────────────────────────

    def run_daily(self) -> Dict[str, Any]:
        """Execute the daily strategy pipeline."""
        as_of_date = self.get_latest_date()
        logger.info("Running %s strategy for %s", self.strategy.get_name(), as_of_date)

        result = {
            "date": as_of_date,
            "status": "running",
            "strategy": self.strategy.get_name(),
            "orders_placed": [],
            "positions_closed": [],
            "protection_attached": [],
            "errors": [],
            "crisis_mode": False,
        }

        # ── Step 1: Crisis override ──
        if self.check_crisis_override(as_of_date):
            logger.warning("CRISIS OVERRIDE ACTIVE — going to cash")
            result["crisis_mode"] = True
            positions = self.alpaca.get_positions()
            for pos in positions:
                try:
                    self.alpaca.submit_market_order(pos["ticker"], pos["qty"], "sell")
                    result["positions_closed"].append({
                        "ticker": pos["ticker"], "qty": pos["qty"], "reason": "Crisis Override",
                    })
                except Exception as e:
                    result["errors"].append(f"Failed to close {pos['ticker']}: {e}")
            result["status"] = "completed_crisis"
            return result

        # ── Step 2: Get signals from strategy ──
        logger.info("Generating signals via %s...", self.strategy.get_name())
        signals = self.strategy.get_signals(as_of_date, self.engine)
        logger.info("Top %d signals: %s", len(signals), [s.ticker for s in signals])

        if not signals:
            result["status"] = "no_candidates"
            return result

        # ── Step 3: Get current positions ──
        current_positions = self.alpaca.get_positions()
        current_tickers = {p["ticker"] for p in current_positions}
        signal_tickers = {s.ticker for s in signals}

        # ── Step 4: Re-attach protection ──
        if current_positions:
            logger.info("Checking protection on %d existing positions...", len(current_positions))
            result["protection_attached"] = self.re_attach_protection(current_positions)

        # ── Step 5: Close positions that should exit ──
        for pos in current_positions:
            ticker = pos["ticker"]
            side = "long" if pos["qty"] > 0 else "short"

            # Ask the strategy if this position should exit
            exit_check = self.strategy.should_exit(ticker, as_of_date, self.engine, side)
            rotated_out = ticker not in signal_tickers

            if rotated_out and not exit_check.should_close:
                # Enforce minimum hold days before closing for rotation
                hold_days = self._get_hold_days(ticker, as_of_date)
                if hold_days < MIN_HOLD_DAYS:
                    logger.info("HOLD %s: held %d/%d days, skipping rotation close",
                                ticker, hold_days, MIN_HOLD_DAYS)
                    continue
                exit_check = ExitCheck(should_close=True, reason="Rotated Out")

            if exit_check.should_close:
                try:
                    close_side = "sell" if side == "long" else "buy"
                    self.alpaca.submit_market_order(ticker, abs(pos["qty"]), close_side)
                    result["positions_closed"].append({
                        "ticker": ticker, "qty": abs(pos["qty"]),
                        "reason": exit_check.reason,
                    })
                    logger.info("CLOSE %s: %d shares (%s)", ticker, abs(pos["qty"]), exit_check.reason)
                except Exception as e:
                    result["errors"].append(f"Failed to close {ticker}: {e}")

        # ── Step 6: Open new positions ──
        remaining_positions = self.alpaca.get_positions()
        remaining_tickers = {p["ticker"] for p in remaining_positions}
        slots_available = self.strategy.max_holdings - len(remaining_positions)

        if slots_available <= 0:
            logger.info("Portfolio full (%d positions), no new entries", len(remaining_positions))
        else:
            account = self.alpaca.get_account()
            portfolio_value = float(account["equity"])
            sizing = self.strategy.sizing_pcts

            opened = 0
            for rank, signal in enumerate(signals):
                if opened >= slots_available:
                    break

                if signal.ticker in remaining_tickers:
                    continue

                target_pct = sizing[rank] if rank < len(sizing) else 0.10
                target_value = portfolio_value * target_pct
                qty = max(1, int(target_value / signal.price))

                try:
                    self.alpaca.submit_bracket_order(
                        symbol=signal.ticker,
                        qty=qty,
                        side="buy" if signal.side == "long" else "sell",
                        take_profit_pct=TAKE_PROFIT_PCT,
                        trailing_stop_pct=TRAILING_STOP_PCT,
                        entry_price=signal.price,
                    )
                    result["orders_placed"].append({
                        "ticker": signal.ticker, "qty": qty, "price": signal.price,
                        "score": signal.score, "angle": signal.angle,
                        "entry_type": signal.entry_type,
                    })
                    logger.info(
                        "BUY %s: %d shares @ ~$%.2f (score=%.2f, angle=%.4f) [slot %d/%d]",
                        signal.ticker, qty, signal.price, signal.score, signal.angle,
                        opened + 1, slots_available,
                    )
                    opened += 1
                except Exception as e:
                    result["errors"].append(f"Failed to buy {signal.ticker}: {e}")

        result["status"] = "completed"
        return result


def _load_active_strategy_class() -> Strategy:
    """Load the active strategy from the deployments registry.

    Falls back to the default Golden Cross strategy when the registry has no
    active deployment, so the production cron keeps working.
    """
    from importlib.util import spec_from_file_location, module_from_spec

    from app.services.deployments_registry import get_active_deployment
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        d = get_active_deployment(db)
        if d is None:
            from app.services.strategies.golden_cross_rotation_v2 import GoldenCrossRotationV2
            return GoldenCrossRotationV2()

        path = d.strategy_path
        spec = spec_from_file_location("active_strategy", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not create import spec for {path}")
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Find the Strategy subclass exported by the file
        cls = None
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy:
                cls = obj
                break
        if cls is None:
            raise ImportError(f"No Strategy subclass found in {path}")
        return cls()
    finally:
        db.close()


def main():
    """Entry point — runs the active strategy (default Golden Cross if none deployed)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    strategy = _load_active_strategy_class()
    runner = StrategyRunner(strategy)
    result = runner.run_daily()

    print(f"\n{'='*60}")
    print(f"  {strategy.get_name()} — DAILY RUN")
    print(f"  Date:   {result['date']}")
    print(f"  Status: {result['status']}")
    print("=" * 60)

    if result.get("crisis_mode"):
        print("  🛑 CRISIS OVERRIDE — All positions closed, staying in cash")
    else:
        print(f"  Orders placed: {len(result['orders_placed'])}")
        for o in result["orders_placed"]:
            print(f"    BUY  {o['ticker']:>6}  {o['qty']:>4} shares  "
                  f"score={o['score']:.2f}  angle={o['angle']:.4f}")

        print(f"  Positions closed: {len(result['positions_closed'])}")
        for c in result["positions_closed"]:
            print(f"    SELL {c['ticker']:>6}  {c['qty']:>4} shares  reason={c['reason']}")

    if result["errors"]:
        print(f"  Errors: {len(result['errors'])}")
        for e in result["errors"]:
            print(f"    ❌ {e}")

    print("=" * 60)
    return result


if __name__ == "__main__":
    main()
