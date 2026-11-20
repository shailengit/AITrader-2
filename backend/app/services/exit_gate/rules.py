"""Transparent rule gates -- the deterministic baseline for the veto experiment.

Every gate here is a named predicate over the position's own state. They exist
to answer "is there any selective exit-veto signal?" in minutes, before a model
or an LLM is trained. Two of them are controls: vetoing every trailing stop, and
vetoing every take profit, reproduce the unconditional levers phase 2 rejected.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from app.services.exit_gate.types import ExitContext, VetoDecision

Predicate = Callable[[ExitContext], bool]


@dataclass(frozen=True)
class RuleGate:
    """Veto a named rule when a pure predicate over the context says so."""

    gate_id: str
    veto_if: Mapping[str, Predicate]

    def decide(self, ctx: ExitContext) -> VetoDecision:
        pred = self.veto_if.get(ctx.rule)
        if pred is None:
            return VetoDecision(veto=False, gate_id=self.gate_id)
        veto = bool(pred(ctx))
        return VetoDecision(veto=veto, confidence=1.0 if veto else 0.0,
                            gate_id=self.gate_id)


#: Controls plus selective rules over position state only. All predicates are
#: pure functions of the context the adapter already computed, so none of them
#: can read a future bar.
RULE_GATES: dict[str, RuleGate] = {
    # ── controls: the unconditional levers already rejected in phase 2 ──
    "veto_all_trail": RuleGate(
        "rule:veto_all_trail", {"trailing_stop": lambda c: True}),
    "veto_all_tp": RuleGate(
        "rule:veto_all_tp", {"take_profit": lambda c: True}),
    "veto_all_time": RuleGate(
        "rule:veto_all_time", {"time_stop": lambda c: True}),

    # ── selective: is this pullback shallow, or is the position a winner? ──
    "veto_trail_if_in_profit": RuleGate(
        "rule:veto_trail_if_in_profit", {"trailing_stop": lambda c: c.ret > 0}),
    "veto_trail_if_big_winner": RuleGate(
        "rule:veto_trail_if_big_winner", {"trailing_stop": lambda c: c.ret > 0.20}),
    "veto_trail_if_shallow_pullback": RuleGate(
        "rule:veto_trail_if_shallow_pullback",
        {"trailing_stop": lambda c: c.drawdown_from_peak < 0.15}),
    "veto_trail_if_young": RuleGate(
        "rule:veto_trail_if_young", {"trailing_stop": lambda c: c.hold_days < 10}),
    "veto_trail_if_large_peak": RuleGate(
        "rule:veto_trail_if_large_peak", {"trailing_stop": lambda c: c.peak_gain > 0.30}),

    # ── selective: never lock in a gain while momentum is still positive ──
    "veto_tp_if_not_extended": RuleGate(
        "rule:veto_tp_if_not_extended", {"take_profit": lambda c: c.peak_gain > 0.50}),
    "veto_time_if_in_profit": RuleGate(
        "rule:veto_time_if_in_profit", {"time_stop": lambda c: c.ret > 0}),
}


def make_rule_gates() -> dict[str, RuleGate]:
    return dict(RULE_GATES)
