"""Alpaca bracket legs are `held`, not `open`, so they are invisible to a
status="open" query.

Consequence if unfixed: `get_position_protection_status` reports has_sl=False for
a position that IS protected, and the runner then attaches a duplicate stop --
and, with a postponed trailing stop, a duplicate fixed stop every time.
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.alpaca_client import AlpacaClient


class _Order:
    def __init__(self, oid, symbol, side, type_, status, qty=10, stop_price=None,
                 limit_price=None, trail_percent=None):
        self.id = oid
        self.symbol = symbol
        self.side = side
        self.type = type_
        self.status = status
        self.qty = str(qty)
        self.filled_qty = "10"
        self.stop_price = stop_price
        self.limit_price = limit_price
        self.trail_percent = trail_percent
        self.time_in_force = "gtc"
        self.order_class = "bracket"
        self.submitted_at = "2026-11-13T00:00:00Z"


class _Api:
    def __init__(self, orders):
        self._orders = orders
        self.calls = []

    def list_orders(self, status="open", limit=None):
        self.calls.append(status)
        if status == "open":
            return [o for o in self._orders if o.status == "new"]
        return list(self._orders)


def _client(orders):
    c = AlpacaClient.__new__(AlpacaClient)
    c.api = _Api(orders)
    return c


def test_a_held_bracket_stop_counts_as_protection():
    c = _client([_Order("s1", "AAA", "sell", "stop", "held", stop_price=80.0)])
    st = c.get_position_protection_status("AAA")
    assert st["has_sl"] is True
    assert [o["type"] for o in st["sl_orders"]] == ["stop"]


def test_a_held_trailing_stop_also_counts():
    c = _client([_Order("t1", "AAA", "sell", "trailing_stop", "held",
                        trail_percent=12.0)])
    assert c.get_position_protection_status("AAA")["has_sl"] is True


def test_cancelled_legs_do_not_count():
    c = _client([_Order("x1", "AAA", "sell", "stop", "canceled")])
    assert c.get_position_protection_status("AAA")["has_sl"] is False


def test_the_default_open_order_query_is_unchanged():
    c = _client([_Order("s1", "AAA", "sell", "stop", "held")])
    assert c.get_open_orders("AAA") == []
    assert c.api.calls[0] == "open"


def test_protection_status_also_sees_new_orders():
    c = _client([_Order("t1", "AAA", "sell", "trailing_stop", "new")])
    st = c.get_position_protection_status("AAA")
    assert st["has_sl"] is True and st["has_tp"] is False
