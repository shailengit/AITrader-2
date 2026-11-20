"""Transparent rule gates: the cheapest possible exit-veto policies.

These exist so the question "is there ANY selective exit-veto signal?" can be
answered without training a model or calling an LLM. If no rule here beats the
baseline, a black-box gate is unlikely to.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.exit_gate.rules import RULE_GATES, RuleGate, make_rule_gates  # noqa: E402
from app.services.exit_gate.types import ExitContext  # noqa: E402


def _ctx(**over):
    base = dict(
        ticker="AAA", as_of_date="2021-03-05", rule="trailing_stop",
        entry_date="2021-01-04", entry_price=100.0, peak_price=130.0,
        current_price=114.0, shares=10, hold_days=60, sector="Tech",
        market_cap=1e10,
    )
    base.update(over)
    return ExitContext(**base)


def test_a_rule_gate_vetoes_only_the_rules_it_names():
    gate = RuleGate("g", {"trailing_stop": lambda c: True})
    assert gate.decide(_ctx(rule="trailing_stop")).veto is True
    assert gate.decide(_ctx(rule="take_profit")).veto is False
    assert gate.decide(_ctx(rule="time_stop")).veto is False


def test_a_predicate_controls_the_veto():
    gate = RuleGate("g", {"trailing_stop": lambda c: c.ret > 0})
    assert gate.decide(_ctx(current_price=110.0)).veto is True
    assert gate.decide(_ctx(current_price=90.0)).veto is False


def test_the_gate_id_is_reported_back():
    gate = RuleGate("rule:test", {"trailing_stop": lambda c: True})
    assert gate.decide(_ctx()).gate_id == "rule:test"


def test_registry_exposes_a_make_function_and_a_static_list():
    made = make_rule_gates()
    assert made.keys() == RULE_GATES.keys()
    for name, gate in made.items():
        assert isinstance(gate, RuleGate)
        assert gate.gate_id.startswith("rule:")
        assert set(gate.veto_if) <= {"trailing_stop", "take_profit", "time_stop"}


#: A position deep in profit, young, and only slightly off its peak: every
#: selective predicate should fire on this one.
_WINNER = _ctx(entry_price=100.0, peak_price=160.0, current_price=150.0, hold_days=5)
#: A losing, old position well off its peak: no selective predicate should fire.
_LOSER = _ctx(entry_price=100.0, peak_price=110.0, current_price=80.0, hold_days=100)


def _with(ctx, rule):
    from dataclasses import replace
    return replace(ctx, rule=rule)


def test_every_selective_gate_fires_on_a_winner_and_stays_quiet_on_a_loser():
    for name, gate in make_rule_gates().items():
        if name.startswith("veto_all_"):
            continue
        rule = next(iter(gate.veto_if))
        assert gate.decide(_with(_WINNER, rule)).veto, f"{name} never fires on a winner"
        assert not gate.decide(_with(_LOSER, rule)).veto, f"{name} fires on a loser"


def test_controls_fire_regardless_of_the_position():
    for name in ("veto_all_trail", "veto_all_tp", "veto_all_time"):
        gate = make_rule_gates()[name]
        rule = next(iter(gate.veto_if))
        assert gate.decide(_with(_LOSER, rule)).veto, name
