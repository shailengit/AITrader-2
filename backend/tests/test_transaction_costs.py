"""Transaction-cost model for the backtest adapter.

Audit context (2026-09-29): the adapter filled at the next open with NO costs --
no commission, no slippage. With ~61 exits/year and ~24x annual portfolio
turnover, that overstates returns by roughly 1.2%/yr at 5bps per side and
~4.9%/yr at 20bps, so every backtest number on this stack is optimistic.

`cost_bps` is charged PER SIDE on the filled notional. Default 0.0 reproduces
the previous behaviour exactly, so existing results stay reproducible and prior
comparisons remain valid.

Round-trip P&L must include BOTH fill costs, otherwise win rate and profit
factor stay inflated even once cash/equity are cost-adjusted.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.strategy_backtest_adapter import round_trip_pnl, trade_cost
from app.services.strategy_base import RotationConfig


def test_rotation_config_defaults_costs_to_zero():
    """Default must be a no-op: existing backtests stay reproducible."""
    assert RotationConfig().cost_bps == 0.0


def test_trade_cost_is_bps_of_notional():
    assert trade_cost(100_000.0, 5.0) == 50.0


def test_trade_cost_is_zero_when_disabled():
    assert trade_cost(100_000.0, 0.0) == 0.0


def test_trade_cost_ignores_non_positive_notional():
    """Invalid data, not a real fill -- charge nothing rather than invent a fee."""
    assert trade_cost(0.0, 5.0) == 0.0
    assert trade_cost(-100_000.0, 5.0) == 0.0


def test_round_trip_pnl_without_costs_matches_original_formula():
    """The pre-existing calculation was shares * (exit - entry)."""
    shares, entry, exit_ = 100, 100.0, 110.0
    assert round_trip_pnl(shares, entry, exit_, 0.0) == shares * (exit_ - entry)


def test_round_trip_pnl_charges_both_fills():
    """100 sh: buy 10,000, sell 11,000, 10bps/side -> fees 10 + 11 -> 979."""
    assert round_trip_pnl(100, 100.0, 110.0, 10.0) == 979.0


def test_round_trip_pnl_goes_negative_when_costs_exceed_a_thin_gain():
    """A +0.05% move on 100 shares cannot survive 20bps per side."""
    assert round_trip_pnl(100, 100.0, 100.05, 20.0) < 0


def test_costs_reduce_pnl_monotonically():
    base = round_trip_pnl(100, 100.0, 110.0, 0.0)
    assert round_trip_pnl(100, 100.0, 110.0, 5.0) < base
    assert round_trip_pnl(100, 100.0, 110.0, 10.0) < round_trip_pnl(100, 100.0, 110.0, 5.0)
