"""The Brain must be able to explain ONE run from its own trades.

The data was always persisted (`strategy_experiments.trades_summary`), but the
bundle only carried strategy-wide aggregates and a sample, so a question like
"why did run #31 have the best CAGR?" could not be answered from the bundle.
"""
import datetime as dt
import types

import pytest

from app.services import brain_service as B


def _sell(ticker, pnl, reason, holding, ret=5.0, entry="2024-01-02", exit="2024-01-12"):
    return {"ticker": ticker, "side": "SELL", "entry_date": entry, "exit_date": exit,
            "entry_price": 100.0, "exit_price": 105.0, "return_pct": ret,
            "holding_days": holding, "exit_reason": reason, "pnl_dollars": pnl}


def _buy(ticker, date="2024-01-02"):
    return {"ticker": ticker, "side": "BUY", "entry_date": date, "exit_date": "",
            "entry_price": 100.0, "exit_price": 0.0, "return_pct": 0.0,
            "holding_days": 0, "exit_reason": "New Entry", "pnl_dollars": 0.0}


def _exp(run_index=31, cagr=52.3):
    return types.SimpleNamespace(
        run_index=run_index,
        start_date=dt.date(2020, 1, 2),
        end_date=dt.date(2026, 11, 11),
        kpis={"cagr_pct": cagr, "sharpe_ratio": 1.2, "max_drawdown_pct": 44.0,
              "total_trades": 3, "win_rate": 66.7, "total_return_pct": 300.0},
        trades_summary=[
            _buy("AAA"), _buy("BBB"), _buy("CCC"),
            _sell("AAA", 500.0, "Trailing Stop", 5),
            _sell("BBB", -200.0, "Rotated Out", 20, ret=-4.0),
            _sell("CCC", 900.0, "Take Profit", 40, ret=30.0),
        ],
    )


def test_run_detail_reports_its_own_exits_and_holding_periods():
    d = B._run_trade_detail(_exp())
    assert d["run_index"] == 31
    assert d["n_buys"] == 3 and d["n_sells"] == 3
    assert d["exit_reasons"]["Trailing Stop"]["n"] == 1
    assert d["exit_reasons"]["Take Profit"]["pnl"] == 900.0
    assert d["exit_reasons"]["Rotated Out"]["win_rate"] == 0.0
    assert d["holding_days"]["median"] == 20
    assert d["holding_days"]["max"] == 40


def test_run_detail_ranks_that_runs_winners_and_losers():
    d = B._run_trade_detail(_exp())
    assert [w["ticker"] for w in d["top_winners"]] == ["CCC", "AAA"]
    assert [l["ticker"] for l in d["top_losers"]] == ["BBB"]


def test_full_trades_are_only_attached_on_request():
    assert "trades" not in B._run_trade_detail(_exp())
    full = B._run_trade_detail(_exp(), include_trades=True)
    assert len(full["trades"]) == 6
    assert {t["side"] for t in full["trades"]} == {"BUY", "SELL"}


def test_a_run_without_trades_degrades_to_empty_detail():
    e = _exp()
    e.trades_summary = None
    d = B._run_trade_detail(e)
    assert d["n_sells"] == 0
    assert d["exit_reasons"] == {}
    assert d["holding_days"] == {}
    assert "trades" not in d


def test_the_bundle_carries_a_per_run_section(monkeypatch):
    exps = [_exp(run_index=31, cagr=52.3), _exp(run_index=7, cagr=12.0)]
    monkeypatch.setattr(B, "_query_experiments", lambda *a, **k: exps)
    monkeypatch.setattr(B, "_all_trades", lambda *a, **k: [])

    bundle = B.build_strategy_bundle(None, "backend/app/services/strategies/x.py")
    per_run = bundle["per_run"]
    assert [r["run_index"] for r in per_run] == [31, 7]
    # Many runs selected: summaries only, no full trade dumps.
    assert "trades" not in per_run[0]
    assert per_run[0]["exit_reasons"]["Take Profit"]["n"] == 1


def test_selecting_few_runs_attaches_their_full_trades(monkeypatch):
    exps = [_exp(run_index=31)]
    monkeypatch.setattr(B, "_query_experiments", lambda *a, **k: exps)
    monkeypatch.setattr(B, "_all_trades", lambda *a, **k: [])

    bundle = B.build_strategy_bundle(None, "x.py", run_ids=["31"])
    assert len(bundle["per_run"]) == 1
    assert len(bundle["per_run"][0]["trades"]) == 6


def test_run_trades_lookup_returns_the_full_history(monkeypatch):
    monkeypatch.setattr(B, "_query_experiments", lambda *a, **k: [_exp(run_index=31)])
    out = B.get_run_trades(None, "x.py", 31)
    assert out["run_index"] == 31
    assert len(out["trades"]) == 6
    assert out["exit_reasons"]["Take Profit"]["pnl"] == 900.0


def test_run_trades_lookup_returns_none_for_an_unknown_run(monkeypatch):
    monkeypatch.setattr(B, "_query_experiments", lambda *a, **k: [])
    assert B.get_run_trades(None, "x.py", 999) is None


# ── payload budget ─────────────────────────────────────────────────────

def test_the_all_runs_bundle_stays_within_a_sane_payload(monkeypatch):
    exps = [_exp(run_index=i) for i in range(1, 41)]
    many = [_sell(f"T{i}", 10.0, "Take Profit", 5)
            for i in range(B.MAX_TOTAL_TRADES * 5)]
    monkeypatch.setattr(B, "_query_experiments", lambda *a, **k: exps)
    monkeypatch.setattr(B, "_all_trades", lambda *a, **k: many)

    bundle = B.build_strategy_bundle(None, "x.py")
    assert len(bundle["sample_trades"]) <= B.MAX_TOTAL_TRADES
    assert len(bundle["per_run"]) == 40
    assert all("trades" not in r for r in bundle["per_run"])


def test_selecting_one_run_does_not_duplicate_its_trades(monkeypatch):
    exps = [_exp(run_index=31)]
    monkeypatch.setattr(B, "_query_experiments", lambda *a, **k: exps)
    monkeypatch.setattr(B, "_all_trades", lambda *a, **k: [])

    bundle = B.build_strategy_bundle(None, "x.py", run_ids=["31"])
    assert bundle["sample_trades"] == []
    assert len(bundle["per_run"][0]["trades"]) == 6
