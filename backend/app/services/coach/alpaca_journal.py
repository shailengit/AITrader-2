"""Reconcile a live Alpaca account's positions into the Coach trade journal.

The multi-account Alpaca runners place real orders but never journal them, so
the Trade Coach has no live data to analyze. This module reconciles an
account's ACTUAL positions (from the Alpaca API) into `journal_trade`:

  - A position that exists on the account but has no open journal trade for
    that strategy+ticker → create an OPEN trade (entry from avg_entry_price).
  - A journal trade that is open but the position no longer exists on the
    account → CLOSE it, computing P&L from the account's recent closed fills
    (falling back to the last known price).

This is idempotent and self-healing: it reflects whatever the account actually
holds, so it captures forward-looking live performance without intercepting
order placement. Failure-isolated — never raises, never blocks the runner.

The strategy is keyed by its file stem (matching `_resolve_strategy`), so the
Coach badge and overview resolve it the same way as any other strategy.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.coach.journal import upsert_strategy
from app.models.journal import JournalTrade

logger = logging.getLogger(__name__)


def reconcile_account_positions(
    strategy_class_path: str,
    prefix: str,
    positions: List[Dict[str, Any]],
    closed_fills: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Sync an Alpaca account's positions into the Coach journal.

    strategy_class_path: the strategy file path (stem = journal strategy name).
    prefix: Alpaca credential prefix ('1', '2', '3', ...).
    positions: list of position dicts from AlpacaClient.get_positions().
    closed_fills: optional list from AlpacaClient.get_closed_fills() used to
        price exits. If omitted, exits use the position's last known price.

    Returns a summary dict {created, closed, errors} for logging.
    """
    result = {"created": 0, "closed": 0, "errors": 0}
    try:
        stem = Path(strategy_class_path).stem
        if not stem:
            return result
        from app.db.database import SessionLocal
        with SessionLocal() as db:
            strat = upsert_strategy(
                kind="manual",
                name=stem,
                params={"path": strategy_class_path, "origin": "alpaca_live", "prefix": prefix},
                session=db,
            )
            if strat is None:
                return result

            # Map ticker -> position for the account's current holdings.
            pos_by_ticker = {p.get("ticker", "").upper(): p for p in positions if p.get("ticker")}

            # Open journal trades for this strategy that are still open.
            open_trades = (
                db.query(JournalTrade)
                .filter(
                    JournalTrade.strategy_id == strat.id,
                    JournalTrade.exit_at.is_(None),
                )
                .all()
            )
            open_by_ticker = {t.ticker.upper(): t for t in open_trades}

            # 1. Create open trades for positions not yet journaled.
            for ticker, pos in pos_by_ticker.items():
                if ticker in open_by_ticker:
                    continue
                entry_px = pos.get("avg_entry_price")
                qty = pos.get("qty")
                if not entry_px or not qty:
                    continue
                db.add(JournalTrade(
                    strategy_id=strat.id,
                    ticker=ticker,
                    side="long" if qty > 0 else "short",
                    qty=abs(qty),
                    entry_px=float(entry_px),
                    entry_at=datetime.utcnow(),
                    notes=f"alpaca:{prefix}",
                ))
                result["created"] += 1

            # 2. Close journal trades whose position no longer exists.
            fills_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
            for f in (closed_fills or []):
                fills_by_symbol.setdefault(f.get("symbol", "").upper(), []).append(f)

            for ticker, t in open_by_ticker.items():
                if ticker in pos_by_ticker:
                    continue
                exit_px = None
                exit_at = None
                for f in fills_by_symbol.get(ticker, []):
                    if f.get("side") == "sell" and f.get("filled_avg_price"):
                        exit_px = float(f["filled_avg_price"])
                        exit_at = f.get("filled_at")
                        break
                if exit_px is None:
                    # Fall back to the position's last known price (current_price).
                    exit_px = pos_by_ticker.get(ticker, {}).get("current_price")
                if exit_px is None:
                    continue
                sign = 1 if t.side == "long" else -1
                t.exit_px = float(exit_px)
                t.exit_at = datetime.fromisoformat(exit_at) if exit_at else datetime.utcnow()
                t.pnl = (float(exit_px) - float(t.entry_px)) * float(t.qty) * sign
                t.pnl_pct = (float(exit_px) - float(t.entry_px)) / float(t.entry_px) * sign
                t.updated_at = datetime.utcnow()
                result["closed"] += 1

            db.commit()
    except Exception as e:
        logger.warning("Alpaca journal reconcile failed: %s", e)
        result["errors"] += 1
    return result
