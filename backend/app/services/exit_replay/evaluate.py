"""Run a policy over the frozen entry set with honest accounting.

Censoring is POLICY-DEPENDENT: a trade is dropped for a given policy only when
that policy needed bars past the data end. Aggregates therefore report the
censored count per policy, so a policy that looks good only because its losing
tail was censored is visible as such.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import CURRENT_MQR_POLICY, ExitPolicy, replay_position
from .policies import FIT_END, VAL_END

MAX_FORWARD_DAYS = 400  # calendar buffer well beyond the 180-trading-day cap

# Every MQR row in journal_trade was recorded with qty=1 (verified: all 29,736
# rows), so the recorded quantities carry NO size information and
# (exit_px - entry_px) * qty is a per-share figure, not portfolio dollars.
# Ranking policies on that number would silently favour high-priced tickers.
# Instead each trade is treated as an equal-weighted slot, which is what the
# strategy actually does (capital / max_holdings).
CAPITAL = 100_000.0
MAX_HOLDINGS = 5
NOTIONAL_PER_POSITION = CAPITAL / MAX_HOLDINGS  # 20,000


def _bucket(entry_date: pd.Timestamp) -> str:
    if entry_date <= FIT_END:
        return "fit"
    if entry_date <= VAL_END:
        return "validate"
    return "out"


def price_exit_mask(
    entry_df: pd.DataFrame, panel, policy: ExitPolicy = CURRENT_MQR_POLICY
) -> pd.Series:
    """True where the trade really exited on a PRICE rule, not by rotation.

    Determined by replaying `policy` UNCAPPED: if it reproduces the recorded
    (exit_date, exit_px), the recorded exit was that price rule firing. Otherwise
    the exit must have been rotation (the only non-price rule).
    """
    flags = []
    for row in entry_df.itertuples(index=False):
        bars = panel.bars(row.ticker, row.entry_date,
                          row.entry_date + pd.Timedelta(days=MAX_FORWARD_DAYS))
        out = replay_position(row.entry_px, row.entry_date, bars, policy,
                              cap_date=None, panel=panel, ticker=row.ticker)
        ok = (out.exit_date is not None and out.exit_px is not None
              and pd.Timestamp(out.exit_date) == pd.Timestamp(row.exit_date)
              and round(abs(float(out.exit_px) - float(row.exit_px)), 2) == 0)
        flags.append(bool(ok))
    return pd.Series(flags, index=entry_df.index, name="price_exit")


def evaluate_policy(
    entry_df: pd.DataFrame,
    panel,
    policy: ExitPolicy,
    price_exit: pd.Series | None = None,
) -> pd.DataFrame:
    """Replay one policy over every frozen entry.

    ROTATION IS HELD FIXED, PRICE EXITS ARE NOT CAPPED.

    Capping every replay at the recorded exit date would impose a ceiling: a
    policy less aggressive than the baseline could never fire later and would be
    truncated at the same date, appearing identical to baseline. That makes the
    motivating question -- "would holding longer have been better?" --
    unanswerable.

    So `price_exit` (see price_exit_mask) decides per trade:
      True  -> the trade exited on a price rule; replay uncapped to the horizon,
               so a wider stop or no stop is genuinely evaluated.
      False -> the trade was rotated out; cap at the recorded date, because
               rotation is deliberately fixed in phase 1.
    """
    if price_exit is None:
        price_exit = pd.Series([False] * len(entry_df), index=entry_df.index)
    flags = list(price_exit)

    rows = []
    for i, row in enumerate(entry_df.itertuples(index=False)):
        bars = panel.bars(row.ticker, row.entry_date,
                          row.entry_date + pd.Timedelta(days=MAX_FORWARD_DAYS))
        out = replay_position(
            row.entry_px, row.entry_date, bars, policy,
            cap_date=None if flags[i] else row.exit_date,
            panel=panel, ticker=row.ticker,
        )
        observed = bool(out.observed_fully) and out.exit_px is not None
        if observed:
            pnl_pct = (float(out.exit_px) - float(row.entry_px)) / float(row.entry_px)
            pnl_dollars = pnl_pct * NOTIONAL_PER_POSITION
        else:
            pnl_pct = None
            pnl_dollars = None
        rows.append({
            "ticker": row.ticker,
            "entry_date": row.entry_date,
            "exit_date": out.exit_date,
            "exit_px": out.exit_px,
            "exit_reason": out.exit_reason,
            "hold_days_calendar": out.hold_days_calendar,
            "observed_fully": observed,
            "pnl_pct": pnl_pct,
            "pnl_dollars": pnl_dollars,
            "bucket": _bucket(row.entry_date),
        })
    return pd.DataFrame(rows)


def summarise(per_trade: pd.DataFrame) -> dict:
    """Aggregate on observed rows only; report the censored count separately.

    No annualised Sharpe here: these are per-trade returns, not a daily series,
    so a Sharpe would not be defined. `info_ratio` is the per-trade mean/std --
    the same idea without the false frequency, and named honestly.
    """
    obs = per_trade[per_trade["observed_fully"]]
    n_total, n_obs = len(per_trade), len(obs)
    out = {"n_total": n_total, "n_observed": n_obs, "n_censored": n_total - n_obs}
    if n_obs == 0:
        out.update(mean_pnl_pct=None, total_pnl_dollars=None,
                   win_rate=None, info_ratio=None, max_dd_pct=None)
        return out

    r = obs["pnl_pct"].astype(float)
    d = obs["pnl_dollars"].astype(float)
    sd = float(r.std())
    out["mean_pnl_pct"] = round(float(r.mean()), 6)
    out["pct_of_capital_delta"] = round(float(r.sum()) * NOTIONAL_PER_POSITION / CAPITAL, 6)
    out["total_pnl_dollars"] = round(float(d.sum()), 2)
    out["win_rate"] = round(float((r > 0).mean()), 4)
    out["info_ratio"] = round(float(r.mean() / sd), 4) if sd > 0 else None

    # Drawdown on an ADDITIVE equity curve in dollars, ordered by exit date.
    # Compounding thousands of per-trade returns overflows: (1+r).cumprod() hit
    # numpy's overflow warning and produced inf, so max_dd was meaningless.
    ordered = obs.sort_values("exit_date", kind="stable")
    equity = CAPITAL + ordered["pnl_dollars"].astype(float).cumsum()
    peak = equity.cummax()
    out["max_dd_pct"] = round(float(((peak - equity) / peak).max() * 100), 2)
    return out
