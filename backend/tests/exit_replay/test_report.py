"""The HTML report must state the gate honestly and disclose the bounds."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pandas as pd

from app.services.exit_replay.report import build_report


def _gate(ok, total, semantic=0, inconsistent=0):
    return {"price_total": total, "price_reproduced": ok,
            "price_rate": ok / total if total else 0.0,
            "rotation_total": 664, "rotation_reproduced": 0,
            "semantic_mismatches": semantic,
            "label_inconsistencies": inconsistent,
            "capped_total": 2013, "capped_reproduced": 1997, "capped_rate": 0.9921,
            "mismatches": []}


def _ranking():
    return [{"policy": "baseline", "fit_dollars": 100.0, "val_dollars": 90.0,
             "n_censored": 3, "n_observed": 10, "mean_pnl_pct": 0.05}]


def _exc():
    return pd.DataFrame([{"ticker": "AAPL", "entry_date": pd.Timestamp("2020-01-02"),
                          "mae": -0.1, "mfe": 0.3}])


def _meta(bounds=None):
    return {"split": "fit <=2023 / validate 2024-25",
            "dedupe": {"rows": 29736, "distinct": 2013, "duplicates": 27723,
                       "max_multiplicity": 110, "mean_multiplicity": 14.77},
            "bounds": bounds or {"baseline": {"capped_val_dollars": 50.0,
                                              "nextopen_val_dollars": 80.0}}}


def test_report_contains_required_sections_and_numbers():
    html = build_report(_gate(1342, 1349), _ranking(), _exc(), _meta())
    for needle in ["<!DOCTYPE html>", "MQR Exit Replay", "Reproduction gate",
                   "Policy ranking", "Excursion", "1,342", "1,342 / 1,349"]:
        assert needle in html, needle


def test_report_marks_a_passing_gate_and_a_semantically_broken_one_differently():
    """A vintage price residue must NOT read as failure; a wrong trigger date must."""
    passing = build_report(_gate(1342, 1349, semantic=0), _ranking(), _exc(), _meta())
    broken = build_report(_gate(1349, 1349, semantic=3), _ranking(), _exc(), _meta())
    assert "PASS" in passing and "FAIL" not in passing
    assert "FAIL" in broken and "void" in broken


def test_report_discloses_dedup_and_both_bounds():
    html = build_report(_gate(1342, 1349), _ranking(), _exc(), _meta())
    for needle in ["Deduplicated", "27,723", "upper bound", "lower bound",
                   "next open", "qty=1"]:
        assert needle in html, needle


def test_report_survives_empty_excursions_and_no_bounds():
    html = build_report(_gate(1342, 1349), _ranking(),
                        pd.DataFrame(columns=["ticker", "mae", "mfe"]),
                        {"split": "x", "dedupe": {}, "bounds": {}})
    assert "Excursion" in html
