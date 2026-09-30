"""Run a policy over the frozen entry set with honest accounting.

Censoring is POLICY-DEPENDENT: a trade is dropped for a given policy only when
that policy needed bars past the data end. Aggregates therefore report the
censored count per policy, so a policy that looks good only because its losing
tail was censored is visible as such.
"""
from __future__ import annotations

import pandas as pd

from .engine import ExitPolicy, replay_position
from .gate import ROTATION_RULE
from .policies import FIT_END, VAL_END

#: Spec-mandated forward horizon, in TRADING days. This is a real cap: bars past
#: it are not walked, so an un-exited trade becomes censored rather than being
#: silently followed for another ~100 days (the original 400 was a CALENDAR
#: buffer that no code enforced as a horizon).
HORIZON_TRADING_DAYS = 180

#: Calendar buffer fetched, comfortably beyond 180 trading days (~260).
MAX_FORWARD_DAYS = 400

#: APPROXIMATION, stated rather than asserted away. Every MQR row was recorded
#: with qty=1 (all 29,736), so per-trade cash size is unrecoverable; and MQR sizes
#: with sizing_method="linear" (score-proportional, halved in bear regimes), NOT
#: equal weight. Treating each trade as one equal-weighted slot of capital/5 is
#: therefore an approximation forced by the data. Because the notional is constant
#: across trades and policies it is a monotone rescaling of summed percent return,
#: so the ordering is identical to ranking on summed return and no size
#: information enters the ranking at all.
CAPITAL = 100_000.0
MAX_HOLDINGS = 5
NOTIONAL_PER_POSITION = CAPITAL / MAX_HOLDINGS  # 20,000


def _bucket(entry_date: pd.Timestamp) -> str:
    if entry_date <= FIT_END:
        return "fit"
    if entry_date <= VAL_END:
        return "validate"
    return "out"


def forward_bars(panel, ticker: str, entry_date) -> pd.DataFrame:
    """Bars strictly after entry, truncated to the 180-trading-day horizon."""
    bars = panel.bars(ticker, entry_date,
                      entry_date + pd.Timedelta(days=MAX_FORWARD_DAYS))
    fwd = bars[bars["Date"] > pd.Timestamp(entry_date)]
    return fwd.head(HORIZON_TRADING_DAYS).reset_index(drop=True)


def price_exit_mask(entry_df: pd.DataFrame) -> pd.Series:
    """True where the trade exited on a PRICE rule rather than by rotation.

    Read DIRECTLY from the recorded reason (journal_trade.notes carries
    'backtest:<Reason>'), not inferred. The original design inferred this by
    replaying the baseline and testing reproduction, because it wrongly believed
    no reason was recorded; the recorded label is exact.
    """
    if "exit_reason" not in entry_df.columns:
        raise KeyError(
            "entry set has no exit_reason column; it is derived from "
            "journal_trade.notes by extract_entry_set -- use that rather than "
            "hand-building an entry frame"
        )
    return (entry_df["exit_reason"] != ROTATION_RULE).rename("price_exit")


def evaluate_policy(
    entry_df: pd.DataFrame,
    panel,
    policy: ExitPolicy,
    price_exit: pd.Series | None = None,
    fill: str = "close",
) -> pd.DataFrame:
    """Replay one policy over every frozen entry.

    ROTATION IS HELD FIXED, PRICE EXITS ARE NOT CAPPED.

    Capping every replay at the recorded exit date would impose a ceiling: a
    policy less aggressive than the baseline could never fire later and would be
    truncated at the same date, appearing identical to baseline -- which makes
    "would holding longer have been better?" unanswerable.

    So `price_exit` decides per trade:
      True  -> exited on a price rule; replay uncapped to the 180-trading-day
               horizon, so a wider or disabled stop is genuinely evaluated.
               This is an UPPER BOUND: rotation is still held fixed and could
               have removed the name sooner.
      False -> rotated out; cap at the recorded date, because rotation is
               deliberately fixed in phase 1.
    """
    if price_exit is None:
        price_exit = price_exit_mask(entry_df)
    flags = list(price_exit)

    rows = []
    for i, row in enumerate(entry_df.itertuples(index=False)):
        bars = forward_bars(panel, row.ticker, row.entry_date)
        out = replay_position(
            row.entry_px, row.entry_date, bars, policy,
            cap_date=None if flags[i] else row.exit_date,
            panel=panel, ticker=row.ticker, fill=fill,
        )
        rows.append(_row(row, out))
    return pd.DataFrame(rows)


def _row(row, out) -> dict:
    observed = bool(out.observed_fully) and out.exit_px is not None
    if observed:
        pnl_pct = (float(out.exit_px) - float(row.entry_px)) / float(row.entry_px)
        pnl_dollars = pnl_pct * NOTIONAL_PER_POSITION
    else:
        pnl_pct = None
        pnl_dollars = None
    return {
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
    }


def summarise(per_trade: pd.DataFrame) -> dict:
    """Aggregate on observed rows only; report the censored count separately.

    No annualised Sharpe: these are per-trade returns with no daily frequency, so
    a Sharpe would be undefined. `info_ratio` is the per-trade mean/std.
    """
    obs = per_trade[per_trade["observed_fully"]]
    n_total, n_obs = len(per_trade), len(obs)
    out = {"n_total": n_total, "n_observed": n_obs, "n_censored": n_total - n_obs}
    if n_obs == 0:
        out.update(mean_pnl_pct=None, sum_pnl_pct=None, total_pnl_dollars=None,
                   win_rate=None, info_ratio=None, max_dd_pct=None)
        return out

    r = obs["pnl_pct"].astype(float)
    d = obs["pnl_dollars"].astype(float)
    sd = float(r.std())
    out["mean_pnl_pct"] = round(float(r.mean()), 6)
    out["sum_pnl_pct"] = round(float(r.sum()), 4)
    out["total_pnl_dollars"] = round(float(d.sum()), 2)
    out["win_rate"] = round(float((r > 0).mean()), 4)
    out["info_ratio"] = round(float(r.mean() / sd), 4) if sd > 0 else None

    # Additive equity curve in dollars, ordered by exit date. Compounding
    # thousands of per-trade returns overflowed and produced inf.
    # NOTE: this is NOT a strategy drawdown -- there is no concurrency model and
    # every trade gets a fresh notional, so it is a comparative statistic only.
    ordered = obs.sort_values("exit_date", kind="stable")
    equity = CAPITAL + ordered["pnl_dollars"].astype(float).cumsum()
    peak = equity.cummax()
    out["max_dd_pct"] = round(float(((peak - equity) / peak).max() * 100), 2)
    return out
