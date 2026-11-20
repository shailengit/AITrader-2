"""Build the gate context from the adapter's own simulation state.

Pure and DB-free on purpose: every number here already exists inside the daily
loop, so this can be unit-tested without a database and cannot drift from what
the simulator actually knew at that date.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from app.services.exit_gate.types import (
    VETOABLE_RULES,
    ExitContext,
    ExitGate,
    GateOutcome,
    GateStats,
    consult_gate,
)
from app.services.strategy_base import Signal


def build_exit_context(
    *,
    ticker: str,
    current_date: str,
    holding: Mapping[str, Any],
    current_price: float,
    hold_days: int,
    rule: str,
    holdings: Mapping[str, Any],
    today_signals: Sequence[Signal],
    max_holdings: int,
    max_sector_count: int,
    top_k: int = 5,
) -> ExitContext:
    """Assemble what the gate may know when `rule` fires for `ticker`.

    `top_candidates` are the names the freed slot could actually buy today:
    ranked by today's signal score, excluding everything already held (which
    includes the triggering name), and respecting the sector cap against
    current holdings. Signal scores are as-of this date; no later bar is read.
    """
    sectors_held = Counter(
        (h.get("sector") or "Unknown") for h in holdings.values())

    feasible: list[tuple[str, float]] = []
    seen: set[str] = set()
    for sig in sorted(today_signals, key=lambda s: s.score, reverse=True):
        if sig.ticker in holdings or sig.ticker in seen:
            continue
        seen.add(sig.ticker)
        sector = sig.sector or "Unknown"
        if sectors_held.get(sector, 0) >= max_sector_count:
            continue
        feasible.append((sig.ticker, float(sig.score)))
        if len(feasible) >= top_k:
            break

    return ExitContext(
        ticker=ticker,
        as_of_date=current_date,
        rule=rule,
        entry_date=str(holding["entry_date"]),
        entry_price=float(holding["entry_price"]),
        peak_price=float(holding["peak_price"]),
        current_price=float(current_price),
        shares=int(holding["shares"]),
        hold_days=int(hold_days),
        sector=holding.get("sector") or "Unknown",
        market_cap=float(holding.get("market_cap") or 0.0),
        held_tickers=tuple(sorted(holdings)),
        n_open_slots=max(0, max_holdings - len(holdings)),
        top_candidates=tuple(feasible),
    )


def apply_exit_gate(
    gate: Optional[ExitGate],
    *,
    stats: Optional[GateStats],
    ticker: str,
    current_date: str,
    holding: Mapping[str, Any],
    current_price: float,
    hold_days: int,
    rule: str,
    holdings: Mapping[str, Any],
    today_signals: Sequence[Signal],
    max_holdings: int,
    max_sector_count: int,
    top_k: int = 5,
) -> GateOutcome:
    """Consult the gate for one fired rule and record the outcome.

    Short-circuits before building the context when there is no gate or the
    rule is not vetoable, so a run without a gate pays nothing for this hook.
    """
    if gate is None:
        outcome = GateOutcome(veto=False, status="no_gate")
    elif rule not in VETOABLE_RULES:
        outcome = GateOutcome(veto=False, status="not_vetoable")
    else:
        ctx = build_exit_context(
            ticker=ticker, current_date=current_date, holding=holding,
            current_price=current_price, hold_days=hold_days, rule=rule,
            holdings=holdings, today_signals=today_signals,
            max_holdings=max_holdings, max_sector_count=max_sector_count,
            top_k=top_k,
        )
        outcome = consult_gate(gate, ctx)
    if stats is not None:
        stats.record(outcome, rule)
    return outcome
