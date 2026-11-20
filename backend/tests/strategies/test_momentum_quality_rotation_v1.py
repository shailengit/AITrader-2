"""MQR_V1: the deployed version of the one exit lever that survived the sweep.

V1 = MQR's engine and exits, with the trailing stop held off for the first 7
calendar days. Everything else is unchanged, and the default rotation config
must stay untouched so existing strategies behave exactly as before.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from app.services.strategies.momentum_quality_rotation import MomentumQualityRotation
from app.services.strategies.momentum_quality_rotation_v1 import (
    TRAILING_STOP_MIN_HOLD_DAYS,
    MomentumQualityRotationV1,
)
from app.services.strategy_base import RotationConfig
from app.services.strategy_backtest_adapter import trailing_stop_armed


def test_the_rotation_config_default_keeps_the_old_behaviour():
    assert RotationConfig().trailing_stop_min_hold_days == 0
    assert MomentumQualityRotation().get_rotation_config().trailing_stop_min_hold_days == 0


def test_the_armed_helper_uses_calendar_days_and_tolerates_off():
    assert trailing_stop_armed(hold_days=0, min_hold_days=0) is True
    assert trailing_stop_armed(hold_days=6, min_hold_days=7) is False
    assert trailing_stop_armed(hold_days=7, min_hold_days=7) is True
    assert trailing_stop_armed(hold_days=3, min_hold_days=0) is True


def test_v1_arms_the_trail_after_seven_days():
    cfg = MomentumQualityRotationV1().get_rotation_config()
    assert cfg.trailing_stop_min_hold_days == TRAILING_STOP_MIN_HOLD_DAYS == 7
    # Everything else is inherited unchanged from MQR.
    mqr = MomentumQualityRotation().get_rotation_config()
    for field in ("trailing_stop", "trailing_stop_activation", "take_profit",
                  "time_stop_days", "min_hold_days", "max_sector_count",
                  "protect_winners", "bear_exposure", "exit_priority",
                  "sizing_method", "hard_stop_loss"):
        assert getattr(cfg, field) == getattr(mqr, field), field


def test_v1_names_itself_distinctly():
    assert MomentumQualityRotationV1().get_name() != MomentumQualityRotation().get_name()
    assert "V1" in MomentumQualityRotationV1().get_name()


def test_v1_inherits_the_signal_engine_unchanged():
    assert (MomentumQualityRotationV1.precompute_signals
            is MomentumQualityRotation.precompute_signals)
    assert (MomentumQualityRotationV1.get_signals
            is MomentumQualityRotation.get_signals)


def test_v1_is_still_sweepable_and_rejects_typos():
    assert MomentumQualityRotationV1(
        trailing_stop_min_hold_days=10).get_rotation_config().trailing_stop_min_hold_days == 10
    with pytest.raises(TypeError):
        MomentumQualityRotationV1(not_a_real_knob=1)
