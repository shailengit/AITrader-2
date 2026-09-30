"""Run a policy over the frozen entry set with honest accounting.

Censoring is POLICY-DEPENDENT: a trade is dropped for a given policy only when
that policy needed bars past the data end. Aggregates therefore report the
censored count per policy, so a policy that looks good only because its losing
tail was censored is visible as such.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import ExitPolicy, replay_position
from .policies import FIT_END, VAL_END

MAX_FORWARD_DAYS = 400  # calendar buffer well beyond the 180-trading-day cap


def _bucket(entry_date: pd.Timestamp) -> str:
    if entry_date <= FIT_END:
        return "fit"
    if entry_date <= VAL_END:
        return "validate"
    return "out"


def evaluate_policy(entry_df: pd.DataFrame, panel, policy: ExitPolicy) -> pd.DataFrame:
    """Replay one policy over every frozen entry.

    `cap_date` is the trade's recorded exit date: rotation is held fixed, so a
    trade that was rotated out ends there, while a trade that exited on a price
    rule exits when that rule fires (which may be earlier -- that IS the
    counterfactual being measured).
    """
    rows = []
    for row in entry_df.itertuples(index=False):
        bars = panel.bars(row.ticker, row.entry_date,
                          row.entry_date + pd.Timedelta(days=MAX_FORWARD_DAYS))
        out = replay_position(
            row.entry_px, row.entry_date, bars, policy,
            cap_date=row.exit_date, panel=panel, ticker=row.ticker,
        )
        observed = bool(out.observed_fully) and out.exit_px is not None
        if observed:
            pnl_pct = (float(out.exit_px) - float(row.entry_px)) / float(row.entry_px)
            pnl_dollars = (float(out.exit_px) - float(row.entry_px)) * float(row.qty)
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
    sd = float(r.std())
    out["mean_pnl_pct"] = round(float(r.mean()), 6)
    out["total_pnl_dollars"] = round(float(obs["pnl_dollars"].astype(float).sum()), 2)
    out["win_rate"] = round(float((r > 0).mean()), 4)
    out["info_ratio"] = round(float(r.mean() / sd), 4) if sd > 0 else None
    eq = (1.0 + r).cumprod()
    out["max_dd_pct"] = round(float(((eq.cummax() - eq) / eq.cummax()).max() * 100), 2)
    return out
