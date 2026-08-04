from typing import Dict, Any
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.deployments_registry import get_active_deployment
from app.services.coach.journal import list_fills_for_strategy, list_runs_for_strategy


def _path_stem(p: str) -> str:
    return Path(p).stem


def aggregate_strategy_summary(strategy_path: str, db: Session) -> Dict[str, Any]:
    active = get_active_deployment(db)
    # The deployments registry stores an ABSOLUTE path while the coach endpoint
    # is called with a RELATIVE path; compare on the strategy file stem.
    is_deployed_this = active is not None and _path_stem(active.strategy_path) == _path_stem(strategy_path)

    fills = list_fills_for_strategy(strategy_path, db=db) if is_deployed_this else []
    runs = list_runs_for_strategy(strategy_path, db=db)

    # Live P&L
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

    # Backtested fallback
    backtested = {}
    if runs:
        last = runs[0]
        backtested = last.get("summary", {})

    return {
        "strategy_path": strategy_path,
        "is_deployed": is_deployed_this,
        "deployed_at": active.deployed_at.isoformat() if (active and is_deployed_this) else None,
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
