"""Tests for the Alpaca live-status router helpers.

Focuses on the pure, mockable logic (configuration guard, strategy-name
resolution, and the account labels read from ALPACA_<n>_NAME in .env) rather
than the live Alpaca network call.
"""
import re
from pathlib import Path

import pytest

import app.routers.alpaca as alpaca_router
from app.routers.alpaca import (
    ACCOUNT_PREFIXES,
    DEFAULT_STRATEGY_NAME,
    _account_label,
    _account_registry,
    _build_equity_account,
    _build_live_account,
    _is_configured,
    _resolve_strategy_name,
    _strategy_name_from_path,
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



# ── Account labels: ALPACA_<n>_NAME in .env is the single source of truth ──
#
# The account label shown in the Command Center ("Acct#1" …) must come from the
# root .env, never from a hard-coded strategy name or a stale account-number map.

STALE_ACCOUNT_NUMBERS = ("PA3QALHOBO67", "PA3EW6COMH40", "PA3EWVY05TVQ")


class _FakeAlpacaClient:
    """Stand-in for AlpacaClient that never touches the network."""

    paper = True

    def __init__(self, prefix=""):
        self.prefix = prefix

    def get_account(self):
        return {
            "account_number": f"LIVE-{self.prefix}",
            "equity": 10_000.0,
            "cash": 1_000.0,
            "buying_power": 2_000.0,
            "status": "ACTIVE",
        }

    def get_positions(self):
        return [{"ticker": "AAPL", "market_value": 100.0, "unrealized_pl": 5.0}]

    def get_portfolio_history(self, period="3M", timeframe="1D", extended_hours=False):
        return {
            "dates": [1700000000, 1700086400],
            "equity": [100.0, 110.0],
            "profit_loss": [0.0, 10.0],
        }


def test_account_label_comes_from_env(monkeypatch):
    monkeypatch.setenv("ALPACA_1_NAME", "Acct#1")
    assert _account_label("1") == "Acct#1"


def test_account_label_falls_back_to_account_n_when_env_absent(monkeypatch):
    monkeypatch.delenv("ALPACA_2_NAME", raising=False)
    assert _account_label("2") == "Account 2"


def test_account_label_ignores_blank_env_value(monkeypatch):
    monkeypatch.setenv("ALPACA_3_NAME", "   ")
    assert _account_label("3") == "Account 3"


def test_account_registry_pairs_env_labels_with_prefixes(monkeypatch):
    monkeypatch.setenv("ALPACA_1_NAME", "Acct#1")
    monkeypatch.setenv("ALPACA_2_NAME", "Acct#2")
    monkeypatch.setenv("ALPACA_3_NAME", "Acct#3")
    assert _account_registry() == [("Acct#1", "1"), ("Acct#2", "2"), ("Acct#3", "3")]


def test_account_registry_covers_the_configured_prefixes():
    assert ACCOUNT_PREFIXES == ["1", "2", "3"]
    assert [prefix for _, prefix in _account_registry()] == list(ACCOUNT_PREFIXES)


def test_build_live_account_uses_env_label_and_live_number(monkeypatch):
    monkeypatch.setattr(alpaca_router, "AlpacaClient", _FakeAlpacaClient)
    monkeypatch.setenv("ALPACA_1_NAME", "Acct#1")

    payload = _build_live_account("1")

    assert payload["label"] == "Acct#1"
    assert payload["account_number"] == "LIVE-1"
    assert payload["configured"] is True


def test_build_live_account_falls_back_when_env_absent(monkeypatch):
    monkeypatch.setattr(alpaca_router, "AlpacaClient", _FakeAlpacaClient)
    monkeypatch.delenv("ALPACA_2_NAME", raising=False)

    payload = _build_live_account("2")

    assert payload["label"] == "Account 2"
    assert payload["account_number"] == "LIVE-2"


def test_build_equity_account_uses_env_label_and_live_number(monkeypatch):
    monkeypatch.setattr(alpaca_router, "AlpacaClient", _FakeAlpacaClient)
    monkeypatch.setenv("ALPACA_3_NAME", "Acct#3")

    payload = _build_equity_account("3", "3M", "1D")

    assert payload["label"] == "Acct#3"
    assert payload["account_number"] == "LIVE-3"
    assert payload["end_equity"] == 110.0


def test_live_endpoint_reports_env_labels_for_all_accounts(monkeypatch):
    monkeypatch.setattr(alpaca_router, "AlpacaClient", _FakeAlpacaClient)
    monkeypatch.setattr(alpaca_router, "_resolve_strategy_name", lambda db: "Ignored")
    for n in (1, 2, 3):
        monkeypatch.setenv(f"ALPACA_{n}_NAME", f"Acct#{n}")

    body = alpaca_router.get_live(db=None)

    assert body["configured"] is True
    assert [a["label"] for a in body["accounts"]] == ["Acct#1", "Acct#2", "Acct#3"]
    assert all("account_number" in a for a in body["accounts"])


def test_equity_curve_endpoint_reports_env_labels(monkeypatch):
    monkeypatch.setattr(alpaca_router, "AlpacaClient", _FakeAlpacaClient)
    for n in (1, 2, 3):
        monkeypatch.setenv(f"ALPACA_{n}_NAME", f"Acct#{n}")

    body = alpaca_router.get_equity_curve()

    assert [a["label"] for a in body["accounts"]] == ["Acct#1", "Acct#2", "Acct#3"]


def test_router_has_no_hard_coded_account_numbers_or_strategy_labels():
    src = Path(alpaca_router.__file__).read_text(encoding="utf-8")

    assert re.search(r"\bPA3[A-Z0-9]{5,}\b", src) is None
    for stale in STALE_ACCOUNT_NUMBERS:
        assert stale not in src
    assert "ACCOUNT_NUMBER_LABELS" not in src
    assert "_resolve_label" not in src
    assert "MomentumQualityRotation" not in src
    assert "DailyGoldenCrossRotation" not in src
    assert "SectorScannerTop5RotationV3" not in src
