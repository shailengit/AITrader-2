"""The adapter's single call into a gate, plus the counters an experiment needs.

Fail-open is only safe if it is counted. An arm whose gate errored on 30% of
consultations is mostly the baseline wearing a gate's name, and these counters
are what let the harness refuse to trust it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.exit_gate.context import apply_exit_gate  # noqa: E402
from app.services.exit_gate.types import GateStats, VetoDecision  # noqa: E402


class _Gate:
    gate_id = "g"

    def __init__(self, veto=False, exc=None):
        self.calls = 0
        self._veto = veto
        self._exc = exc

    def decide(self, ctx):
        self.calls += 1
        if self._exc:
            raise self._exc
        return VetoDecision(veto=self._veto, confidence=0.9)


def _call(gate, stats, rule="trailing_stop"):
    return apply_exit_gate(
        gate,
        stats=stats,
        ticker="AAA",
        current_date="2021-03-05",
        holding={"entry_date": "2021-01-04", "entry_price": 100.0,
                 "peak_price": 120.0, "shares": 10, "sector": "Tech",
                 "market_cap": 2e10},
        current_price=114.0,
        hold_days=60,
        rule=rule,
        holdings={"AAA": {}},
        today_signals=[],
        max_holdings=5,
        max_sector_count=2,
    )


def test_a_veto_is_counted_by_status_and_by_rule():
    stats = GateStats()
    out = _call(_Gate(veto=True), stats)
    assert out.veto is True
    assert stats.consultations == 1
    assert stats.vetoes == 1
    assert stats.by_rule == {"trailing_stop": 1}


def test_a_gate_error_is_counted_as_fail_open_and_as_a_consultation():
    stats = GateStats()
    out = _call(_Gate(exc=TimeoutError("slow")), stats)
    assert out.veto is False
    assert stats.consultations == 1
    assert stats.vetoes == 0
    assert stats.fail_open == 1


def test_a_non_vetoable_rule_is_not_a_consultation():
    gate = _Gate(veto=True)
    stats = GateStats()
    out = _call(gate, stats, rule="hard_stop_loss")
    assert out.veto is False
    assert gate.calls == 0
    assert stats.consultations == 0
    assert stats.not_vetoable == 1


def test_no_gate_is_not_a_consultation():
    stats = GateStats()
    out = _call(None, stats)
    assert out.status == "no_gate"
    assert stats.consultations == 0


def test_fail_open_rate_is_undefined_without_consultations():
    assert GateStats().fail_open_rate == 0.0
    stats = GateStats(consultations=4, fail_open=1)
    assert stats.fail_open_rate == 0.25


def test_stats_serialise_for_the_report():
    stats = GateStats()
    _call(_Gate(veto=True), stats)
    _call(_Gate(exc=RuntimeError("x")), stats)
    d = stats.as_dict()
    assert d["consultations"] == 2 and d["vetoes"] == 1 and d["fail_open"] == 1
    assert d["by_rule"] == {"trailing_stop": 2}
