"""Deterministic analytics over the trade journal. No LLM."""
from __future__ import annotations
import logging
import math
import uuid
from datetime import date as date_cls, datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import and_

from app.models.journal import JournalTrade, JournalStrategy, JournalStrategyRun, JournalMarketRegime, JournalSignal

logger = logging.getLogger(__name__)


def _closed_trades_query(session, period_start: date_cls, period_end: date_cls, strategy_id: Optional[uuid.UUID], source: Optional[str] = None):
    """Common base: closed trades in [period_start, period_end], optionally filtered by strategy and source."""
    q = session.query(JournalTrade).filter(
        JournalTrade.exit_at.isnot(None),
        JournalTrade.exit_at >= datetime.combine(period_start, datetime.min.time()),
        JournalTrade.exit_at <= datetime.combine(period_end, datetime.max.time()),
    )
    if strategy_id is not None:
        q = q.filter(JournalTrade.strategy_id == strategy_id)
    if source is not None:
        q = q.filter(JournalTrade.source == source)
    return q.order_by(JournalTrade.exit_at.asc())


def backtest_kpis(session, strategy_id: Optional[uuid.UUID], source: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """KPIs for backtest source, derived from per-run CAGR (% annualized).

    A multi-run backtest is N independent experiments (each its own $100k and
    randomized start date). Summing their position-sized dollar P&L onto one
    timeline is meaningless (it produced the ±billions / -$60M figures). The
    correct backtest KPIs come from each run's CAGR (annualized return),
    aggregated in backtest_analysis.run_summary (median/best/worst CAGR, win
    rate).

    Returns a KPI set in the same shape as kpis(), but with %-based CAGR values
    and kpi_mode='pct' so the frontend renders them as percentages. Also adds a
    `label` describing which experiment(s) the metrics refer to. Returns None
    when source isn't 'backtest' or there's no analysis to draw from.
    """
    if source != "backtest":
        return None
    from app.models.backtest_analysis import BacktestAnalysis
    from app.models.journal import JournalStrategy

    q = session.query(BacktestAnalysis)
    if strategy_id is not None:
        strat = session.get(JournalStrategy, strategy_id)
        if strat is None:
            return None
        q = q.filter(BacktestAnalysis.strategy_name == strat.name)
    rows = q.order_by(BacktestAnalysis.created_at.desc()).all()
    if not rows:
        return None

    # Latest analysis per strategy (a strategy may have several batches).
    latest: Dict[str, BacktestAnalysis] = {}
    for r in rows:
        if r.strategy_name not in latest:
            latest[r.strategy_name] = r

    medians = [float(a.run_summary["median_cagr_pct"]) for a in latest.values()
               if a.run_summary and a.run_summary.get("median_cagr_pct") is not None]
    bests = [float(a.run_summary["best_cagr_pct"]) for a in latest.values()
             if a.run_summary and a.run_summary.get("best_cagr_pct") is not None]
    worsts = [float(a.run_summary["worst_cagr_pct"]) for a in latest.values()
              if a.run_summary and a.run_summary.get("worst_cagr_pct") is not None]
    winrates = [float(a.run_summary["mean_win_rate_pct"]) for a in latest.values()
                if a.run_summary and a.run_summary.get("mean_win_rate_pct") is not None]
    if not medians:
        return None

    n_trades = sum(a.n_trades for a in latest.values())
    n_runs = sum(a.n_completed for a in latest.values())
    # Label describing which experiment(s) these metrics refer to.
    if len(latest) == 1:
        a = next(iter(latest.values()))
        created = a.created_at.strftime("%b %d, %Y") if a.created_at else ""
        label = f"{a.strategy_name} · {a.n_completed} runs · {created}"
    else:
        label = f"{len(latest)} strategies · latest batch each"
    return {
        "total_pnl": round(sum(medians) / len(medians), 2),
        "win_rate": round((sum(winrates) / len(winrates)) / 100.0, 4) if winrates else 0.0,
        "expectancy": round(max(bests), 2) if bests else 0.0,
        "n_trades": n_trades,
        "n_open": 0,
        "max_dd": round(min(worsts), 2) if worsts else 0.0,
        "current_dd": 0.0,
        "sharpe_proxy": 0.0,
        "kpi_mode": "pct",
        "label": label,
    }


def kpis(session, period_start: date_cls, period_end: date_cls, strategy_id: Optional[uuid.UUID], source: Optional[str] = None) -> Dict[str, Any]:
    closed = _closed_trades_query(session, period_start, period_end, strategy_id, source).all()
    n = len(closed)
    n_open_q = session.query(JournalTrade).filter(JournalTrade.exit_at.is_(None))
    if strategy_id is not None:
        n_open_q = n_open_q.filter(JournalTrade.strategy_id == strategy_id)
    if source is not None:
        n_open_q = n_open_q.filter(JournalTrade.source == source)
    n_open = n_open_q.count()
    if n == 0:
        return {
            "total_pnl": 0.0, "win_rate": 0.0, "expectancy": 0.0,
            "n_trades": 0, "n_open": n_open, "max_dd": 0.0, "current_dd": 0.0,
            "sharpe_proxy": 0.0,
        }
    pnls = [float(t.pnl or 0.0) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total_pnl = sum(pnls)
    win_rate = len(wins) / n if n else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    # max drawdown over the period
    eq = pd.Series(pnls).cumsum()
    running_max = eq.cummax()
    dd = (eq - running_max)
    max_dd = float(dd.min()) if len(dd) else 0.0
    current_dd = float(dd.iloc[-1]) if len(dd) else 0.0
    # Sharpe proxy = mean / std of per-trade returns (annualized proxy, 252 trading days)
    std = pd.Series(pnls).std(ddof=1) if n > 1 else 0.0
    sharpe = float((pd.Series(pnls).mean() / std) * math.sqrt(252)) if std and std > 0 else 0.0
    return {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 4),
        "expectancy": round(expectancy, 2),
        "n_trades": n,
        "n_open": n_open,
        "max_dd": round(max_dd, 2),
        "current_dd": round(current_dd, 2),
        "sharpe_proxy": round(sharpe, 4),
    }


def equity_curve(session, period_start: date_cls, period_end: date_cls, strategy_id: Optional[uuid.UUID], source: Optional[str] = None) -> List[Dict[str, Any]]:
    closed = _closed_trades_query(session, period_start, period_end, strategy_id, source).all()
    if not closed:
        return []
    rows = [{"date": t.exit_at.date().isoformat(), "equity": float(t.pnl or 0.0)} for t in closed]
    df = pd.DataFrame(rows)
    df["equity"] = df["equity"].cumsum()
    return df.to_dict(orient="records")


def drawdown_curve(session, period_start: date_cls, period_end: date_cls, strategy_id: Optional[uuid.UUID], source: Optional[str] = None) -> List[Dict[str, Any]]:
    eq = equity_curve(session, period_start, period_end, strategy_id, source)
    if not eq:
        return []
    df = pd.DataFrame(eq)
    df["running_max"] = df["equity"].cummax()
    df["dd"] = df["equity"] - df["running_max"]
    return df[["date", "dd"]].to_dict(orient="records")


# Module-level cache of ticker -> sector, so regime classification doesn't hit
# the DB once per trade (a backtest "All" window can have ~80k untagged trades).
_SECTOR_CACHE: Dict[str, str] = {}


def _classify_trade_regime(ticker: str, entry_date) -> Optional[str]:
    """Classify a trade's regime on-the-fly using the shared regime manager.

    Falls back to the Markov sector regime classifier when the trade wasn't
    tagged with a regime at journal time (e.g. backtest trades). Trains the
    shared manager on demand (no-op once trained per-process). Returns
    'BULL'/'BEAR' or None if it can't be classified.
    """
    if not ticker or not entry_date:
        return None
    try:
        from app.services.markov.regime_model import get_shared_regime_manager
        from app.services.data_service import DataService
        rm = get_shared_regime_manager()
        rm.ensure_trained()  # train on demand (no-op if already trained)
        if not rm.models:
            return None
        sector = _SECTOR_CACHE.get(ticker)
        if sector is None:
            meta = DataService.get_ticker_metadata(ticker)
            sector = (meta or {}).get("sector", "") or ""
            _SECTOR_CACHE[ticker] = sector
        if not sector:
            return None
        return rm.get_ticker_regime(ticker, sector, str(entry_date)[:10]).get("regime")
    except Exception:
        return None


def pnl_by_regime(session, period_start: date_cls, period_end: date_cls, strategy_id: Optional[uuid.UUID], source: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    closed = _closed_trades_query(session, period_start, period_end, strategy_id, source).all()
    # For backtest source, dollar P&L is a meaningless cross-run sum (each run
    # is its own $100k). Aggregate per-trade % return (pnl_pct) instead so the
    # regime plot shows meaningful relative performance.
    use_pct = source == "backtest"
    out: Dict[str, Dict[str, Any]] = {}
    for t in closed:
        regime = t.regime_at_exit or t.regime_at_entry
        if not regime:
            # Not tagged at journal time — classify on-the-fly via the shared
            # regime manager (Markov) so the plot isn't "unknown".
            regime = _classify_trade_regime(t.ticker, t.entry_at)
        regime = regime or "unknown"
        bucket = out.setdefault(regime, {"n": 0, "pnl": 0.0, "pnl_pct_sum": 0.0})
        bucket["n"] += 1
        if use_pct:
            bucket["pnl"] += float(t.pnl_pct or 0.0)
        else:
            bucket["pnl"] += float(t.pnl or 0.0)
        bucket["pnl_pct_sum"] += float(t.pnl_pct or 0.0)
    for v in out.values():
        v["pnl"] = round(v["pnl"], 2)
        v["pnl_pct"] = round(v["pnl_pct_sum"] / v["n"], 4) if v["n"] else 0.0
        del v["pnl_pct_sum"]
    return out


def mae_mfe_scatter(session, period_start: date_cls, period_end: date_cls, strategy_id: Optional[uuid.UUID], source: Optional[str] = None) -> List[Dict[str, Any]]:
    closed = _closed_trades_query(session, period_start, period_end, strategy_id, source).all()
    out = []
    for t in closed:
        out.append({
            "mae": float(t.mae) if t.mae is not None else None,
            "mfe": float(t.mfe) if t.mfe is not None else None,
            "pnl": float(t.pnl) if t.pnl is not None else None,
            "ticker": t.ticker,
            "entry_at": t.entry_at.isoformat() if t.entry_at else None,
        })
    return out


def win_rate_by_strategy(session, period_start: date_cls, period_end: date_cls, source: Optional[str] = None) -> List[Dict[str, Any]]:
    # For backtest source, the journaled trades are flattened across all
    # independent runs, so a period-window win rate is meaningless (it produced
    # e.g. 0.037 for a strategy whose true per-run win rate is ~40%). Use the
    # per-run mean win rate from backtest_analysis.run_summary instead.
    if source == "backtest":
        from app.models.backtest_analysis import BacktestAnalysis
        rows = (session.query(BacktestAnalysis)
                .order_by(BacktestAnalysis.created_at.desc()).all())
        latest: Dict[str, BacktestAnalysis] = {}
        for r in rows:
            if r.strategy_name not in latest:
                latest[r.strategy_name] = r
        bt_rows = []
        for name, a in latest.items():
            wr = (a.run_summary or {}).get("mean_win_rate_pct")
            bt_rows.append({
                "strategy_id": str(a.id),
                "name": name,
                "n": a.n_completed,
                "win_rate": round(wr / 100.0, 4) if wr is not None else 0.0,
            })
        bt_rows.sort(key=lambda r: r["win_rate"], reverse=True)
        return bt_rows

    q = (session.query(JournalStrategy, JournalTrade)
         .join(JournalTrade, JournalTrade.strategy_id == JournalStrategy.id)
         .filter(JournalTrade.exit_at.isnot(None))
         .filter(JournalTrade.exit_at >= datetime.combine(period_start, datetime.min.time()))
         .filter(JournalTrade.exit_at <= datetime.combine(period_end, datetime.max.time())))
    if source is not None:
        q = q.filter(JournalTrade.source == source)
    out: Dict[uuid.UUID, Dict[str, Any]] = {}
    for strat, t in q.all():
        bucket = out.setdefault(strat.id, {"strategy_id": str(strat.id), "name": strat.name, "n": 0, "wins": 0})
        bucket["n"] += 1
        if t.pnl is not None and float(t.pnl) > 0:
            bucket["wins"] += 1
    rows = []
    for v in out.values():
        v["win_rate"] = round(v["wins"] / v["n"], 4) if v["n"] else 0.0
        del v["wins"]
        rows.append(v)
    rows.sort(key=lambda r: r["win_rate"], reverse=True)
    return rows


def entry_timing_lag(session, period_start: date_cls, period_end: date_cls, strategy_id: Optional[uuid.UUID]) -> Dict[str, Any]:
    """Days between the originating signal's as_of_date and the trade's entry_at."""
    q = (session.query(JournalSignal, JournalTrade)
         .join(JournalTrade, JournalTrade.signal_id == JournalSignal.id)
         .filter(JournalTrade.entry_at >= datetime.combine(period_start, datetime.min.time()))
         .filter(JournalTrade.entry_at <= datetime.combine(period_end, datetime.max.time())))
    if strategy_id is not None:
        q = q.filter(JournalTrade.strategy_id == strategy_id)
    lags = []
    for sig, t in q.all():
        if sig.as_of_date and t.entry_at:
            lag = (t.entry_at.date() - sig.as_of_date).days
            if lag >= 0:
                lags.append(lag)
    if not lags:
        return {"p25": 0, "p50": 0, "p75": 0, "mean": 0.0, "n": 0}
    s = pd.Series(lags)
    return {
        "p25": int(s.quantile(0.25)),
        "p50": int(s.quantile(0.50)),
        "p75": int(s.quantile(0.75)),
        "mean": round(float(s.mean()), 2),
        "n": len(lags),
    }


def strategy_correlation_matrix(session, period_start: date_cls, period_end: date_cls, source: Optional[str] = None) -> Dict[str, Any]:
    q = (session.query(JournalStrategy.name, JournalTrade.exit_at, JournalTrade.pnl)
         .join(JournalTrade, JournalTrade.strategy_id == JournalStrategy.id)
         .filter(JournalTrade.exit_at.isnot(None))
         .filter(JournalTrade.exit_at >= datetime.combine(period_start, datetime.min.time()))
         .filter(JournalTrade.exit_at <= datetime.combine(period_end, datetime.max.time())))
    if source is not None:
        q = q.filter(JournalTrade.source == source)
    rows = [(n, d.date().isoformat(), float(p or 0.0)) for n, d, p in q.all()]
    if not rows:
        return {"strategies": [], "matrix": []}
    df = pd.DataFrame(rows, columns=["name", "date", "pnl"]).pivot_table(index="date", columns="name", values="pnl", aggfunc="sum").fillna(0.0)
    corr = df.corr().fillna(0.0)
    strategies = list(corr.columns)
    matrix = [[round(float(corr.loc[a, b]), 4) for b in strategies] for a in strategies]
    return {"strategies": strategies, "matrix": matrix}


def recent_trades(session, strategy_id: Optional[uuid.UUID], n: int = 20, source: Optional[str] = None) -> List[Dict[str, Any]]:
    q = session.query(JournalTrade)
    if strategy_id is not None:
        q = q.filter(JournalTrade.strategy_id == strategy_id)
    if source is not None:
        q = q.filter(JournalTrade.source == source)
    rows = q.order_by(JournalTrade.entry_at.desc()).limit(n).all()
    return [t.to_dict() for t in rows]


def regime_timeline(session, period_start: date_cls, period_end: date_cls) -> List[Dict[str, Any]]:
    rows = (session.query(JournalMarketRegime)
            .filter(JournalMarketRegime.date >= period_start)
            .filter(JournalMarketRegime.date <= period_end)
            .order_by(JournalMarketRegime.date.asc()).all())
    return [{"date": r.date.isoformat(), "regime": r.regime, "confidence": float(r.confidence) if r.confidence is not None else None} for r in rows]


def overview(session, period_start: date_cls, period_end: date_cls, strategy_id: Optional[uuid.UUID], source: Optional[str] = None) -> Dict[str, Any]:
    return {
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "source": source,
        "kpis": kpis(session, period_start, period_end, strategy_id, source),
        "equity_curve": equity_curve(session, period_start, period_end, strategy_id, source),
        "drawdown_curve": drawdown_curve(session, period_start, period_end, strategy_id, source),
        "pnl_by_regime": pnl_by_regime(session, period_start, period_end, strategy_id, source),
        "win_rate_by_strategy": win_rate_by_strategy(session, period_start, period_end, source),
        "entry_timing_lag": entry_timing_lag(session, period_start, period_end, strategy_id),
    }
