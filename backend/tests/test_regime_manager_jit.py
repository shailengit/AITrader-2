"""Unit tests for lazy just-in-time Jump Model training (regime JIT).

Verifies that a fresh SectorRegimeManager can populate itself on first
request without a manual retrain — the behavior that makes Command Center's
"Today's Regime" show BULL/BEAR after a server restart instead of UNKNOWN.

Heavy model fitting and DB access are patched out so these tests are fast
and deterministic.
"""
import pandas as pd

from app.services.markov import regime_model as rm_mod
from app.services.markov.regime_model import SectorRegimeManager, JumpModel


def _fake_features(etf: str, start_date: str, end_date: str):
    """Cheap stand-in for compute_etf_features: a bare observation column."""
    return pd.DataFrame({"log_return_20d": [0.0] * 100})


def _fake_train(self, features) -> bool:
    """Cheap stand-in for JumpModel.train: mark trained without fitting."""
    idx = pd.date_range("2024-01-01", periods=3)
    self._smoothed_probs = pd.DataFrame(
        {"bull_probability": [0.8, 0.9, 0.85], "regime": [1, 1, 1]},
        index=idx,
    )
    self.garch_result = None
    self._is_trained = True
    return True


def test_fresh_manager_starts_untrained():
    manager = SectorRegimeManager()
    assert manager.models == {}
    assert manager.get_regime("XLK")["regime"] == "UNKNOWN"


def test_ensure_trained_trains_all_etfs_once(monkeypatch):
    monkeypatch.setattr(rm_mod, "compute_etf_features", _fake_features)
    monkeypatch.setattr(JumpModel, "train", _fake_train)

    manager = SectorRegimeManager()
    calls = []
    original_train_all = manager.train_all

    def tracking_train_all(start, end):
        calls.append((start, end))
        return original_train_all(start, end)

    monkeypatch.setattr(manager, "train_all", tracking_train_all)

    ok = manager.ensure_trained()
    assert ok is True
    # Trained every sector ETF exactly once.
    assert len(manager.models) == 11
    assert all(m.is_trained for m in manager.models.values())
    assert len(calls) == 1
    # Regimes now resolve instead of UNKNOWN.
    assert manager.get_regime("XLK")["regime"] in ("BULL", "BEAR")


def test_ensure_trained_is_noop_when_already_trained(monkeypatch):
    monkeypatch.setattr(rm_mod, "compute_etf_features", _fake_features)
    monkeypatch.setattr(JumpModel, "train", _fake_train)

    manager = SectorRegimeManager()
    manager.ensure_trained()
    trained_etfs = len(manager.models)
    assert trained_etfs == 11

    # Second call must not retrain.
    monkeypatch.setattr(manager, "train_all", lambda s, e: (_ for _ in ()).throw(
        AssertionError("train_all should not be called again")
    ))
    manager.ensure_trained()
    assert len(manager.models) == trained_etfs


def test_ensure_trained_tolerates_failed_etfs(monkeypatch):
    monkeypatch.setattr(rm_mod, "compute_etf_features", _fake_features)

    def flaky_train(self, features) -> bool:
        # Simulate one ETF failing to fit.
        trained = self.etf_ticker != "XLE"
        if trained:
            idx = pd.date_range("2024-01-01", periods=3)
            self._smoothed_probs = pd.DataFrame(
                {"bull_probability": [0.8, 0.9, 0.85], "regime": [1, 1, 1]},
                index=idx,
            )
            self.garch_result = None
        self._is_trained = trained
        return trained

    monkeypatch.setattr(JumpModel, "train", flaky_train)

    manager = SectorRegimeManager()
    ok = manager.ensure_trained()
    assert ok is True
    # XLE failed to train but the manager still holds all models.
    assert len(manager.models) == 11
    assert manager.get_regime("XLE")["regime"] == "UNKNOWN"
    assert manager.get_regime("XLK")["regime"] in ("BULL", "BEAR")
