"""Alpaca live-trading status API.

Surfaces the live paper/live Alpaca account state so the Command Center's
"Live P&L" card can show the currently-deployed strategy's equity and P&L
without requiring a manual deploy in Strategy Lab.

Supports multiple Alpaca paper accounts. Each account maps to a credential
prefix (see AlpacaClient): the default (no prefix) account, the "LS" account,
and the "3" account. The account number and friendly label are derived at
runtime from the /account response where possible.
"""
from __future__ import annotations

import datetime
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.services.alpaca_client import AlpacaClient
from app.services.deployments_registry import get_active_deployment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alpaca", tags=["alpaca"])

# Matches the runner's fallback strategy when no deployment is active
# (see app/services/alpaca_runner.py:_load_active_strategy_class).
DEFAULT_STRATEGY_NAME = "Golden Cross Rotation v2"

# Account registry: (friendly label, credential prefix).
#   ""  -> ALPACA_API_KEY / ALPACA_SECRET_KEY        (default account)
#   "LS"-> ALPACA_LS_API_KEY / ALPACA_LS_SECRET_KEY
#   "3" -> ALPACA_3_API_KEY / ALPACA_3_SECRET_KEY
ACCOUNT_PREFIXES: List[Tuple[str, str]] = [
    ("MomentumQualityRotation", ""),
    ("DailyGoldenCrossRotation", "LS"),
    ("SectorScannerTop5Rotation", "3"),
]

# Account number -> friendly label, derived at runtime from /account.
# Unknown account numbers fall back to the configured label.
ACCOUNT_NUMBER_LABELS: Dict[str, str] = {
    "PA3QALHOBO67": "MomentumQualityRotation",
    "PA3EW6COMH40": "DailyGoldenCrossRotation",
    "PA3Q31C2WTO3": "SectorScannerTop5Rotation",
}


def get_session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _strategy_name_from_path(strategy_path: str) -> str:
    """Humanize a strategy file path into a display name."""
    stem = Path(strategy_path).stem
    # snake_case -> Title Case
    return stem.replace("_", " ").replace("-", " ").title()


def _resolve_strategy_name(db: Session) -> str:
    """Return the active deployment's name, or the default fallback."""
    d = get_active_deployment(db)
    if d is None or not d.strategy_path:
        return DEFAULT_STRATEGY_NAME
    return _strategy_name_from_path(d.strategy_path)


def _is_configured() -> bool:
    """True if the primary Alpaca keys are set (paper account by default)."""
    return bool(
        os.getenv("ALPACA_API_KEY")
        and os.getenv("ALPACA_SECRET_KEY")
    )


def _resolve_label(label: str, account_number: Optional[str]) -> str:
    """Prefer the runtime account number to pick a friendly label."""
    if account_number and account_number in ACCOUNT_NUMBER_LABELS:
        return ACCOUNT_NUMBER_LABELS[account_number]
    return label


def _build_live_account(label: str, prefix: str) -> Dict[str, Any]:
    """Fetch live state for one account; never raises."""
    try:
        client = AlpacaClient(prefix=prefix)
    except ValueError as e:  # missing/invalid keys
        return {"label": label, "configured": False, "reason": str(e)}

    try:
        account = client.get_account()
        positions = client.get_positions()
    except Exception as e:
        logger.warning("Alpaca live fetch failed for %s: %s", label, e)
        return {"label": label, "configured": False, "reason": f"Alpaca fetch error: {e}"}

    total_unrealized_pl = sum(p.get("unrealized_pl", 0.0) for p in positions)
    total_market_value = sum(p.get("market_value", 0.0) for p in positions)
    total_unrealized_pl_pct = (
        total_unrealized_pl / total_market_value if total_market_value else 0.0
    )
    account_number = account.get("account_number")

    return {
        "label": _resolve_label(label, account_number),
        "account_number": account_number,
        "configured": True,
        "paper": client.paper,
        "account": {
            "equity": account.get("equity"),
            "cash": account.get("cash"),
            "buying_power": account.get("buying_power"),
        },
        "n_positions": len(positions),
        "positions": positions,
        "total_unrealized_pl": round(total_unrealized_pl, 2),
        "total_unrealized_pl_pct": round(total_unrealized_pl_pct, 4),
    }


def _build_equity_account(label: str, prefix: str, period: str, timeframe: str) -> Dict[str, Any]:
    """Fetch equity history for one account; never raises."""
    try:
        client = AlpacaClient(prefix=prefix)
    except ValueError as e:
        return {"label": label, "configured": False, "reason": str(e)}

    try:
        hist = client.get_portfolio_history(period=period, timeframe=timeframe)
    except Exception as e:
        logger.warning("Alpaca equity-curve fetch failed for %s: %s", label, e)
        return {"label": label, "configured": False, "reason": f"Alpaca fetch error: {e}"}

    # Convert epoch timestamps (seconds) to YYYY-MM-DD and pair with equity.
    dates = []
    for ts in hist.get("dates", []):
        try:
            dates.append(datetime.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d"))
        except (TypeError, ValueError):
            dates.append(str(ts))
    equity = hist.get("equity", [])

    account_number = None
    try:
        account_number = client.get_account().get("account_number")
    except Exception:
        pass

    return {
        "label": _resolve_label(label, account_number),
        "account_number": account_number,
        "configured": True,
        "period": period,
        "dates": dates,
        "equity": equity,
        "start_equity": equity[0] if equity else None,
        "end_equity": equity[-1] if equity else None,
        "change": (equity[-1] - equity[0]) if len(equity) >= 2 else None,
        "change_pct": ((equity[-1] / equity[0]) - 1) if len(equity) >= 2 and equity[0] else None,
    }


@router.get("/live")
def get_live(
    db: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Return live account equity, open positions, and unrealized P&L for all accounts."""
    accounts = [_build_live_account(label, prefix) for label, prefix in ACCOUNT_PREFIXES]
    if not any(a.get("configured") for a in accounts):
        return {
            "configured": False,
            "reason": "No Alpaca accounts are configured (check the root .env keys)",
            "accounts": accounts,
        }

    return {
        "configured": True,
        "strategy_name": _resolve_strategy_name(db),
        "accounts": accounts,
    }


@router.get("/equity-curve")
def get_equity_curve(
    period: str = "3M",
    timeframe: str = "1D",
) -> Dict[str, Any]:
    """Return each account's equity curve (portfolio history) over a period."""
    accounts = [
        _build_equity_account(label, prefix, period, timeframe)
        for label, prefix in ACCOUNT_PREFIXES
    ]
    if not any(a.get("configured") for a in accounts):
        return {
            "configured": False,
            "reason": "No Alpaca accounts are configured (check the root .env keys)",
            "accounts": accounts,
        }

    return {
        "configured": True,
        "period": period,
        "accounts": accounts,
    }
