"""Date normalisation shared across the exit-replay package.

Postgres hands back tz-aware timestamps while policy configs and test literals
are naive, and comparing aware to naive raises. Everything here is a calendar
trading day, so tz carries no information: the package works in naive dates.
"""
from __future__ import annotations

import pandas as pd


def as_naive_dates(s) -> pd.Series:
    s = pd.to_datetime(s)
    return s.dt.tz_localize(None) if s.dt.tz is not None else s
