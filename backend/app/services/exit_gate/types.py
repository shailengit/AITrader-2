"""Exit-gate contracts: the context a gate sees and the decision it returns.

A gate may only ever VETO a price exit; it can never create one. That keeps the
gate causal (it sees the simulation's own state at date t), keeps it
reversible (a veto merely defers to the next day's rule check), and keeps tail
risk out of a model's hands: hard stops, strategy exits and rotation are not
vetoable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Protocol

#: Rules a gate is allowed to override. Everything else is a hard constraint.
VETOABLE_RULES = frozenset({"trailing_stop", "take_profit", "time_stop"})


@dataclass(frozen=True)
class ExitContext:
    """What a gate is told when a price rule fires.

    `ret`, `peak_gain` and `drawdown_from_peak` are derived from the prices
    rather than passed in, so a caller cannot hand a gate numbers that
    disagree with the position it is describing.
    """

    ticker: str
    as_of_date: str
    rule: str                      # exit_priority token, not the display string
    entry_date: str
    entry_price: float
    peak_price: float
    current_price: float
    shares: int
    hold_days: int
    sector: str
    market_cap: float
    # Replacement opportunity: what the freed slot would buy today. Ignoring
    # this is what made phase 2's frozen-entry ranking wrong.
    held_tickers: tuple[str, ...] = ()
    n_open_slots: int = 0
    top_candidates: tuple[tuple[str, float], ...] = ()
    features: Mapping[str, float] = field(default_factory=dict)

    @property
    def ret(self) -> float:
        return self.current_price / self.entry_price - 1.0

    @property
    def peak_gain(self) -> float:
        return self.peak_price / self.entry_price - 1.0

    @property
    def drawdown_from_peak(self) -> float:
        return 1.0 - self.current_price / self.peak_price


@dataclass(frozen=True)
class VetoDecision:
    veto: bool = False
    confidence: float = 0.0
    reason: str = ""
    gate_id: str = ""


class ExitGate(Protocol):
    gate_id: str

    def decide(self, ctx: ExitContext) -> VetoDecision:
        ...


@dataclass(frozen=True)
class GateOutcome:
    """Result of consulting a gate, with a status for the experiment's counters."""

    veto: bool
    status: str                       # no_gate | not_vetoable | vetoed | accepted | error
    decision: Optional[VetoDecision] = None
    detail: str = ""


@dataclass
class GateStats:
    """How often a gate was asked, how often it held, and how often it broke."""

    consultations: int = 0            # actual gate calls: vetoed + accepted + error
    vetoes: int = 0
    fail_open: int = 0                # errors and malformed decisions
    not_vetoable: int = 0             # rule this gate is not allowed to touch
    no_gate: int = 0
    by_rule: dict[str, int] = field(default_factory=dict)

    @property
    def fail_open_rate(self) -> float:
        return self.fail_open / self.consultations if self.consultations else 0.0

    def record(self, outcome: GateOutcome, rule: str) -> None:
        if outcome.status in ("vetoed", "accepted", "error"):
            self.consultations += 1
            self.by_rule[rule] = self.by_rule.get(rule, 0) + 1
        elif outcome.status == "not_vetoable":
            self.not_vetoable += 1
        else:
            self.no_gate += 1
        if outcome.veto:
            self.vetoes += 1
        if outcome.status == "error":
            self.fail_open += 1

    def as_dict(self) -> dict:
        return {
            "consultations": self.consultations,
            "vetoes": self.vetoes,
            "fail_open": self.fail_open,
            "fail_open_rate": round(self.fail_open_rate, 4),
            "not_vetoable": self.not_vetoable,
            "no_gate": self.no_gate,
            "by_rule": dict(self.by_rule),
        }


def consult_gate(gate: Optional[ExitGate], ctx: ExitContext) -> GateOutcome:
    """Ask a gate whether to hold. Fails open on any gate malfunction.

    Failing open is the only safe direction: a broken gate must never prevent
    an exit. The status is carried out so an experiment can count fail-opens
    and refuse to trust an arm whose gate was mostly broken.
    """
    if gate is None:
        return GateOutcome(veto=False, status="no_gate")
    if ctx.rule not in VETOABLE_RULES:
        return GateOutcome(veto=False, status="not_vetoable")
    try:
        decision = gate.decide(ctx)
    except Exception as exc:  # noqa: BLE001 - a gate must never break the run
        return GateOutcome(
            veto=False, status="error",
            detail=f"{type(exc).__name__}: {exc}")
    if not isinstance(decision, VetoDecision):
        return GateOutcome(
            veto=False, status="error",
            detail=f"gate returned {type(decision).__name__}, expected VetoDecision")
    return GateOutcome(
        veto=bool(decision.veto),
        status="vetoed" if decision.veto else "accepted",
        decision=decision,
    )
