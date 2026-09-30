"""Frozen entry set: the fixed entries every policy comparison runs on."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pandas as pd

from app.services.exit_replay.entry_set import (
    ENTRY_COLUMNS,
    MQR_STRATEGY_ID,
    extract_entry_set,
    freeze_entry_set,
    load_entry_set,
)


def test_entry_set_has_expected_shape_and_columns():
    df = extract_entry_set(MQR_STRATEGY_ID)
    assert len(df) == 29_736
    assert list(df.columns) == ENTRY_COLUMNS
    assert df[["ticker", "entry_px", "exit_px", "qty"]].notna().all().all()
    assert (df["entry_px"] > 0).all() and (df["exit_px"] > 0).all()
    assert df["entry_date"].min() == pd.Timestamp("2020-01-03")
    assert df["entry_date"].max() == pd.Timestamp("2026-05-19")


def test_hold_days_are_calendar_days_and_match_range():
    df = extract_entry_set(MQR_STRATEGY_ID)
    assert df["hold_days_calendar"].min() == 1
    assert df["hold_days_calendar"].max() == 122


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
