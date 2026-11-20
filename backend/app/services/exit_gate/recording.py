"""Recording gate: observe every exit decision, change nothing.

The point is to collect the true distribution of decision contexts from the
real simulator (not from a frozen entry set), so an LLM or model pilot can be
asked the questions the strategy would actually face.
"""
from __future__ import annotations

from typing import List, Set, Tuple

from app.services.exit_gate.types import ExitContext, VetoDecision


class RecordingGate:
    """Append-only observer. Always lets the exit proceed."""

    gate_id = "record"

    def __init__(self) -> None:
        self.contexts: List[ExitContext] = []
        self._seen: Set[Tuple[str, str, str, str]] = set()

    def decide(self, ctx: ExitContext) -> VetoDecision:
        self.contexts.append(ctx)
        self._seen.add(self._identity(ctx))
        return VetoDecision(veto=False, gate_id=self.gate_id)

    @staticmethod
    def _identity(ctx: ExitContext) -> Tuple[str, str, str, str]:
        # The same position, date and rule is the same decision question; the
        # price is determined by those four and need not be part of the key.
        return (ctx.ticker, ctx.entry_date, ctx.as_of_date, ctx.rule)

    def unique_contexts(self) -> List[ExitContext]:
        out, seen = [], set()
        for ctx in self.contexts:
            k = self._identity(ctx)
            if k in seen:
                continue
            seen.add(k)
            out.append(ctx)
        return out
