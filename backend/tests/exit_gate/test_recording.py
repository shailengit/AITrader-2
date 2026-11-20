"""Recording gate: observes every exit decision without changing the run.

Used to collect the real distribution of decision contexts from baseline
backtests. It must never veto, so a run with the recorder is identical to the
baseline run.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.exit_gate.recording import RecordingGate  # noqa: E402
from app.services.exit_gate.types import ExitContext  # noqa: E402


def _ctx(rule="trailing_stop"):
    return ExitContext(
        ticker="AAA", as_of_date="2021-03-05", rule=rule,
        entry_date="2021-01-04", entry_price=100.0, peak_price=130.0,
        current_price=114.0, shares=10, hold_days=60, sector="Tech",
        market_cap=1e10)


def test_the_recorder_never_vetoes():
    gate = RecordingGate()
    for rule in ("trailing_stop", "take_profit", "time_stop"):
        assert gate.decide(_ctx(rule)).veto is False


def test_the_recorder_keeps_every_context_it_saw():
    gate = RecordingGate()
    gate.decide(_ctx("trailing_stop"))
    gate.decide(_ctx("take_profit"))
    assert [c.rule for c in gate.contexts] == ["trailing_stop", "take_profit"]


def test_the_recorder_can_be_frozen_and_deduplicated():
    gate = RecordingGate()
    gate.decide(_ctx("trailing_stop"))
    gate.decide(_ctx("trailing_stop"))
    assert len(gate.contexts) == 2
    assert len(gate.unique_contexts()) == 1


def test_unique_key_is_the_decision_identity_not_the_price_path():
    gate = RecordingGate()
    gate.decide(_ctx("trailing_stop"))
    later = _ctx("trailing_stop")
    gate.decide(ExitContext(**{**later.__dict__, "current_price": 113.0}))
    # Same ticker/entry/rule/date is the same decision question.
    assert len(gate.unique_contexts()) == 1
