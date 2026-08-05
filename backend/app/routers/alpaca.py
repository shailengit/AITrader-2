"""Alpaca live-trading status API.

Surfaces the live paper/live Alpaca account state so the Command Center's
"Live P&L" card can show the currently-deployed strategy's equity and P&L
without requiring a manual deploy in Strategy Lab.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

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


@router.get("/live")
def get_live(
    db: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Return live account equity, open positions, and unrealized P&L."""
    if not _is_configured():
        return {
            "configured": False,
            "reason": "Alpaca API keys are not set in backend/.env",
        }

    try:
        client = AlpacaClient()
        account = client.get_account()
        positions = client.get_positions()
    except ValueError as e:  # missing/invalid keys
        return {"configured": False, "reason": str(e)}
    except Exception as e:
        logger.warning("Alpaca live fetch failed: %s", e)
        return {"configured": False, "reason": f"Alpaca fetch error: {e}"}

    total_unrealized_pl = sum(p.get("unrealized_pl", 0.0) for p in positions)
    total_market_value = sum(p.get("market_value", 0.0) for p in positions)
    total_unrealized_pl_pct = (
        total_unrealized_pl / total_market_value if total_market_value else 0.0
    )

    return {
        "configured": True,
        "paper": client.paper,
        "strategy_name": _resolve_strategy_name(db),
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
