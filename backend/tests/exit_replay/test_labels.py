"""Forward-return labels and the purge that keeps the temporal split honest."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd

from app.services.exit_replay.labels import TRAIN_END, make_label, purge_before_split
from tests.exit_replay.test_features import _panel


def test_label_is_the_forward_return_over_the_horizon():
    rp = _panel(n_dates=120)
    lab = make_label(rp, 50, 0, 20)
    assert abs(lab - (rp.closes[70, 0] / rp.closes[50, 0] - 1)) < 1e-12


def test_label_is_none_when_the_horizon_runs_past_the_data():
    rp = _panel(n_dates=60)
    assert make_label(rp, 55, 0, 20) is None


def test_train_end_constant_is_the_spec_split():
    assert TRAIN_END == pd.Timestamp("2023-12-31")


def test_purge_drops_every_row_whose_label_window_crosses_the_split():
    """A row within H trading days BEFORE the split uses post-split prices."""
    dates = pd.bdate_range("2023-01-02", periods=300)      # spans into 2024
    rows = pd.Series(dates)
    keep = purge_before_split(dates, rows, horizon=40, split=TRAIN_END)
    split_pos = int(dates.searchsorted(TRAIN_END))
    kept_pos = dates.searchsorted(pd.DatetimeIndex(rows[keep].values))
    assert (kept_pos + 40 <= split_pos).all()
    assert keep.sum() < len(dates)          # the purge actually removed rows


def test_purge_keeps_early_rows_and_drops_everything_post_split():
    dates = pd.bdate_range("2023-01-02", periods=300)
    rows = pd.Series(dates)
    keep = purge_before_split(dates, rows, horizon=40, split=TRAIN_END)
    assert bool(keep[0]) is True
    assert not bool(keep[rows >= TRAIN_END].any())


def test_purge_keeps_everything_before_the_split_and_excludes_unlabellable_tail():
    """Two distinct exclusions: rows near the SPLIT (leak) and rows near the END OF
    DATA (no label exists). With data ending years before the split, only the
    trailing `horizon` rows are dropped."""
    dates = pd.bdate_range("2020-01-02", periods=50)
    rows = pd.Series(dates)
    keep = purge_before_split(dates, rows, horizon=5, split=TRAIN_END)
    assert keep[:45].all()          # nothing here is near the split
    assert not keep[45:].any()      # last 5 rows have no computable label
