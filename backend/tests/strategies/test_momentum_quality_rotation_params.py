"""Parameterization tests for Momentum Quality Rotation (MQR).

The sweep harness needs to vary one lever at a time (min_hold_days and friends)
without editing the module between runs. MQR previously read module constants
directly, so a sweep was impossible without file edits.

Defaults are pinned: the verified 100-run baseline (269 trades/run, Sharpe 1.58)
was measured against exactly these values, so an override must never move them.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.strategies.momentum_quality_rotation import MomentumQualityRotation


def test_defaults_match_the_verified_baseline():
    """The exact values the 100-run baseline was measured against."""
    cfg = MomentumQualityRotation().get_rotation_config()
    assert cfg.min_hold_days == 14
    assert cfg.hard_stop_loss == 0.20
    assert cfg.trailing_stop == 0.12
    assert cfg.trailing_stop_activation == 0.0  # armed from entry = baseline
    assert cfg.take_profit == 0.50
    assert cfg.time_stop_days == 120
    assert cfg.bear_exposure == 0.50
    assert cfg.protect_winners is True
    assert cfg.re_score_holdings is True


def test_min_hold_days_override_is_applied():
    cfg = MomentumQualityRotation(min_hold_days=28).get_rotation_config()
    assert cfg.min_hold_days == 28


def test_override_does_not_disturb_other_defaults():
    cfg = MomentumQualityRotation(min_hold_days=21).get_rotation_config()
    assert cfg.trailing_stop == 0.12
    assert cfg.take_profit == 0.50
    assert cfg.bear_exposure == 0.50


def test_unknown_override_is_rejected():
    """A typo'd sweep key must fail loudly, not silently re-test the baseline."""
    with pytest.raises(TypeError):
        MomentumQualityRotation(min_hold_dayz=21)
