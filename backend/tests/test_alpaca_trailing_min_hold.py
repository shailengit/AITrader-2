"""Live/paper parity for 'no trailing stop before N days'.

The backtest and the replay engine both gate the trail on position age. The
Alpaca runner must do the same, and it must not silently leave a young position
with NO stop at all while the trail is postponed.
"""
import os
import sys
import types
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.services.alpaca_client import AlpacaClient
from app.services.alpaca_runner import StrategyRunner
from app.services.strategy_base import ExitCheck, RotationConfig, Strategy


class _FakeStrategy(Strategy):
    def __init__(self, cfg=None):
        self._cfg = cfg or RotationConfig()

    def get_name(self):
        return "FakeV1"

    def get_signals(self, as_of_date, engine):
        return []

    def should_exit(self, ticker, as_of_date, engine, side="long"):
        return ExitCheck()

    @property
    def max_holdings(self):
        return 5

    @property
    def sizing_pcts(self):
        return [0.2, 0.2, 0.2, 0.2, 0.2]

    def get_rotation_config(self):
        return self._cfg


class _ProtectionAlpaca:
    def __init__(self, status):
        self._status = status
        self.trailing = []
        self.fixed = []
        self.cancelled = []
        self.api = types.SimpleNamespace(
            cancel_order=lambda oid: self.cancelled.append(oid))

    def get_position_protection_status(self, ticker):
        return self._status

    def submit_trailing_stop(self, **kw):
        self.trailing.append(kw)
        return {"id": "trail-1"}

    def submit_stop_loss(self, **kw):
        self.fixed.append(kw)
        return {"id": "stop-1"}


def _status(sl_orders=(), all_orders=None):
    return {"has_sl": bool(sl_orders),
            "sl_orders": list(sl_orders),
            "all_orders": list(all_orders if all_orders is not None else sl_orders)}


def _runner(cfg, alpaca):
    r = StrategyRunner(_FakeStrategy(cfg))
    r.alpaca = alpaca
    return r


def test_the_runner_reads_the_minimum_age_from_the_strategy():
    r = StrategyRunner(_FakeStrategy(RotationConfig(
        trailing_stop=0.12, hard_stop_loss=0.20,
        trailing_stop_min_hold_days=7)))
    assert r.trailing_stop_min_hold_days == 7


def test_a_young_position_keeps_its_fixed_stop_and_gets_no_trail(monkeypatch):
    alpaca = _ProtectionAlpaca(_status([{"id": "s1", "type": "stop"}]))
    r = _runner(RotationConfig(trailing_stop=0.12, hard_stop_loss=0.20,
                               trailing_stop_min_hold_days=7), alpaca)
    monkeypatch.setattr(r, "_get_hold_calendar_days", lambda t, d: 3)
    r.re_attach_protection([{"ticker": "AAA", "qty": 10}], "2024-06-08")
    assert alpaca.trailing == []
    assert alpaca.cancelled == []


def test_a_young_position_with_no_stop_gets_a_fixed_hard_stop(monkeypatch):
    alpaca = _ProtectionAlpaca(_status([]))
    r = _runner(RotationConfig(trailing_stop=0.12, hard_stop_loss=0.20,
                               trailing_stop_min_hold_days=7), alpaca)
    monkeypatch.setattr(r, "_get_hold_calendar_days", lambda t, d: 2)
    r.re_attach_protection(
        [{"ticker": "AAA", "qty": 10, "avg_entry_price": 100.0}], "2024-06-08")
    assert alpaca.trailing == []
    assert len(alpaca.fixed) == 1
    assert alpaca.fixed[0]["symbol"] == "AAA"
    assert alpaca.fixed[0]["stop_price"] == pytest.approx(80.0)


def test_an_old_enough_position_swaps_the_fixed_stop_for_the_trail(monkeypatch):
    alpaca = _ProtectionAlpaca(_status([{"id": "s1", "type": "stop"}]))
    r = _runner(RotationConfig(trailing_stop=0.12, hard_stop_loss=0.20,
                               trailing_stop_min_hold_days=7), alpaca)
    monkeypatch.setattr(r, "_get_hold_calendar_days", lambda t, d: 9)
    r.re_attach_protection([{"ticker": "AAA", "qty": 10}], "2024-06-08")
    assert alpaca.cancelled == ["s1"]
    assert alpaca.trailing and alpaca.trailing[0]["trail_percent"] == pytest.approx(12.0)


def test_an_old_position_that_already_trails_is_left_alone(monkeypatch):
    alpaca = _ProtectionAlpaca(_status([{"id": "t1", "type": "trailing_stop"}]))
    r = _runner(RotationConfig(trailing_stop=0.12,
                               trailing_stop_min_hold_days=7), alpaca)
    monkeypatch.setattr(r, "_get_hold_calendar_days", lambda t, d: 30)
    r.re_attach_protection([{"ticker": "AAA", "qty": 10}], "2024-06-08")
    assert alpaca.trailing == [] and alpaca.cancelled == []


def test_without_a_minimum_the_old_behaviour_is_unchanged(monkeypatch):
    alpaca = _ProtectionAlpaca(_status([]))
    r = _runner(RotationConfig(trailing_stop=0.12, trailing_stop_min_hold_days=0),
                alpaca)
    r.re_attach_protection([{"ticker": "AAA", "qty": 10}])
    assert alpaca.trailing and alpaca.trailing[0]["trail_percent"] == pytest.approx(12.0)


def test_calendar_days_since_entry(monkeypatch):
    alpaca = types.SimpleNamespace(get_entry_date=lambda t: "2024-06-01")
    r = _runner(RotationConfig(), alpaca)
    assert r._get_hold_calendar_days("AAA", "2024-06-08") == 7


class _OrderApi:
    def __init__(self):
        self.kwargs = None

    def submit_order(self, **kw):
        self.kwargs = kw
        return types.SimpleNamespace(
            id="o1", symbol=kw["symbol"], qty=str(kw["qty"]), side=kw["side"],
            status="new", type=kw["type"], limit_price=kw.get("limit_price"),
            submitted_at=datetime.now())


def test_a_bracket_can_carry_a_fixed_stop_instead_of_a_trailing_one():
    client = AlpacaClient.__new__(AlpacaClient)
    client.api = _OrderApi()
    client.submit_bracket_order(symbol="AAA", qty=10, side="buy",
                                take_profit_pct=0.5, trailing_stop_pct=0.0,
                                hard_stop_pct=0.20, entry_price=100.0)
    stop = client.api.kwargs["stop_loss"]
    assert stop["stop_price"] == "80.0"
    assert "trail_percent" not in stop


def test_a_bracket_still_supports_a_trailing_stop_when_asked():
    client = AlpacaClient.__new__(AlpacaClient)
    client.api = _OrderApi()
    client.submit_bracket_order(symbol="AAA", qty=10, side="buy",
                                take_profit_pct=0.5, trailing_stop_pct=0.12,
                                entry_price=100.0)
    stop = client.api.kwargs["stop_loss"]
    assert stop["trail_percent"] == "12.0"
