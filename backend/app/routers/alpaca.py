"""Alpaca live-trading status API.

Surfaces the live paper/live Alpaca account state so the Command Center's
"Live P&L" card can show the currently-deployed strategy's equity and P&L
without requiring a manual deploy in Strategy Lab.

Supports multiple Alpaca paper accounts. Each account maps to a credential
prefix (see AlpacaClient): the "1", "2", and "3" accounts. The friendly label is
the account's own name from ALPACA_<n>_NAME in the root .env (never a strategy
name), and the account number is the live value from the /account response.
"""
from __future__ import annotations

import datetime
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.services.alpaca_client import AlpacaClient
from app.services.deployments_registry import get_active_deployment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alpaca", tags=["alpaca"])

# Matches the runner's fallback strategy when no deployment is active
# (see app/services/alpaca_runner.py:_load_active_strategy_class).
DEFAULT_STRATEGY_NAME = "Golden Cross Rotation v2"

# Account registry: credential prefixes, in display order.
#   "1" -> ALPACA_1_API_KEY / ALPACA_1_SECRET_KEY / ALPACA_1_NAME
#   "2" -> ALPACA_2_API_KEY / ALPACA_2_SECRET_KEY / ALPACA_2_NAME
#   "3" -> ALPACA_3_API_KEY / ALPACA_3_SECRET_KEY / ALPACA_3_NAME
#
# The display label is the account's OWN name — ALPACA_<n>_NAME in the root
# .env ("Acct#1" …) — not the strategy currently deployed on it, so the label
# stays true when a strategy moves account.
#
# Read through os.getenv, like ALPACA_<n>_API_KEY: main.py loads .env with
# python-dotenv at *startup* (override=True) and nothing re-reads it per request,
# so a rename in .env needs a backend restart (`launchctl kickstart -k
# gui/$(id -u)/com.tradecraft.alpaca-backend`) before it appears here.
ACCOUNT_PREFIXES: List[str] = ["1", "2", "3"]


def _account_label(prefix: str) -> str:
    """Display name for one account, from ALPACA_<n>_NAME in .env.

    Falls back to "Account <n>" when the key is unset or blank.
    """
    env_key = f"ALPACA_{prefix}_NAME" if prefix else "ALPACA_NAME"
    name = (os.getenv(env_key) or "").strip()
    if name:
        return name
    return f"Account {prefix}" if prefix else "Account"


def _account_registry() -> List[Tuple[str, str]]:
    """(display label, credential prefix) for each configured account."""
    return [(_account_label(prefix), prefix) for prefix in ACCOUNT_PREFIXES]


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


def _build_live_account(prefix: str) -> Dict[str, Any]:
    """Fetch live state for one account; never raises."""
    label = _account_label(prefix)
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
        "label": label,
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


def _build_equity_account(prefix: str, period: str, timeframe: str) -> Dict[str, Any]:
    """Fetch equity history for one account; never raises."""
    label = _account_label(prefix)
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
        "label": label,
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
    accounts = [_build_live_account(prefix) for prefix in ACCOUNT_PREFIXES]
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
        _build_equity_account(prefix, period, timeframe)
        for prefix in ACCOUNT_PREFIXES
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


# ── Account admin (liquidate / update keys) ──────────────────────────

class UpdateKeysRequest(BaseModel):
    api_key: str
    secret_key: str
    account_number: Optional[str] = None


@router.post("/{prefix}/liquidate")
def liquidate_account(prefix: str) -> Dict[str, Any]:
    """Cancel all open orders and close all positions on a paper account."""
    from app.services.alpaca_account_admin import liquidate_account as _liq
    try:
        return _liq(prefix)
    except Exception as e:
        raise HTTPException(500, detail={"error": str(e)})


@router.post("/{prefix}/update-keys")
def update_account_keys(prefix: str, body: UpdateKeysRequest) -> Dict[str, Any]:
    """Swap an account's API key/secret in .env and its account number in
    strategy_accounts.py. The account number is auto-fetched from Alpaca using
    the new keys if not provided, so the user only pastes the two keys."""
    from app.services.alpaca_account_admin import update_account_keys as _upd
    try:
        return _upd(prefix, body.api_key, body.secret_key, body.account_number)
    except ValueError as e:
        raise HTTPException(400, detail={"error": str(e)})
    except Exception as e:
        raise HTTPException(500, detail={"error": str(e)})
