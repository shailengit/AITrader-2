from typing import Dict, Any, Optional
from pathlib import Path
import json

from sqlalchemy.orm import Session

from app.services.deployments_registry import get_active_deployment
from app.services.coach.journal import list_fills_for_strategy, list_runs_for_strategy


def _path_stem(p: str) -> str:
    return Path(p).stem


def _live_account_summary(strategy_path: str, db: Session) -> Optional[Dict[str, Any]]:
    """Pull live performance for a multi-account running strategy from Alpaca.

    Returns a dict of live fields (is_deployed, live_pnl, n_live_trades,
    current_regime, account_number, n_positions) for strategies that are
    currently running on their own Alpaca account (see strategy_accounts.py).
    Returns None when the strategy is not a running multi-account strategy or
    the Alpaca fetch fails (never raises).
    """
    stem = _path_stem(strategy_path)
    if not stem:
        return None
    try:
        from app.services.strategy_accounts import running_strategy_by_stem
        from app.services.alpaca_client import AlpacaClient
        from app.models.journal import JournalMarketRegime

        rs = running_strategy_by_stem(stem)
        if rs is None:
            return None
        client = AlpacaClient(prefix=rs.prefix)
        account = client.get_account()
        positions = client.get_positions()
        live_pnl = sum(p.get("unrealized_pl", 0.0) for p in positions)
        n_live_trades = len(positions)

        # Current regime: latest market regime on record, else UNKNOWN.
        current_regime = "UNKNOWN"
        try:
            latest = (
                db.query(JournalMarketRegime)
                .order_by(JournalMarketRegime.date.desc())
                .first()
            )
            if latest is not None:
                current_regime = latest.regime
        except Exception:
            pass

        return {
            "is_deployed": True,
            "deployed_at": None,
            "live_pnl": round(live_pnl, 2),
            "n_live_trades": n_live_trades,
            "current_regime": current_regime,
            "account_number": account.get("account_number"),
            "n_positions": n_live_trades,
        }
    except Exception:
        return None


def _normalize_backtested(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a journaled run's result_summary into the badge's expected shape.

    The badge expects `backtested.total_return` as a FRACTION (1.0 = 100%) and
    `backtested.sharpe`. Journaled Strategy Lab runs store `total_return_pct`
    (percent) and `sharpe_ratio`. Convert so the badge renders correctly.
    """
    if not summary:
        return {}
    out = dict(summary)
    trp = out.get("total_return_pct")
    if trp is not None and "total_return" not in out:
        out["total_return"] = float(trp) / 100.0
    if out.get("sharpe_ratio") is not None and "sharpe" not in out:
        out["sharpe"] = float(out["sharpe_ratio"])
    return out


def _sidecar_meta_fallback(strategy_path: str) -> Dict[str, Any]:
    """Read backtest KPIs from the strategy's sidecar .meta.json (no DB needed).

    Strategy classes ship performance KPIs in a co-located `<stem>.meta.json`
    file (the same source that populates the Library table's CAGR/Sharpe/etc.
    columns). The Coach badge normally gets backtest metrics from journaled
    runs, but strategies that were never run through a journaled batch have no
    runs yet still carry these KPIs — fall back to the meta file for them.

    Returns a payload shaped like a run's `result_summary`:
        total_return (fractional, 1.0 = 100%), sharpe, plus the raw meta fields.
    Returns {} when no meta file exists or it can't be parsed.
    """
    stem = _path_stem(strategy_path)
    if not stem:
        return {}
    strategies_dir = Path(__file__).resolve().parent.parent / "strategies"
    meta_path = strategies_dir / f"{stem}.meta.json"
    if not meta_path.exists():
        return {}
    try:
        meta = json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    summary = {}
    total_return_pct = meta.get("total_return_pct")
    if total_return_pct is not None:
        summary["total_return"] = float(total_return_pct) / 100.0
    if meta.get("sharpe_ratio") is not None:
        summary["sharpe"] = float(meta["sharpe_ratio"])
    for key in ("cagr_pct", "win_rate", "max_drawdown_pct", "total_trades", "last_backtest"):
        if meta.get(key) is not None:
            summary[key] = meta[key]
    return summary


def aggregate_strategy_summary(strategy_path: str, db: Session) -> Dict[str, Any]:
    active = get_active_deployment(db)
    # The deployments registry stores an ABSOLUTE path while the coach endpoint
    # is called with a RELATIVE path; compare on the strategy file stem.
    is_deployed_this = active is not None and _path_stem(active.strategy_path) == _path_stem(strategy_path)

    # A multi-account running strategy (see strategy_accounts.py) is deployed
    # on its own Alpaca account. Prefer its live account data when present —
    # this covers the 3-account setup that the single-active registry can't.
    live = _live_account_summary(strategy_path, db)
    is_deployed = bool(live and live.get("is_deployed")) or is_deployed_this

    fills = list_fills_for_strategy(strategy_path, db=db) if is_deployed else []
    runs = list_runs_for_strategy(strategy_path, db=db)

    # Live P&L: prefer the live Alpaca account, else journaled fills.
    if live:
        live_pnl = live.get("live_pnl", 0.0)
        n_live_trades = live.get("n_live_trades", 0)
        current_regime = live.get("current_regime", "UNKNOWN")
    else:
        live_pnl = sum(float(f.get("pnl", 0)) for f in fills) if fills else 0.0
        n_live_trades = len(fills)
        # Current regime: simplest — derive from the most recent fill's date
        current_regime = "UNKNOWN"
        if fills:
            current_regime = fills[0].get("regime", "UNKNOWN")

    # Regime attribution
    regime_attribution: Dict[str, Dict[str, Any]] = {}
    for f in fills:
        r = f.get("regime", "UNKNOWN")
        slot = regime_attribution.setdefault(r, {"n_trades": 0, "win_rate": 0.0, "total_pnl": 0.0, "wins": 0})
        slot["n_trades"] += 1
        slot["total_pnl"] += float(f.get("pnl", 0))
        if float(f.get("pnl", 0)) > 0:
            slot["wins"] += 1
    for r, slot in regime_attribution.items():
        slot["win_rate"] = slot["wins"] / slot["n_trades"] if slot["n_trades"] else 0.0

    # Backtested fallback: prefer the most recent journaled run, else fall
    # back to the sidecar .meta.json (strategies that were backtested but never
    # run through a journaled batch still carry their KPIs in the meta file).
    backtested = {}
    if runs:
        last = runs[0]
        backtested = _normalize_backtested(last.get("summary", {}))
    if not backtested:
        backtested = _sidecar_meta_fallback(strategy_path)

    return {
        "strategy_path": strategy_path,
        "is_deployed": is_deployed,
        "deployed_at": active.deployed_at.isoformat() if (active and is_deployed_this) else (live.get("deployed_at") if live else None),
        "account_number": live.get("account_number") if live else None,
        "n_positions": live.get("n_positions") if live else None,
        "n_live_trades": n_live_trades,
        "live_pnl": live_pnl,
        "live_sharpe_30d": 0.0,  # placeholder; compute from fill timeseries
        "current_regime": current_regime,
        "regime_attribution": regime_attribution,
        "drift": {
            "live_equity": [],
            "backtested_equity": [],
            "max_divergence_pct": 0.0,
            "alert": False,
        },
        "last_5_trades": fills[:5],
        "backtested": backtested,
        "coach_insight": "",
    }
