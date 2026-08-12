"""
DeMarker (Tom DeMark) momentum oscillator — VectorBT IndicatorFactory.

Computes the DeMarker value in [0, 1] from High/Low price action:

    DeMax  = max(High - prev_High, 0)
    DeMin  = max(prev_Low - Low, 0)
    DeMark = SMA(DeMax, window) / (SMA(DeMax, window) + SMA(DeMin, window))

Exposes three public entry points:

- `DeMarker` — `vbt.IndicatorFactory` for use in strategies and VectorBT
  param sweeps. Run with `DeMarker.run(high, low, window=…).demarker`.
- `DeMarkerIndicator` — class adapter for the screener
  `INDICATOR_REGISTRY` dispatch (instantiate, call `.demarker()` to get a
  `pd.Series`). Mirrors the `ta` library's `XIndicator().x()` convention.
- `compute(high, low, window)` — thin numpy convenience wrapper.

Column name (when wired into the screener pipeline): `momentum_demarker`.
Default `window` is 14, matching Tom DeMark's original setting.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_WINDOW = 14


def _demarker_apply(high, low, window: int) -> np.ndarray:
    import vectorbt as vbt  # lazy: heavy import
    # VectorBT may pass inputs as 1-D or 2-D (n, 1) columns; flatten for pd.Series.
    high_arr = np.asarray(high).reshape(-1)
    low_arr = np.asarray(low).reshape(-1)
    high_s = pd.Series(high_arr)
    low_s = pd.Series(low_arr)
    prev_high = high_s.shift(1)
    prev_low = low_s.shift(1)
    demax = (high_s - prev_high).clip(lower=0.0)
    demin = (prev_low - low_s).clip(lower=0.0)
    demax_avg = demax.rolling(window).mean()
    demin_avg = demin.rolling(window).mean()
    return (demax_avg / (demax_avg + demin_avg)).to_numpy()


DeMarker = vbt.IndicatorFactory(
    class_name="DeMarker",
    short_name="dem",
    input_names=["high", "low"],
    param_names=["window"],
    output_names=["demarker"],
).from_apply_func(
    _demarker_apply,
    window=DEFAULT_WINDOW,
)


def compute(high, low, window: int = DEFAULT_WINDOW) -> np.ndarray:
    """Convenience wrapper — returns just the demarker array as numpy."""
    return DeMarker.run(high, low, window=window).demarker.to_numpy()


class DeMarkerIndicator:
    """Class adapter for `INDICATOR_REGISTRY` dispatch.

    The screener's `_recompute_indicator` invokes
    `cls(**params)` then `getattr(instance, output_attr)()` — a pattern
    shared with the `ta` library's `XIndicator().x()`. This class wraps
    the `_demarker_apply` computation in the same shape so the registry
    can resolve `momentum_demarker` to this module.

    Example:
        ind = DeMarkerIndicator(high=df['High'], low=df['Low'], window=14)
        series = ind.demarker()  # pd.Series aligned to the input index
    """

    def __init__(self, high, low, window: int = DEFAULT_WINDOW):
        self.high = high
        self.low = low
        self.window = int(window)

    def demarker(self) -> pd.Series:
        values = _demarker_apply(
            np.asarray(self.high),
            np.asarray(self.low),
            self.window,
        )
        index = getattr(self.high, 'index', None)
        return pd.Series(values, index=index)
