"""Supervised dataset: one row per (date, candidate), plus the temporal split."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pandas as pd

from app.services.exit_replay.dataset import TOP_K, build_dataset, split_dataset
from app.services.exit_replay.features import FEATURE_COLUMNS
from tests.exit_replay.test_features import _panel

_NUMERIC = [c for c in FEATURE_COLUMNS if c not in ("sector", "days_to_earnings")]


def test_dataset_has_features_label_and_no_nan_labels():
    rp = _panel(n_dates=140)
    df = build_dataset(rp, rp.dates[60], rp.dates[100], horizon=20, top_k=3)
    assert len(df) > 0
    assert {"date", "ticker", "label"} <= set(df.columns)
    assert set(FEATURE_COLUMNS) <= set(df.columns)
    assert df["label"].notna().all()


def test_dataset_respects_top_k_per_day():
    rp = _panel(n_dates=140)
    df = build_dataset(rp, rp.dates[60], rp.dates[100], horizon=20, top_k=2)
    assert df.groupby("date").size().max() <= 2


def test_split_is_temporal_with_train_strictly_before_test():
    # The panel must actually CROSS 2023-12-31 (400 business days is only ~1.5
    # years from 2020, which never reaches the split) and the build window must
    # extend past it, or the test trivially has no test rows.
    rp = _panel(n_dates=1200)
    df = build_dataset(rp, rp.dates[40], rp.dates[-30], horizon=20, top_k=3)
    tr, te = split_dataset(df, horizon=20)
    assert len(tr) and len(te)
    assert tr["date"].max() < te["date"].min()
    assert (te["date"] >= pd.Timestamp("2023-12-31")).all()


def test_no_nan_in_numeric_features():
    """NaN reaching the model silently poisons training; only days_to_earnings may
    be NaN, and that is deliberate."""
    rp = _panel(n_dates=140)
    df = build_dataset(rp, rp.dates[60], rp.dates[100], horizon=20, top_k=3)
    assert df[_NUMERIC].notna().all().all(), df[_NUMERIC].isna().sum().to_dict()


def test_top_k_constant():
    assert TOP_K == 20


def test_empty_window_returns_an_empty_frame_with_columns():
    rp = _panel(n_dates=60)
    df = build_dataset(rp, rp.dates[300:301][0] if len(rp.dates) > 300 else rp.dates[-1],
                       rp.dates[-1], horizon=20, top_k=3)
    assert len(df) == 0
    assert {"date", "ticker", "label"} <= set(df.columns)
