"""Unit tests for the .meta.json sidecar written after a batch backtest.

The sidecar sits next to a strategy file and is read by the Library table and
the Coach badge fallback. Every KPI in it is a per-run median -- the sidecar
describes *a* typical run, because runs in a batch have randomized start dates
and therefore arbitrary lengths (see strategy_backtest_adapter.py:601-604).

`total_trades` previously summed the batch, which inflated a 100-run strategy's
displayed trade count 100x (momentum_quality_rotation reported 26,891 when its
runs actually averaged 269). These tests pin the per-run median convention.

No DB, no LLM: _write_sidecar_meta is a pure aggregation over result dicts.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services import strategy_lab_orchestrator as orch


def _run(trades: int, status: str = "completed", **kpi_overrides) -> dict:
    """One batch result carrying the KPI keys _write_sidecar_meta reads."""
    kpis = {
        "cagr_pct": 10.0,
        "sharpe_ratio": 1.0,
        "total_return_pct": 100.0,
        "win_rate": 50.0,
        "max_drawdown_pct": 20.0,
        "total_trades": trades,
    }
    kpis.update(kpi_overrides)
    return {"status": status, "kpis": kpis}


@pytest.fixture
def write_sidecar(tmp_path, monkeypatch):
    """Write a sidecar into tmp_path and return the parsed JSON."""
    monkeypatch.setattr(orch, "REPO_ROOT", tmp_path)
    (tmp_path / "strategies").mkdir()

    def _write(results):
        orch._write_sidecar_meta("strategies/demo.py", results)
        return json.loads((tmp_path / "strategies" / "demo.meta.json").read_text())

    return _write


def test_total_trades_is_median_not_batch_sum(write_sidecar):
    """A 3-run batch trading 100/200/300 reports 200, not the 600 sum."""
    meta = write_sidecar([_run(100), _run(200), _run(300)])
    assert meta["total_trades"] == 200


def test_total_trades_stays_an_int_for_even_run_counts(write_sidecar):
    """The router types total_trades as Optional[int]; 250.5 must not leak."""
    meta = write_sidecar([_run(100), _run(200), _run(300), _run(400)])
    assert meta["total_trades"] == 250
    assert isinstance(meta["total_trades"], int)


def test_failed_runs_are_excluded_from_the_median(write_sidecar):
    meta = write_sidecar([_run(100), _run(200), _run(9999, status="failed")])
    assert meta["total_trades"] == 150
