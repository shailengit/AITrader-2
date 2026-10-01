"""Assemble the supervised dataset: one row per (date, candidate).

Rows are sampled from the top-K of the universe-filtered ranking on every trading day
in the window, NOT only from the baseline's own decision days. That is deliberate: it
yields far more rows and avoids inheriting the baseline's blind spots. The deployment
evaluation is what validates the distribution shift.
"""
from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd

from .features import FEATURE_COLUMNS, build_features
from .labels import TRAIN_END, make_label, purge_before_split

TOP_K = 20


def build_dataset(rp, start: pd.Timestamp, end: pd.Timestamp, horizon: int,
                  top_k: int = TOP_K, earnings=None) -> pd.DataFrame:
    """One row per candidate per day, or an empty frame with the right columns."""
    empty = pd.DataFrame(columns=["date", "ticker", "label"] + list(FEATURE_COLUMNS))
    i0 = rp.date_index(pd.Timestamp(start))
    i1 = rp.date_index(pd.Timestamp(end))
    if i0 is None or i1 is None or i1 <= i0:
        return empty

    rows = []
    for i in range(i0, i1):
        for t, _ in rp.ranked_on(i, top_k=top_k):
            j = rp.ticker_index(t)
            if j is None:
                continue
            label = make_label(rp, i, j, horizon)
            if label is None:
                continue
            feats = build_features(rp, i, j, earnings=earnings)
            if not feats:
                continue
            rows.append({"date": rp.dates[i], "ticker": t, "label": label, **feats})
    return pd.DataFrame(rows) if rows else empty


def split_dataset(df: pd.DataFrame, horizon: int,
                  train_end: pd.Timestamp = TRAIN_END) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Temporal split, with the purge applied to the TRAIN side only."""
    if df.empty:
        return df, df
    dates = pd.DatetimeIndex(sorted(df["date"].unique()))
    keep = purge_before_split(dates, df["date"], horizon, train_end)
    return df[keep].copy(), df[df["date"] >= train_end].copy()
