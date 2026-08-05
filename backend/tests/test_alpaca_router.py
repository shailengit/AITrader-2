"""Tests for the Alpaca live-status router helpers.

Focuses on the pure, mockable logic (configuration guard and strategy-name
resolution) rather than the live Alpaca network call.
"""
import pytest

from app.routers.alpaca import (
    _is_configured,
    _resolve_strategy_name,
    _strategy_name_from_path,
    DEFAULT_STRATEGY_NAME,
)


class _FakeDeployment:
    def __init__(self, strategy_path):
        self.strategy_path = strategy_path


class _EmptyDB:
    pass


class _NoActiveDeploymentDB:
    def __init__(self):
        self.deployment = None

    def query(self, model):
        return self


class _WithActiveDeploymentDB:
    def __init__(self, strategy_path):
        self.deployment = _FakeDeployment(strategy_path)

    def query(self, model):
        return self


def test_strategy_name_from_path_humanizes():
    assert _strategy_name_from_path("/x/y/golden_cross_rotation_v2.py") == "Golden Cross Rotation V2"
    assert _strategy_name_from_path("my_strategy.py") == "My Strategy"


def test_resolve_strategy_name_falls_back_when_none_active(monkeypatch):
    monkeypatch.setattr(
        "app.routers.alpaca.get_active_deployment",
        lambda db: None,
    )
    assert _resolve_strategy_name(_EmptyDB()) == DEFAULT_STRATEGY_NAME


def test_resolve_strategy_name_uses_active_deployment(monkeypatch):
    monkeypatch.setattr(
        "app.routers.alpaca.get_active_deployment",
        lambda db: _FakeDeployment("cool_strategy.py"),
    )
    assert _resolve_strategy_name(_EmptyDB()) == "Cool Strategy"


def test_is_configured_false_when_keys_missing(monkeypatch):
    monkeypatch.setattr("app.routers.alpaca.os.getenv", lambda k, d=None: None)
    assert _is_configured() is False


def test_is_configured_true_when_keys_present(monkeypatch):
    def fake_getenv(k, d=None):
        return {"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s"}.get(k)

    monkeypatch.setattr("app.routers.alpaca.os.getenv", fake_getenv)
    assert _is_configured() is True
