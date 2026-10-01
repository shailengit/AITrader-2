"""Forward-return labels and the purge that keeps the temporal split honest.

A label at date D uses prices through D+H, so any training row within H trading days
of the split boundary has already seen the test period. Dropping those rows is a
correctness requirement, not a refinement: without it the model is trained on the
outcome it is later scored against.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

TRAIN_END = pd.Timestamp("2023-12-31")


def make_label(rp, i: int, j: int, horizon: int) -> Optional[float]:
    """Forward `horizon`-trading-day return; None if it runs past the data."""
    return rp.forward_return(i, j, horizon)


def purge_before_split(dates: pd.DatetimeIndex, row_dates: pd.Series,
                       horizon: int, split: pd.Timestamp = TRAIN_END) -> np.ndarray:
    """Boolean mask of TRAINING rows to keep.

    A row survives iff its label window (row date .. row date + horizon trading
    days) ends at or before the split.
    """
    # Compare in DATE space, not index positions. Comparing positions against
    # `dates.searchsorted(split)` breaks when the split lies beyond the data: the
    # search returns len(dates), and the last `horizon` rows of a short index are
    # then dropped even though every one of them is years before the split.
    split_ts = np.datetime64(pd.Timestamp(split))
    pos = dates.searchsorted(pd.DatetimeIndex(row_dates.values))
    end_pos = pos + horizon
    computable = end_pos < len(dates)          # the label must exist at all
    label_end = dates.values[np.clip(end_pos, 0, len(dates) - 1)]
    return np.asarray(computable & (label_end <= split_ts))
