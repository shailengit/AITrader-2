"""Frozen entry set: the fixed, DEDUPLICATED entries every policy runs on.

journal_trade held 29,736 MQR rows but only 2,013 distinct positions, replicated
up to 110x by a batch writer. These tests pin the corrected shape and assert the
spec's "no duplicate positions" requirement, which the original set violated.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pandas as pd

from app.services.exit_replay.entry_set import (
    ENTRY_COLUMNS,
    MQR_STRATEGY_ID,
    duplicate_summary,
    extract_entry_set,
    freeze_entry_set,
    load_entry_set,
)


def test_raw_rows_are_heavily_replicated():
    """The finding that forced the dedup: 29,736 rows / 2,013 positions."""
    raw = extract_entry_set(MQR_STRATEGY_ID, dedupe=False)
    s = duplicate_summary(raw)
    assert s["rows"] == 29_736
    assert s["distinct"] == 2_013
    assert s["duplicates"] == 27_723
    assert s["max_multiplicity"] == 110


def test_deduped_set_has_no_duplicate_positions():
    """Spec 10 requires no duplicate rows; the original set failed this."""
    df = extract_entry_set(MQR_STRATEGY_ID)
    assert len(df) == 2_013
    assert int(df.duplicated(["ticker", "entry_date"]).sum()) == 0


def test_entry_set_columns_and_values_are_clean():
    df = extract_entry_set(MQR_STRATEGY_ID)
    assert list(df.columns) == ENTRY_COLUMNS
    assert df[["ticker", "entry_px", "exit_px", "qty", "exit_reason"]].notna().all().all()
    assert (df["entry_px"] > 0).all() and (df["exit_px"] > 0).all()
    assert df["entry_date"].min() == pd.Timestamp("2020-01-03")
    assert df["entry_date"].max() == pd.Timestamp("2026-05-19")
    assert df["hold_days_calendar"].min() >= 1
    assert df["hold_days_calendar"].max() <= 400


def test_exit_reason_comes_from_notes_and_covers_the_known_rules():
    """journal_trade.notes carries 'backtest:<Reason>'. The original design
    wrongly believed no reason was recorded."""
    df = extract_entry_set(MQR_STRATEGY_ID)
    assert set(df["exit_reason"].unique()) <= {
        "Trailing Stop", "Rotated Out", "Take Profit", "Time Stop", "Stop Loss"}
    # Trailing stop is the largest bucket by a wide margin; rotation second.
    top = df["exit_reason"].value_counts()
    assert top.index[0] == "Trailing Stop"
    assert top.index[1] == "Rotated Out"
    assert 0.45 < top.iloc[0] / len(df) < 0.60


def test_no_trade_held_under_14_days_is_labelled_rotation():
    """The structural signature the original design used to INFER price exits is
    still true and now checkable against the recorded labels."""
    df = extract_entry_set(MQR_STRATEGY_ID)
    bad = df[(df["hold_days_calendar"] < 14) & (df["exit_reason"] == "Rotated Out")]
    assert len(bad) == 0


def test_freeze_load_roundtrip_preserves_values(tmp_path):
    df = extract_entry_set(MQR_STRATEGY_ID)
    p = tmp_path / "entry_set.csv"
    freeze_entry_set(df, p)
    back = load_entry_set(p)
    assert len(back) == len(df)
    pd.testing.assert_frame_equal(
        back.sort_values(["ticker", "entry_date"]).reset_index(drop=True),
        df.sort_values(["ticker", "entry_date"]).reset_index(drop=True),
        check_dtype=False,
    )


def test_freeze_is_deterministic(tmp_path):
    df = extract_entry_set(MQR_STRATEGY_ID)
    a = freeze_entry_set(df, tmp_path / "a.csv")
    b = freeze_entry_set(df, tmp_path / "b.csv")
    assert a == b and len(a) == 64
