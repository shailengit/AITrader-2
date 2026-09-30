"""The HTML report must state the gate honestly and carry the numbers."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pandas as pd

from app.services.exit_replay.report import build_report


def _gate(ok, total):
    return {"hard_total": total, "hard_reproduced": ok,
            "soft_total": 23643, "soft_reproduced": 13000, "soft_rate": 0.5499,
            "predicted_soft_rate": 0.56, "hard_mismatches": [],
            "class_counts": {"exact": ok}}


def _ranking():
    return [{"policy": "baseline", "fit_dollars": 100.0, "val_dollars": 90.0,
             "n_censored": 3, "mean_pnl_pct": 0.05, "n_observed": 10}]


def _exc():
    return pd.DataFrame([{"ticker": "AAPL", "entry_date": pd.Timestamp("2020-01-02"),
                          "mae": -0.1, "mfe": 0.3}])


def test_report_contains_required_sections_and_numbers():
    html = build_report(_gate(6093, 6093), _ranking(), _exc(),
                        {"split": "fit <=2023 / validate 2024-25"})
    for needle in ["<!DOCTYPE html>", "MQR Exit Replay", "Reproduction gate",
                   "Policy ranking", "Excursion", "6,093", "6,093 / 6,093"]:
        assert needle in html, needle


def test_report_marks_a_passing_gate_and_a_failing_gate_differently():
    passing = build_report(_gate(6093, 6093), _ranking(), _exc(), {"split": "x"})
    failing = build_report(_gate(6092, 6093), _ranking(), _exc(), {"split": "x"})
    assert "PASS" in passing and "FAIL" not in passing
    assert "FAIL" in failing
    assert "void" in failing          # conclusions are void until it passes


def test_report_survives_empty_excursions():
    html = build_report(_gate(6093, 6093), _ranking(),
                        pd.DataFrame(columns=["ticker", "mae", "mfe"]), {"split": "x"})
    assert "Excursion" in html
