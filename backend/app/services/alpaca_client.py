"""Alpaca trading API wrapper for TradeCraft."""

import os
import logging
from typing import List, Dict, Any, Optional

import alpaca_trade_api as tradeapi

logger = logging.getLogger(__name__)


class AlpacaClient:
    """Wrapper around Alpaca trading and data APIs.

    Supports optional key prefix for multiple accounts:
        client = AlpacaClient(prefix="1")   # uses ALPACA_1_API_KEY / ALPACA_1_SECRET_KEY
        client = AlpacaClient(prefix="2")   # uses ALPACA_2_API_KEY / ALPACA_2_SECRET_KEY
    """

    def __init__(self, prefix: str = ""):
        key_suffix = f"_{prefix}" if prefix else ""

        self.api_key = os.getenv(f"ALPACA{key_suffix}_API_KEY")
        self.secret_key = os.getenv(f"ALPACA{key_suffix}_SECRET_KEY")
        self.paper = os.getenv(f"ALPACA{key_suffix}_PAPER", "true").lower() == "true"

        if not self.api_key or not self.secret_key:
            raise ValueError(
                f"ALPACA{key_suffix}_API_KEY and ALPACA{key_suffix}_SECRET_KEY must be set in .env"
            )

        base_url = "https://paper-api.alpaca.markets" if self.paper else "https://api.alpaca.markets"
        self.api = tradeapi.REST(self.api_key, self.secret_key, base_url=base_url)

    def get_account(self) -> Dict[str, Any]:
        """Get account details: equity, cash, buying power, account number."""
        account = self.api.get_account()
        return {
            "equity": float(account.equity),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "status": account.status,
            "account_number": getattr(account, "account_number", None),
        }

    def get_portfolio_history(
        self,
        period: str = "3M",
        timeframe: str = "1D",
        extended_hours: bool = False,
    ) -> Dict[str, Any]:
        """Return the account equity curve (portfolio history).

        period: "1D" | "1W" | "1M" | "3M" | "6M" | "1A" | "all"
        timeframe: "1Min" | "5Min" | "15Min" | "1H" | "1D"
        Returns {"dates": [...], "equity": [...], "profit_loss": [...]}.
        """
        try:
            ph = self.api.get_portfolio_history(
                period=period, timeframe=timeframe, extended_hours=extended_hours
            )
            return {
                "dates": list(getattr(ph, "timestamp", []) or []),
                "equity": [float(x) for x in (getattr(ph, "equity", []) or [])],
                "profit_loss": [float(x) for x in (getattr(ph, "profit_loss", []) or [])],
            }
        except Exception as e:
            logger.error("Failed to fetch portfolio history: %s", e)
            raise

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get current open positions."""
        positions = self.api.list_positions()
        return [
            {
                "ticker": p.symbol,
                "qty": int(p.qty),
                "market_value": float(p.market_value),
                "cost_basis": float(p.cost_basis),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_pl_pct": float(p.unrealized_plpc),
                "current_price": float(p.current_price),
                "avg_entry_price": float(p.avg_entry_price),
            }
            for p in positions
        ]

    def submit_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        take_profit_pct: float = 0.20,
        trailing_stop_pct: float = 0.20,
        entry_price: float = 0.0,
        limit_tolerance: float = 0.005,
    ) -> Dict[str, Any]:
        """Submit a bracket order with take profit and trailing stop.

        Uses a limit order with tolerance to avoid bad fills at market open.
        For buys: limit price = entry_price * (1 + tolerance)
        For sells: limit price = entry_price * (1 - tolerance)
        """
        if entry_price <= 0:
            raise ValueError("entry_price is required for limit bracket orders")

        limit_price = round(
            entry_price * (1 + limit_tolerance) if side == "buy"
            else entry_price * (1 - limit_tolerance),
            2,
        )

        order_kwargs = {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "type": "limit",
            "limit_price": str(limit_price),
            "time_in_force": "gtc",
            "order_class": "bracket",
        }

        # Add take profit if specified
        if take_profit_pct > 0:
            tp_price = round(entry_price * (1 + take_profit_pct), 2)
            order_kwargs["take_profit"] = {"limit_price": str(tp_price)}

        # Add trailing stop loss
        if trailing_stop_pct > 0:
            stop_price = round(entry_price * (1 - trailing_stop_pct), 2)
            order_kwargs["stop_loss"] = {
                "stop_price": str(stop_price),
                "trail_percent": str(trailing_stop_pct * 100),
            }

        order = self.api.submit_order(**order_kwargs)
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": int(order.qty),
            "side": order.side,
            "status": order.status,
            "type": order.type,
            "submitted_at": str(order.submitted_at),
        }

    def submit_market_order(self, symbol: str, qty: int, side: str) -> Dict[str, Any]:
        """Submit a simple market order (for closing positions)."""
        order = self.api.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type="market",
            time_in_force="day",
        )
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": int(order.qty),
            "side": order.side,
            "status": order.status,
        }

    def check_borrow_availability(self, symbol: str) -> Dict[str, Any]:
        """Check if a stock is shortable and easy-to-borrow.

        Returns dict with:
            shortable: bool — Alpaca allows shorting
            easy_to_borrow: bool — no special borrow fee
            borrow_rate: float | None — annualized borrow rate if available
            status: str — "active" | "inactive" | "error"
        """
        try:
            asset = self.api.get_asset(symbol)
            return {
                "shortable": getattr(asset, "shortable", False),
                "easy_to_borrow": getattr(asset, "easy_to_borrow", False),
                "borrow_rate": None,  # Alpaca doesn't expose this via get_asset
                "status": asset.status if hasattr(asset, "status") else "unknown",
            }
        except Exception as e:
            logger.debug("Borrow check failed for %s: %s", symbol, e)
            return {
                "shortable": False,
                "easy_to_borrow": False,
                "borrow_rate": None,
                "status": "error",
            }

    def get_open_orders(self, symbol: str = None) -> List[Dict[str, Any]]:
        """Get all open orders, optionally filtered by symbol.

        Returns list of dicts with order details including side, type, status.
        """
        try:
            raw = self.api.list_orders(status="open")
            orders = []
            for o in raw:
                if symbol and o.symbol != symbol:
                    continue
                orders.append({
                    "id": str(o.id),
                    "symbol": o.symbol,
                    "side": o.side,
                    "type": o.type,
                    "qty": int(o.qty),
                    "filled_qty": int(o.filled_qty or 0),
                    "limit_price": float(o.limit_price) if o.limit_price else None,
                    "stop_price": float(o.stop_price) if o.stop_price else None,
                    "trail_percent": float(o.trail_percent) if hasattr(o, "trail_percent") and o.trail_percent else None,
                    "time_in_force": o.time_in_force,
                    "order_class": o.order_class,
                    "status": o.status,
                    "submitted_at": str(o.submitted_at),
                })
            return orders
        except Exception as e:
            logger.error("Failed to list open orders: %s", e)
            return []

    def get_position_protection_status(self, symbol: str) -> Dict[str, Any]:
        """Check if a position has active take-profit and/or stop-loss orders.

        Returns:
            has_tp: bool — has an active take-profit limit order
            has_sl: bool — has an active stop-loss order (trailing or fixed)
            orders: list — the matching open orders
        """
        orders = self.get_open_orders(symbol)
        tp_orders = [o for o in orders if o["side"] in ("sell",) and o["type"] == "limit"]
        sl_orders = [o for o in orders if o["side"] in ("sell",) and o["type"] in ("stop", "trailing_stop")]
        return {
            "has_tp": len(tp_orders) > 0,
            "has_sl": len(sl_orders) > 0,
            "tp_orders": tp_orders,
            "sl_orders": sl_orders,
            "all_orders": orders,
        }

    def submit_trailing_stop(
        self,
        symbol: str,
        qty: int,
        side: str,
        trail_percent: float = 20.0,
    ) -> Dict[str, Any]:
        """Submit a standalone trailing stop order for an existing position.

        Unlike bracket/oco orders, trailing stops are submitted as simple
        stop orders with a trail percent. They follow the price as it moves
        in the favorable direction and trigger when it reverses by the
        trail percentage.

        For long positions: side="sell" (stops out if price drops)
        For short positions: side="buy" (stops out if price rises)
        """
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type="trailing_stop",
                trail_percent=str(trail_percent),
                time_in_force="gtc",
            )
            return {
                "id": str(order.id),
                "symbol": order.symbol,
                "qty": int(order.qty),
                "side": order.side,
                "status": order.status,
                "type": order.type,
                "trail_percent": float(order.trail_percent) if hasattr(order, "trail_percent") and order.trail_percent else trail_percent,
                "submitted_at": str(order.submitted_at),
            }
        except Exception as e:
            logger.error("Failed to submit trailing stop for %s: %s", symbol, e)
            raise

    def get_closed_fills(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent closed (filled) orders with fill price/date.

        Used to determine exit prices/dates when reconciling positions into the
        Coach journal. Returns most-recent-first. Only orders with a non-zero
        filled quantity are included.
        """
        try:
            raw = self.api.list_orders(status="closed", limit=limit)
            fills = []
            for o in raw:
                if symbol and o.symbol != symbol:
                    continue
                fq = getattr(o, "filled_qty", None)
                if not fq or int(fq or 0) <= 0:
                    continue
                fap = getattr(o, "filled_avg_price", None)
                fa = getattr(o, "filled_at", None)
                fills.append({
                    "symbol": o.symbol,
                    "side": o.side,
                    "qty": int(fq),
                    "filled_avg_price": float(fap) if fap else None,
                    "filled_at": str(fa) if fa else None,
                })
            return fills
        except Exception as e:
            logger.error("Failed to list closed fills: %s", e)
            return []

    def get_entry_date(self, symbol: str) -> str | None:
        """Get the entry date for a position from order history.

        Looks at the most recent filled buy order for the symbol and
        returns its filled_at date (YYYY-MM-DD). Returns None if no
        matching order is found.
        """
        try:
            orders = self.api.list_orders(
                status="closed",
                limit=100,
                after=None,
            )
            for o in orders:
                if o.symbol == symbol and o.side == "buy" and o.filled_qty and int(o.filled_qty) > 0:
                    filled_at = getattr(o, "filled_at", None)
                    if filled_at:
                        return str(filled_at)[:10]
                    submitted_at = getattr(o, "submitted_at", None)
                    if submitted_at:
                        return str(submitted_at)[:10]
            return None
        except Exception as e:
            logger.debug("Failed to get entry date for %s: %s", symbol, e)
            return None

    def cancel_all_orders(self) -> bool:
        """Cancel all open orders."""
        try:
            self.api.cancel_all_orders()
            return True
        except Exception as e:
            logger.error("Failed to cancel orders: %s", e)
            return False
