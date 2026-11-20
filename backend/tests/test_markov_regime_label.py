"""The bull state must be identified from the fit, not assumed to be state 1.

statsmodels labels the two Markov regimes arbitrarily per series. The old code
took the last probability column as "bull", so any sector whose higher-return
state happened to be fitted first was reported inverted -- live examples were
XLK (true state mean +3.37%/20d on state 0) and XLP.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.markov.regime_model import (  # noqa: E402
    JumpModel,
    SectorRegimeManager,
    identify_bull_state,
)


def _probs(rows):
    return np.array(rows, dtype=float)


# ── the selector itself ────────────────────────────────────────────────

def test_bull_state_is_the_higher_mean_state_even_when_it_is_state_zero():
    obs = np.array([0.03, 0.04, 0.02, 0.05, -0.01, -0.02, 0.00, -0.03])
    probs = _probs([[0.9, 0.1]] * 4 + [[0.1, 0.9]] * 4)
    assert identify_bull_state(obs, probs) == 0


def test_bull_state_is_state_one_when_state_one_has_the_higher_mean():
    obs = np.array([-0.01, -0.02, 0.00, -0.03, 0.03, 0.04, 0.02, 0.05])
    probs = _probs([[0.9, 0.1]] * 4 + [[0.1, 0.9]] * 4)
    assert identify_bull_state(obs, probs) == 1


def test_identical_means_fall_back_to_the_calmer_state():
    # Same mean, visibly different dispersion: the low-variance state is "bull".
    obs = np.array([0.01, 0.01, 0.01, 0.01, 0.01, -0.09, 0.11, 0.01])
    probs = _probs([[0.9, 0.1]] * 4 + [[0.1, 0.9]] * 4)
    assert identify_bull_state(obs, probs) == 0


def test_a_state_that_never_wins_does_not_break_the_selector():
    obs = np.array([0.01, 0.02, 0.03])
    probs = _probs([[0.9, 0.1]] * 3)
    assert identify_bull_state(obs, probs) == 0


# ── end to end through the fit ────────────────────────────────────────

def _features(first_mean, second_mean, n=400, seed=7):
    rng = np.random.default_rng(seed)
    half = n // 2
    obs = np.concatenate([
        rng.normal(first_mean, 0.004, half),
        rng.normal(second_mean, 0.004, n - half),
    ])
    return pd.DataFrame(
        {"log_return_20d": obs},
        index=pd.bdate_range("2020-01-01", periods=n),
    )


def test_a_series_ending_in_its_negative_state_reports_bear():
    """The high-return block is FIRST, so its fitted index varies by run -- the
    label must follow the means rather than the column order."""
    m = JumpModel("TEST")
    assert m.train(_features(first_mean=+0.03, second_mean=-0.015))
    assert m.bull_state is not None

    regime = m.get_regime()
    assert regime["regime"] == "BEAR"
    assert regime["bull_probability"] < 0.5, regime


def test_a_series_ending_in_its_positive_state_reports_bull():
    m = JumpModel("TEST")
    assert m.train(_features(first_mean=-0.015, second_mean=+0.03, seed=11))
    regime = m.get_regime()
    assert regime["regime"] == "BULL"
    assert regime["bull_probability"] > 0.5, regime


def test_bull_probability_is_the_probability_of_the_identified_bull_state():
    m = JumpModel("TEST")
    assert m.train(_features(first_mean=+0.03, second_mean=-0.015, seed=3))
    last = m._filtered_probs.iloc[-1]
    assert m.get_regime()["bull_probability"] == pytest.approx(
        float(last.iloc[m.bull_state]), abs=1e-6)


# ── the as-of date the UI will show ───────────────────────────────────

def test_the_manager_reports_the_latest_fitted_date():
    rm = SectorRegimeManager()
    for etf, last in (("XLK", "2026-11-13"), ("XLF", "2026-11-12")):
        m = JumpModel(etf)
        m._is_trained = True
        m._smoothed_probs = pd.DataFrame(
            {"bull_probability": [0.9], "regime": [1.0]},
            index=pd.to_datetime([last]))
        rm.models[etf] = m
    assert rm.as_of_date() == "2026-11-13"


def test_the_manager_returns_no_date_when_untrained():
    assert SectorRegimeManager().as_of_date() is None
