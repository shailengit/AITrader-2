"""Obsidian export: one note per run plus a batch index, rendered from stored trades."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.experiment_export import (  # noqa: E402
    export_runs,
    render_index,
    render_run_note,
    safe_name,
)


def _detail(run=31, cagr=52.3):
    return {
        "run_index": run,
        "strategy_name": "Momentum Quality Rotation V1",
        "batch": "2026-11-16",
        "start_date": "2020-01-02",
        "end_date": "2026-11-11",
        "cagr_pct": cagr,
        "sharpe_ratio": 1.2,
        "max_drawdown_pct": 44.0,
        "total_trades": 3,
        "win_rate": 66.7,
        "n_sells": 3,
        "exit_reasons": {
            "Trailing Stop": {"n": 1, "pnl": 500.0, "wins": 1, "win_rate": 100.0, "avg_holding_days": 5.0},
            "Rotated Out": {"n": 1, "pnl": -200.0, "wins": 0, "win_rate": 0.0, "avg_holding_days": 20.0},
            "Take Profit": {"n": 1, "pnl": 900.0, "wins": 1, "win_rate": 100.0, "avg_holding_days": 40.0},
        },
        "holding_days": {"n": 3, "mean": 21.7, "median": 20, "p10": 5, "p90": 40, "max": 40},
        "top_winners": [{"ticker": "CCC", "return_pct": 30.0, "pnl_dollars": 900.0,
                         "exit_reason": "Take Profit", "holding_days": 40,
                         "entry_date": "2024-01-02", "exit_date": "2024-02-11"}],
        "top_losers": [{"ticker": "BBB", "return_pct": -4.0, "pnl_dollars": -200.0,
                        "exit_reason": "Rotated Out", "holding_days": 20,
                        "entry_date": "2024-01-02", "exit_date": "2024-01-22"}],
        "trades": [
            {"ticker": "CCC", "side": "SELL", "entry_date": "2024-01-02",
             "exit_date": "2024-02-11", "entry_price": 100.0, "exit_price": 130.0,
             "return_pct": 30.0, "holding_days": 40, "exit_reason": "Take Profit",
             "pnl_dollars": 900.0},
        ],
    }


def test_safe_name_strips_path_and_space_hostile_characters():
    assert safe_name("Momentum Quality Rotation V1") == "Momentum-Quality-Rotation-V1"
    assert "/" not in safe_name("a/b")


def test_the_note_carries_frontmatter_kpis_and_the_trade_table():
    note = render_run_note(_detail())
    assert note.startswith("---\n")
    assert "run: 31" in note
    assert "cagr: 52.3" in note
    assert "## Exit reasons" in note
    assert "| Take Profit | 1 |" in note
    assert "CCC" in note and "Take Profit" in note
    assert "## Trades" in note
    assert "| 2024-01-02 | 2024-02-11 | CCC |" in note


def test_the_note_records_the_worst_contributor():
    assert "BBB" in render_run_note(_detail())


def test_the_index_links_every_run():
    rows = [{"run_index": 31, "cagr_pct": 52.3, "sharpe_ratio": 1.2,
             "max_drawdown_pct": 44.0, "total_trades": 3, "win_rate": 66.7,
             "start_date": "2020-01-02"}]
    idx = render_index(rows, "Momentum Quality Rotation V1", "2026-11-16")
    assert "# Momentum Quality Rotation V1" in idx
    assert "[[Run 031]]" in idx
    assert "52.30" in idx


def test_export_writes_notes_and_an_index(tmp_path):
    paths = export_runs(
        [_detail(31), _detail(7, cagr=12.0)],
        "Momentum Quality Rotation V1",
        "2026-11-16",
        tmp_path,
    )
    names = sorted(p.name for p in paths)
    assert "00 Index.md" in names
    assert "Run 031.md" in names and "Run 007.md" in names
    body = (tmp_path / "Run 031.md").read_text()
    assert "run: 31" in body
    index = (tmp_path / "00 Index.md").read_text()
    assert "[[Run 031]]" in index and "[[Run 007]]" in index


def test_export_is_idempotent(tmp_path):
    export_runs([_detail(31)], "S", "2026-11-16", tmp_path)
    export_runs([_detail(31)], "S", "2026-11-16", tmp_path)
    assert len(list(tmp_path.glob("Run 031.md"))) == 1
