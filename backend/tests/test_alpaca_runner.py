"""Tests for the Alpaca strategy runner."""

import os
import sys
import types

# Ensure backend is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Set DB credentials for testing
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")

import pytest
from app.services.alpaca_runner import StrategyRunner
from app.services.strategy_base import Strategy, ExitCheck


class _DummyAlpaca:
    """Stand-in for AlpacaClient so tests never touch the live API."""

    def __init__(self, prefix=""):
        # Mirror the real constructor: StrategyRunner passes `prefix=`.
        self.prefix = prefix
    def get_positions(self):
        return []
    def get_account(self):
        return {"equity": "100000.00"}
    def submit_market_order(self, *args, **kwargs):
        return {"id": "dummy"}
    def submit_bracket_order(self, *args, **kwargs):
        return {"id": "dummy"}


class _FakeStrategy(Strategy):
    """Concrete Strategy for tests."""
    def __init__(self, signals=None):
        self._signals = signals or []
    def get_name(self):
        return "FakeStrategy"
    def get_signals(self, as_of_date, engine):
        return self._signals
    def should_exit(self, ticker, as_of_date, engine, side):
        return ExitCheck(should_close=False, reason="")
    @property
    def max_holdings(self):
        return 5
    @property
    def sizing_pcts(self):
        return [0.2]


class _FakeConn:
    """Context-manager connection whose execute().scalar() returns a value."""
    def __init__(self, scalar_value):
        self._value = scalar_value
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def execute(self, *args, **kwargs):
        return types.SimpleNamespace(scalar=lambda: self._value)


class _FakeEngine:
    """Engine stub for get_latest_date / crisis-query tests."""
    def __init__(self, scalar_value):
        self._conn = _FakeConn(scalar_value)
    def connect(self):
        return self._conn


@pytest.fixture
def runner(monkeypatch):
    """A StrategyRunner with the live Alpaca client replaced by a dummy."""
    monkeypatch.setattr("app.services.alpaca_runner.AlpacaClient", _DummyAlpaca)
    return StrategyRunner(strategy=_FakeStrategy())


def test_get_latest_date(runner, monkeypatch):
    """get_latest_date returns the DB date as a YYYY-MM-DD string."""
    monkeypatch.setattr(runner, "engine", _FakeEngine("2024-06-15"))
    date = runner.get_latest_date()
    assert date == "2024-06-15"
    assert len(date) == 10


def test_get_latest_date_falls_back_to_today_when_null(runner, monkeypatch):
    """When the DB has no data, get_latest_date returns today's date."""
    monkeypatch.setattr(runner, "engine", _FakeEngine(None))
    import datetime
    date = runner.get_latest_date()
    assert len(date) == 10
    assert date == datetime.datetime.now().strftime("%Y-%m-%d")


def test_check_crisis_override_returns_bool(runner):
    """check_crisis_override returns a bool (False on any DB error)."""
    import numpy as np
    result = runner.check_crisis_override("2024-01-01")
    assert isinstance(result, (bool, np.bool_))


def test_run_daily_returns_no_candidates(runner):
    """run_daily with no signals reports no_candidates."""
    runner.strategy._signals = []
    result = runner.run_daily()
    assert result["status"] == "no_candidates"
    assert "strategy" in result
    assert result["strategy"] == "FakeStrategy"


def test_run_daily_crisis_goes_to_cash(runner, monkeypatch):
    """run_daily in crisis mode closes everything and reports completed_crisis."""
    monkeypatch.setattr(runner, "check_crisis_override", lambda as_of: True)
    result = runner.run_daily()
    assert result["status"] == "completed_crisis"
    assert result["crisis_mode"] is True


class _CrisisConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _CrisisEngine:
    def connect(self):
        return _CrisisConn()


def test_check_crisis_override_binds_the_date(runner, monkeypatch):
    """The crisis query is parameterised, not string-formatted."""
    import pandas as pd
    import app.services.alpaca_runner as alpaca_runner_module

    seen = {}

    def fake_read_sql(sql, conn, params=None):
        seen["sql"], seen["params"] = str(sql), params
        return pd.DataFrame()

    monkeypatch.setattr(alpaca_runner_module.pd, "read_sql", fake_read_sql)
    runner.engine = _CrisisEngine()

    assert runner.check_crisis_override("2024-06-08") is False
    assert "2024-06-08" not in seen["sql"]
    assert seen["params"] == {"as_of_date": "2024-06-08"}
