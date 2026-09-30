"""Pure exit-rule replay: mirrors strategy_backtest_adapter semantics exactly."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pandas as pd

from app.services.exit_replay.engine import (
    CURRENT_MQR_POLICY,
    ExitPolicy,
    OFF,
    replay_position,
)


def bars(rows):
    """rows: list of (date, open, high, low, close)"""
    return pd.DataFrame(
        [{"Date": pd.Timestamp(d), "Open": o, "High": h, "Low": lo, "Close": c}
         for d, o, h, lo, c in rows]
    )


def test_hard_stop_fires_at_boundary():
    p = ExitPolicy(hard_stop_loss=0.20, trailing_stop=OFF)
    b = bars([("2020-01-02", 100, 100, 80, 80),      # close -20% -> trigger
              ("2020-01-03", 79, 79, 78, 78)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.exit_reason == "Stop Loss"
    assert out.exit_date == pd.Timestamp("2020-01-02")   # trigger date
    assert out.exit_px == 79.0                            # NEXT open


def test_hard_stop_does_not_fire_just_above_boundary():
    p = ExitPolicy(hard_stop_loss=0.20, trailing_stop=OFF)
    b = bars([("2020-01-02", 100, 100, 81, 80.5), ("2020-01-03", 80, 80, 79, 79)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.exit_reason != "Stop Loss" or out.exit_date != pd.Timestamp("2020-01-02")


def test_take_profit_fires_at_boundary():
    p = ExitPolicy(take_profit=0.50, trailing_stop=OFF, hard_stop_loss=OFF)
    b = bars([("2020-01-02", 100, 151, 100, 150), ("2020-01-03", 152, 152, 150, 151)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.exit_reason == "Take Profit" and out.exit_px == 152.0


def test_trailing_activation_blocks_early_exit():
    # drop 12% from a peak that only reached entry => unarmed when activation > 0
    b = bars([("2020-01-02", 100, 100, 88, 88), ("2020-01-03", 88, 88, 87, 87)])
    armed = replay_position(100.0, pd.Timestamp("2020-01-01"), b,
                            ExitPolicy(trailing_stop=0.12, trailing_stop_activation=0.0,
                                       hard_stop_loss=OFF, take_profit=OFF))
    unarmed = replay_position(100.0, pd.Timestamp("2020-01-01"), b,
                              ExitPolicy(trailing_stop=0.12, trailing_stop_activation=0.10,
                                         hard_stop_loss=OFF, take_profit=OFF))
    assert armed.exit_reason == "Trailing Stop"
    assert unarmed.exit_reason != "Trailing Stop"


def test_time_stop_uses_calendar_days():
    p = ExitPolicy(time_stop_days=10, trailing_stop=OFF, hard_stop_loss=OFF, take_profit=OFF)
    b = bars([("2020-01-05", 100, 101, 99, 100),
              ("2020-01-11", 100, 101, 99, 100),   # exactly 10 calendar days after 01-01
              ("2020-01-20", 100, 101, 99, 100)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.exit_reason == "Time Stop"
    assert out.exit_date == pd.Timestamp("2020-01-11")
    assert out.hold_days_calendar == 10


def test_precedence_hard_stop_beats_trailing_on_same_bar():
    p = ExitPolicy(hard_stop_loss=0.20, trailing_stop=0.05,
                   trailing_stop_activation=0.0, take_profit=OFF)
    b = bars([("2020-01-02", 100, 100, 70, 70), ("2020-01-03", 70, 70, 69, 69)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.exit_reason == "Stop Loss"     # hard stop is first in precedence


def test_cap_date_ends_replay_as_rotated_out():
    p = ExitPolicy(trailing_stop=OFF, hard_stop_loss=OFF, take_profit=OFF, time_stop_days=OFF)
    b = bars([("2020-01-02", 100, 101, 99, 100), ("2020-01-06", 100, 102, 99, 101)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p,
                          cap_date=pd.Timestamp("2020-01-06"))
    assert out.exit_reason == "Rotated Out"
    assert out.exit_date == pd.Timestamp("2020-01-06")


def test_observed_fully_false_when_window_ends_without_exit():
    p = ExitPolicy(trailing_stop=OFF, hard_stop_loss=OFF, take_profit=OFF, time_stop_days=OFF)
    b = bars([("2020-01-02", 100, 101, 99, 100), ("2020-01-03", 100, 101, 99, 100)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.observed_fully is False
    assert out.exit_reason == "Window End"


def test_mae_mfe_recorded():
    p = ExitPolicy(trailing_stop=OFF, hard_stop_loss=OFF, take_profit=OFF, time_stop_days=OFF)
    b = bars([("2020-01-02", 100, 120, 90, 110), ("2020-01-03", 110, 115, 105, 108)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.mfe == 0.20 and out.mae == -0.10


def test_current_mqr_policy_matches_live_constants():
    assert CURRENT_MQR_POLICY.hard_stop_loss == 0.20
    assert CURRENT_MQR_POLICY.trailing_stop == 0.12
    assert CURRENT_MQR_POLICY.trailing_stop_activation == 0.0
    assert CURRENT_MQR_POLICY.take_profit == 0.50
    assert CURRENT_MQR_POLICY.time_stop_days == 120
