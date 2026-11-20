"""Exit-gate contracts: what a gate is allowed to see and to do.

These tests pin the safety rules before any gate exists:
  - the position's derived numbers cannot disagree with its prices
  - only price exits are vetoable (hard stop, strategy exits and rotation are not)
  - a broken gate must never block an exit
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.exit_gate.types import (  # noqa: E402
    VETOABLE_RULES,
    ExitContext,
    GateOutcome,
    VetoDecision,
    consult_gate,
)


def _ctx(**over):
    base = dict(
        ticker="AAA",
        as_of_date="2021-03-05",
        rule="trailing_stop",
        entry_date="2021-01-04",
        entry_price=100.0,
        peak_price=130.0,
        current_price=114.0,
        shares=100,
        hold_days=60,
        sector="Tech",
        market_cap=1e10,
    )
    base.update(over)
    return ExitContext(**base)


class _SpyGate:
    """Records calls so 'the gate was never asked' is assertable."""

    gate_id = "spy"

    def __init__(self, decision=None, exc=None):
        self.calls = []
        self._decision = decision
        self._exc = exc

    def decide(self, ctx):
        self.calls.append(ctx)
        if self._exc is not None:
            raise self._exc
        return self._decision


def test_context_derives_ret_peak_gain_and_drawdown_from_its_own_prices():
    c = _ctx()
    assert c.ret == pytest.approx(0.14)
    assert c.peak_gain == pytest.approx(0.30)
    assert c.drawdown_from_peak == pytest.approx(1.0 - 114.0 / 130.0)


def test_vetoable_rules_are_price_exits_only():
    assert VETOABLE_RULES == {"trailing_stop", "take_profit", "time_stop"}
    for forbidden in ("hard_stop_loss", "strategy_exit", "rotated_out"):
        assert forbidden not in VETOABLE_RULES


def test_veto_decision_defaults_to_not_vetoing():
    d = VetoDecision()
    assert d.veto is False
    assert d.confidence == 0.0


def test_no_gate_means_no_veto_and_no_consult():
    out = consult_gate(None, _ctx())
    assert isinstance(out, GateOutcome)
    assert out.veto is False
    assert out.status == "no_gate"
    assert out.decision is None


def test_gate_is_never_consulted_for_a_non_vetoable_rule():
    gate = _SpyGate(decision=VetoDecision(veto=True, confidence=1.0))
    out = consult_gate(gate, _ctx(rule="hard_stop_loss"))
    assert out.veto is False
    assert out.status == "not_vetoable"
    assert gate.calls == []


def test_a_vetoing_gate_reports_vetoed():
    gate = _SpyGate(decision=VetoDecision(veto=True, confidence=0.9, reason="run it"))
    out = consult_gate(gate, _ctx())
    assert out.veto is True
    assert out.status == "vetoed"
    assert out.decision.reason == "run it"
    assert len(gate.calls) == 1


def test_a_non_vetoing_gate_reports_accepted():
    gate = _SpyGate(decision=VetoDecision(veto=False))
    out = consult_gate(gate, _ctx())
    assert out.veto is False
    assert out.status == "accepted"


def test_a_broken_gate_fails_open_and_never_blocks_an_exit():
    gate = _SpyGate(exc=RuntimeError("model timeout"))
    out = consult_gate(gate, _ctx())
    assert out.veto is False
    assert out.status == "error"
    assert "model timeout" in out.detail


def test_a_gate_returning_a_bare_bool_is_treated_as_broken():
    class BoolGate:
        gate_id = "bad"

        def decide(self, ctx):
            return True

    out = consult_gate(BoolGate(), _ctx())
    assert out.veto is False
    assert out.status == "error"
