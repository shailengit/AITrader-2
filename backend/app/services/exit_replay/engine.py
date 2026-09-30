"""Pure exit-rule replay over a fixed entry.

Mirrors strategy_backtest_adapter.py's exit semantics EXACTLY -- that is what
makes the reproduction gate (Task 4) possible:
  - precedence: hard_stop_loss -> trailing_stop -> take_profit -> time_stop
  - rules read the day's CLOSE; peak is close-based, seeded at entry_px
  - the exit fills at the NEXT trading day's open (close if there is no next bar)
  - exit_date is the TRIGGER date; exit_px is the fill
  - time_stop counts CALENDAR days

Because entries are fixed and forward prices are real, this is deterministic:
there is no position-size truncation feedback loop, so no path chaos.

The fill comes from the next row of `bars` (which carries Open), so the function
is pure and testable without a PricePanel; `panel.next_open` is only consulted
when `bars` has no later row.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd

OFF = 0.0  # disables a rule (mirrors the adapter's `cfg.x > 0` guards)


@dataclass(frozen=True)
class ExitPolicy:
    hard_stop_loss: float = 0.20
    trailing_stop: float = 0.12
    trailing_stop_activation: float = 0.0
    take_profit: float = 0.50
    time_stop_days: int = 120
    exit_priority: Tuple[str, ...] = (
        "hard_stop_loss", "trailing_stop", "take_profit", "time_stop",
    )


CURRENT_MQR_POLICY = ExitPolicy()


@dataclass
class ReplayOutcome:
    exit_date: Optional[pd.Timestamp]
    exit_px: Optional[float]
    exit_reason: str
    hold_days_calendar: int
    mae: float
    mfe: float
    observed_fully: bool


def _trailing_triggered(entry_px, peak, close, trail, activation) -> bool:
    """Same rule as strategy_backtest_adapter.trailing_stop_triggered."""
    if trail <= 0:
        return False
    if (peak - entry_px) / entry_px < activation:
        return False
    return (peak - close) / peak >= trail


def _fill_price(opens, closes, i, n, panel, ticker, trigger_date, fill: str):
    """Return (price, observed_fully) for an exit triggered at bar i.

    fill="close"     -- the trigger bar's close. This is the convention the
                        historic journal_trade data uses (verified: 600/600
                        short-hold samples match the trigger-day close, 0 match
                        the next open), so it is the default and the only way to
                        reproduce the recorded baseline.
    fill="next_open" -- the following trading day's open, which is what the
                        CURRENT adapter does and is the more realistic fill.
                        Used as a sensitivity check, since it avoids the
                        look-ahead optimism of trading at an observed close.
    """
    if fill == "close":
        return float(closes[i]), True
    if i + 1 < n:
        return float(opens[i + 1]), True
    if panel is not None and ticker:
        got = panel.next_open(ticker, trigger_date)
        if got is not None:
            return float(got), True
    return float(closes[i]), False      # no later bar at all: fall back, not fully observed


def replay_position(
    entry_px: float,
    entry_date: pd.Timestamp,
    bars: pd.DataFrame,
    policy: ExitPolicy,
    cap_date: Optional[pd.Timestamp] = None,
    panel=None,
    ticker: Optional[str] = None,
    fill: str = "close",
) -> ReplayOutcome:
    """Walk bars forward from a fixed entry, applying `policy`.

    `cap_date` is the trade's actual rotation date. Rotation is held fixed in
    phase 1, so the replay ends there as 'Rotated Out' rather than modelling a
    cross-sectional re-ranking.

    `fill` follows the recorded data's convention by default; see _fill_price.
    """
    entry_date = pd.Timestamp(entry_date)
    forward = bars[bars["Date"] > entry_date]
    if cap_date is not None:
        forward = forward[forward["Date"] <= pd.Timestamp(cap_date)]
    if len(forward) == 0:
        return ReplayOutcome(entry_date, entry_px, "Window End", 0, 0.0, 0.0, False)

    forward = forward.reset_index(drop=True)
    dates = forward["Date"].to_numpy()
    opens = forward["Open"].to_numpy(dtype=float)
    highs = forward["High"].to_numpy(dtype=float)
    lows = forward["Low"].to_numpy(dtype=float)
    closes = forward["Close"].to_numpy(dtype=float)
    entry_np = np.datetime64(entry_date.to_datetime64())
    one_day = np.timedelta64(1, "D")
    n = len(closes)

    # Rule activation mirrors the adapter's `cfg.x > 0` guards.
    use_hard = policy.hard_stop_loss > 0
    use_trail = policy.trailing_stop > 0
    use_tp = policy.take_profit > 0
    use_time = policy.time_stop_days > 0

    peak = float(entry_px)
    mae = 0.0
    mfe = 0.0
    last_i = -1

    for i in range(n):
        close = closes[i]
        if close > peak:
            peak = close
        ret = (close - entry_px) / entry_px
        hi = (highs[i] - entry_px) / entry_px
        lo = (lows[i] - entry_px) / entry_px
        if hi > mfe:
            mfe = hi
        if lo < mae:
            mae = lo
        hold = int((dates[i] - entry_np) / one_day)
        last_i = i

        reason = None
        for rule in policy.exit_priority:
            if rule == "hard_stop_loss" and use_hard:
                if ret <= -policy.hard_stop_loss:
                    reason = "Stop Loss"
            elif rule == "trailing_stop" and use_trail:
                if _trailing_triggered(entry_px, peak, close,
                                       policy.trailing_stop,
                                       policy.trailing_stop_activation):
                    reason = "Trailing Stop"
            elif rule == "take_profit" and use_tp:
                if ret >= policy.take_profit:
                    reason = "Take Profit"
            elif rule == "time_stop" and use_time:
                if hold >= policy.time_stop_days:
                    reason = "Time Stop"
            if reason is not None:
                break

        if reason is not None:
            trigger_date = pd.Timestamp(dates[i])
            px, observed = _fill_price(opens, closes, i, n, panel, ticker,
                                       trigger_date, fill)
            return ReplayOutcome(trigger_date, px, reason, hold, mae, mfe, observed)

    # Window exhausted without a price rule firing.
    last_date = pd.Timestamp(dates[last_i])
    hold = int((dates[last_i] - entry_np) / one_day)
    capped = cap_date is not None and pd.Timestamp(cap_date) <= last_date
    if capped:
        px, observed = _fill_price(opens, closes, last_i, n, panel, ticker,
                                   last_date, fill)
        return ReplayOutcome(last_date, px, "Rotated Out", hold, mae, mfe, observed)
    return ReplayOutcome(last_date, closes[last_i], "Window End",
                         hold, mae, mfe, False)
