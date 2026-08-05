"""Unit tests for the Sector Scanner Top-5 Rotation strategy.

Covers the pure, DB-free logic: sigmoid momentum scoring, the 90-day
perf / 14-day vol computation, and the rotation/risk configuration that
must match the strategy spec (docs/strategies/sector-scanner-top5-rotation-spec.md).

The full backtest (adapter.run) is exercised separately; these tests pin
the deterministic helpers and the risk contract so a refactor can't
silently change behavior.
"""
import numpy as np
import pandas as pd

from app.services.strategies.sector_scanner_top5_rotation import (
    SectorScannerTop5Rotation,
    MAX_HOLDINGS,
    MIN_HOLD_DAYS,
    HARD_STOP,
    MAX_SECTOR_COUNT,
    MAX_VOLATILITY,
    MIN_MARKET_CAP,
)


def _strategy():
    return SectorScannerTop5Rotation()


# ── Identity / contract ───────────────────────────────────────────────

def test_name_and_holdings():
    s = _strategy()
    assert s.get_name() == "Sector Scanner Top-5 Rotation"
    assert s.max_holdings == MAX_HOLDINGS == 5
    assert sum(s.sizing_pcts) == 1.0


def test_rotation_config_matches_spec():
    """The risk contract must match the spec exactly."""
    cfg = _strategy().get_rotation_config()
    assert cfg.sizing_method == "linear"          # momentum-proportional
    assert cfg.hard_stop_loss == HARD_STOP == 0.20
    assert cfg.trailing_stop == 0.0               # disabled
    assert cfg.take_profit == 0.0                 # disabled
    assert cfg.time_stop_days == 0                # rotation is the primary exit
    assert cfg.min_hold_days == MIN_HOLD_DAYS == 14
    assert cfg.max_sector_count == MAX_SECTOR_COUNT == 2
    assert cfg.re_score_holdings is True          # re-compete on current momentum
    assert cfg.bear_exposure == 1.0               # no bear-market cash mode
    assert cfg.exit_priority == ["hard_stop_loss"]


def test_should_exit_is_empty():
    """No strategy-specific exit — rotation + hard stop live in the adapter."""
    ec = _strategy().should_exit("AAPL", "2024-01-01", None)
    assert ec.should_close is False
    assert ec.reason == ""


# ── Sigmoid momentum score ───────────────────────────────────────────

def test_sigmoid_score_is_monotonic_and_bounded():
    s = _strategy()
    scores = [s._sigmoid_score(x) for x in (-0.5, -0.1, 0.0, 0.1, 0.5)]
    # Strictly increasing with perf_3m.
    assert scores == sorted(scores)
    assert all(0.0 < sc < 1.0 for sc in scores)
    # Center point: zero momentum maps to 0.5.
    assert abs(s._sigmoid_score(0.0) - 0.5) < 1e-9
    # Positive momentum scores above 0.5, negative below.
    assert s._sigmoid_score(0.1) > 0.5
    assert s._sigmoid_score(-0.1) < 0.5


# ── 90-day perf + 14-day vol ─────────────────────────────────────────

def test_perf3m_and_vol_flat_series():
    """Constant prices -> zero 90-day perf and zero volatility."""
    dates = pd.date_range("2023-01-01", periods=120, freq="D").to_numpy()
    close = np.full(120, 100.0)
    perf3m, vol14 = _strategy()._perf3m_and_vol(dates, close)
    assert np.allclose(perf3m[90:], 0.0, atol=1e-9)
    assert np.allclose(vol14[15:], 0.0, atol=1e-9)


def test_perf3m_captures_90_day_return():
    """A +10% move over the 90-day lookback must surface in perf_3m."""
    s = _strategy()
    dates = pd.date_range("2023-01-01", periods=120, freq="D").to_numpy()
    close = np.full(120, 100.0)
    close[90:] = 110.0  # +10% from day 90 onward
    perf3m, _ = s._perf3m_and_vol(dates, close)
    # At the last bar, the 90-day lookback lands before the jump -> +10%.
    assert abs(perf3m[-1] - 0.10) < 1e-6


def test_vol14_measures_volatility():
    """Alternating prices produce non-zero 14-day vol; flat tail is zero."""
    s = _strategy()
    dates = pd.date_range("2023-01-01", periods=120, freq="D").to_numpy()
    close = np.full(120, 100.0)
    close[20:60] = np.where(np.arange(40) % 2 == 0, 100.0, 105.0)  # choppy window
    _, vol14 = s._perf3m_and_vol(dates, close)
    assert vol14[20:60].max() > 0.0
    assert vol14[-1] == 0.0  # flat after the choppy window


# ── Filter constants ─────────────────────────────────────────────────

def test_filter_constants_match_spec():
    assert MAX_VOLATILITY == 0.05
    assert MIN_MARKET_CAP == 5e9
