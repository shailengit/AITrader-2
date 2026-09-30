"""Backfill journal_trade mae/mfe from the real price path.

Default is dry-run: this writes to the production database, so the caller must
opt in explicitly.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pandas as pd

from app.services.exit_replay.backfill import backfill


class FakePanel:
    def bars(self, ticker, start, end):
        return pd.DataFrame([
            {"Date": pd.Timestamp("2020-02-04"), "Open": 101, "High": 120,
             "Low": 90, "Close": 110},
        ])


def _entry():
    return pd.DataFrame([{
        "ticker": "AAPL", "entry_date": pd.Timestamp("2020-02-03"),
        "entry_px": 100.0, "qty": 1.0,
        "exit_date": pd.Timestamp("2020-03-02"), "exit_px": 110.0,
        "hold_days_calendar": 28,
    }])


def test_dry_run_reports_counts_and_writes_nothing():
    res = backfill(_entry(), FakePanel(), None, dry_run=True)
    assert res["dry_run"] is True
    assert res["n_updated"] == 1          # would-update count
    assert res["n_skipped"] == 0


def test_dry_run_never_touches_the_engine_even_if_given_one():
    class ExplodingEngine:
        def begin(self, *a, **k):
            raise AssertionError("dry_run must not open a transaction")

    res = backfill(_entry(), FakePanel(), ExplodingEngine(), dry_run=True)
    assert res["n_updated"] == 1


def test_write_mode_executes_updates_through_the_engine():
    executed = []

    class FakeConn:
        def execute(self, stmt, params=None):
            executed.append(params)

    class FakeEngine:
        def begin(self):
            class Ctx:
                def __enter__(self_inner):
                    return FakeConn()

                def __exit__(self_inner, *a):
                    return False
            return Ctx()

    res = backfill(_entry(), FakePanel(), FakeEngine(), dry_run=False)
    assert res["n_updated"] == 1
    assert res["dry_run"] is False
    assert len(executed) == 1
    assert round(float(executed[0]["mae"]), 4) == -0.10
    assert round(float(executed[0]["mfe"]), 4) == 0.20
