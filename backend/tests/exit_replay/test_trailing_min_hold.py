"""A trailing stop that is not armed until the position is old enough.

This is the one exit lever that survived the 100-start sweep. It must behave
identically in the research replay, the backtest adapter and the live runner,
so the semantics are pinned here first.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.exit_replay.engine import (  # noqa: E402
    CURRENT_MQR_POLICY,
    OFF,
    ExitPolicy,
    replay_position,
)


def _bars():
    """Rise to 110, then fall hard enough to trip a 12% trail from day 3."""
    closes = [100, 105, 110, 96, 90, 85, 80, 75, 70, 65, 60, 55]
    dates = pd.date_range("2020-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({
        "Date": dates,
        "Open": closes,
        "High": [c * 1.01 for c in closes],
        "Low": [c * 0.99 for c in closes],
        "Close": closes,
    })


def _policy(**over):
    base = dict(hard_stop_loss=OFF, trailing_stop=0.12, take_profit=OFF,
                time_stop_days=0)
    base.update(over)
    return ExitPolicy(**base)


def test_the_default_policy_still_arms_the_trail_immediately():
    assert ExitPolicy().trailing_stop_min_hold_days == 0
    assert CURRENT_MQR_POLICY.trailing_stop_min_hold_days == 0


def test_the_trail_fires_on_day_three_without_a_minimum_age():
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), _bars(), _policy())
    assert out.exit_reason == "Trailing Stop"
    assert out.exit_date == pd.Timestamp("2020-01-04")      # index 3
    assert out.hold_days_calendar == 3


def test_a_seven_day_minimum_holds_the_position_through_the_early_drop():
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), _bars(),
                          _policy(trailing_stop_min_hold_days=7))
    assert out.exit_reason == "Trailing Stop"
    assert out.exit_date == pd.Timestamp("2020-01-08")      # index 7, first legal day
    assert out.hold_days_calendar == 7


def test_the_minimum_does_not_suppress_other_exit_rules():
    # A 20% hard stop must still fire inside the protected window.
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), _bars(),
                          _policy(hard_stop_loss=0.20,
                                  trailing_stop_min_hold_days=7))
    assert out.exit_reason == "Stop Loss"
    assert out.hold_days_calendar < 7


def test_a_minimum_longer_than_the_window_can_censor_the_exit():
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), _bars(),
                          _policy(trailing_stop_min_hold_days=99))
    assert out.exit_reason == "Window End"
    assert out.observed_fully is False
