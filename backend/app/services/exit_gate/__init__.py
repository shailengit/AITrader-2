"""Pluggable exit veto gates for Strategy ABC backtests.

A gate is consulted only when a deterministic price rule fires, and may only
veto that exit. See `types.py` for the contract and `consult_gate` for the
fail-open policy.
"""
from app.services.exit_gate.types import (
    VETOABLE_RULES,
    ExitContext,
    ExitGate,
    GateOutcome,
    VetoDecision,
    consult_gate,
)

__all__ = [
    "VETOABLE_RULES",
    "ExitContext",
    "ExitGate",
    "GateOutcome",
    "VetoDecision",
    "consult_gate",
]
