"""Backtest dates must be bound, never interpolated into SQL.

`ExperimentRequest` carries its dates as plain strings, and the adapter pasted
them straight into the query:

    WHERE "Date" >= '{as_of}' AND "Date" <= '{end}'

The strategy-lab endpoint is authenticated, so this was authenticated SQL
injection: a token holder could end a date with `' UNION SELECT ...` and read
the whole database. These tests pin the two defences: the boundary rejects
anything that is not a date, and the query itself binds the values.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest

from app.routers.strategy_lab import ExperimentRequest
from app.services import strategy_backtest_adapter as adapter_mod
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategy_base import ExitCheck, RotationConfig, Strategy


class _FakeStrategy(Strategy):
    def __init__(self, cfg=None):
        self._cfg = cfg or RotationConfig()

    def get_name(self):
        return "FakeV1"

    def get_signals(self, as_of_date, engine):
        return []

    def should_exit(self, ticker, as_of_date, engine, side="long"):
        return ExitCheck()

    @property
    def max_holdings(self):
        return 5

    @property
    def sizing_pcts(self):
        return [0.2, 0.2, 0.2, 0.2, 0.2]

    def get_rotation_config(self):
        return self._cfg


def test_the_price_query_binds_the_dates(monkeypatch):
    seen = {}

    def fake_read_sql(sql, conn, params=None):
        seen["sql"], seen["params"] = str(sql), params
        return pd.DataFrame(columns=["Date", "Close"])

    monkeypatch.setattr(adapter_mod.pd, "read_sql", fake_read_sql)

    adapter_mod.read_date_range(
        object(), "spy", ("Date", "Close"), "2020-01-01", "2024-01-01")

    assert "2020-01-01" not in seen["sql"]
    assert "2024-01-01" not in seen["sql"]
    assert ":as_of" in seen["sql"] and ":end" in seen["sql"]
    assert seen["params"] == {"as_of": "2020-01-01", "end": "2024-01-01"}


def test_a_hyphenated_ticker_table_is_accepted(monkeypatch):
    """get_safe_table_name maps BRK.B to "brk-b"; the guard must allow it."""
    seen = {}

    def fake_read_sql(sql, conn, params=None):
        seen["sql"] = str(sql)
        return pd.DataFrame(columns=["Date", "Close"])

    monkeypatch.setattr(adapter_mod.pd, "read_sql", fake_read_sql)

    adapter_mod.read_date_range(
        object(), "brk-b", ("Date", "Close"), "2020-01-01", "2024-01-01")

    assert '"brk-b"' in seen["sql"]


def test_the_price_query_keeps_its_descending_limit(monkeypatch):
    seen = {}

    def fake_read_sql(sql, conn, params=None):
        seen["sql"] = str(sql)
        return pd.DataFrame(columns=["Date", "Close"])

    monkeypatch.setattr(adapter_mod.pd, "read_sql", fake_read_sql)

    adapter_mod.read_date_range(
        object(), "aapl", ("Date", "Close"), "2020-01-01", "2024-01-01",
        descending=True, limit=3000)

    assert "DESC" in seen["sql"]
    assert "LIMIT 3000" in seen["sql"]


class _ExplodingEngine:
    """Fails the test if the adapter reaches the database at all."""

    def connect(self):
        raise AssertionError("queried the database before validating the dates")


def test_the_adapter_rejects_a_non_iso_start_date(monkeypatch):
    monkeypatch.setattr(adapter_mod, "db_engine", _ExplodingEngine())
    adapter = StrategyBacktestAdapter(_FakeStrategy())
    with pytest.raises(ValueError):
        adapter.run(as_of="2020-01-01' OR '1'='1", end="2024-01-01")


def test_the_adapter_rejects_a_non_iso_end_date(monkeypatch):
    monkeypatch.setattr(adapter_mod, "db_engine", _ExplodingEngine())
    adapter = StrategyBacktestAdapter(_FakeStrategy())
    with pytest.raises(ValueError):
        adapter.run(as_of="2020-01-01", end="2024-01-01'--")


def test_the_request_rejects_an_injected_end_date():
    with pytest.raises(ValueError):
        ExperimentRequest(
            n_runs=1, end_date="2024-01-01' OR '1'='1",
            start_date_min="2020-01-01", start_date_max="2023-01-01")


def test_the_request_rejects_an_injected_start_bound():
    with pytest.raises(ValueError):
        ExperimentRequest(
            n_runs=1, end_date="2024-01-01",
            start_date_min="2020-01-01'--", start_date_max="2023-01-01")


def test_the_request_rejects_an_injected_fixed_start_date():
    with pytest.raises(ValueError):
        ExperimentRequest(
            n_runs=1, end_date="2024-01-01",
            fixed_start_dates=["2020-01-01", "2021-01-01'--"])


def test_the_request_accepts_iso_dates():
    req = ExperimentRequest(
        n_runs=1, end_date="2024-01-01",
        start_date_min="2020-01-01", start_date_max="2023-01-01",
        fixed_start_dates=["2020-01-01", "2021-06-30"])
    assert req.end_date == "2024-01-01"
    assert req.fixed_start_dates == ["2020-01-01", "2021-06-30"]
