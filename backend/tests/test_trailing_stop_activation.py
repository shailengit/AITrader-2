"""Trailing-stop activation threshold.

Motivation (MQR turnover audit, 2026-09-29): the 12% trailing stop is 50.5% of
all exits and is the binding constraint on turnover -- displacing rotation exits
via min_hold_days just handed them to the trail. A 12% trail on a position that
never got going is simply a stop loss on ordinary volatility, so the position
exits and gets re-bought: churn.

The threshold arms the trail only once the position has been up by `activation`
at its PEAK. Peak-based, not current-gain-based: the peak only rises, so once
armed it stays armed. A current-gain check would disarm on exactly the pullback
the trail exists to catch.

activation=0.0 must reproduce the previous behaviour byte-for-byte: peak_price
starts at the entry price and only rises, so peak_gain >= 0 always holds.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.strategy_backtest_adapter import trailing_stop_triggered
from app.services.strategy_base import RotationConfig


def test_rotation_config_defaults_activation_to_off():
    """Default must be a no-op so every existing strategy is unaffected."""
    assert RotationConfig().trailing_stop_activation == 0.0


def test_zero_activation_is_current_behaviour():
    """entry 100, peak 100, -12% from peak -> fires, exactly as before."""
    assert trailing_stop_triggered(100.0, 100.0, 88.0, 0.12, 0.0) is True


def test_threshold_blocks_the_stop_before_the_position_ever_runs():
    """Never profitable at peak -> unarmed, despite a 12% drawdown from peak."""
    assert trailing_stop_triggered(100.0, 100.0, 88.0, 0.12, 0.10) is False


def test_threshold_arms_once_peak_gain_clears_it():
    """Peak +20% clears a +10% activation; 12.5% off that peak fires."""
    assert trailing_stop_triggered(100.0, 120.0, 105.0, 0.12, 0.10) is True


def test_threshold_stays_unarmed_when_peak_gain_is_short():
    """Peak only +5% against a +10% activation -> still unarmed."""
    assert trailing_stop_triggered(100.0, 105.0, 92.0, 0.12, 0.10) is False


def test_peak_gain_exactly_at_the_threshold_arms():
    assert trailing_stop_triggered(100.0, 110.0, 96.8, 0.12, 0.10) is True


def test_disabled_trailing_stop_never_fires():
    assert trailing_stop_triggered(100.0, 200.0, 50.0, 0.0, 0.0) is False


def test_drawdown_just_under_the_trail_does_not_fire():
    assert trailing_stop_triggered(100.0, 100.0, 88.01, 0.12, 0.0) is False
