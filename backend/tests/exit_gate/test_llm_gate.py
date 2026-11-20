"""The LLM exit gate: an external decision-maker asked whether to hold.

The prompt is anonymised on purpose. A general-purpose model has memorised the
price paths of famous tickers; naming the instrument lets it answer from what
happened next, which no rule-based backtest can do and which would make every
result meaningless. Identity is available only as a leakage diagnostic.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.exit_gate.cache import DecisionCache  # noqa: E402
from app.services.exit_gate.llm_gate import LLMExitGate, build_prompt  # noqa: E402
from app.services.exit_gate.types import ExitContext  # noqa: E402


def _ctx(**over):
    base = dict(
        ticker="NVDA", as_of_date="2021-03-05", rule="trailing_stop",
        entry_date="2021-01-04", entry_price=100.0, peak_price=130.0,
        current_price=114.0, shares=10, hold_days=60, sector="Tech",
        market_cap=1e10,
        held_tickers=("AAA", "NVDA"),
        n_open_slots=0,
        top_candidates=(("XYZ", 0.91), ("ABC", 0.88)),
    )
    base.update(over)
    return ExitContext(**base)


class _Completer:
    def __init__(self, reply='{"veto": true, "confidence": 0.95, "reason": "hold"}'):
        self.reply = reply
        self.prompts = []
        self.n = 0

    def __call__(self, prompt):
        self.n += 1
        self.prompts.append(prompt)
        return self.reply


@pytest.fixture
def cache(tmp_path):
    c = DecisionCache(str(tmp_path / "c.sqlite"))
    yield c
    c.close()


def test_the_anonymised_prompt_hides_identity_and_dates():
    p = build_prompt(_ctx(), include_identity=False)
    assert "NVDA" not in p
    assert "2021-03-05" not in p
    assert "2021-01-04" not in p
    # Relative numbers only: no absolute price levels.
    assert "100.0" not in p and "114.0" not in p and "130.0" not in p


def test_the_identity_prompt_carries_the_ticker_only_for_the_diagnostic():
    assert "NVDA" in build_prompt(_ctx(), include_identity=True)


def test_the_prompt_asks_for_strict_json_and_states_the_threshold_free_framing():
    p = build_prompt(_ctx())
    assert "json" in p.lower()
    assert "veto" in p and "confidence" in p


def test_high_confidence_veto_is_honoured(cache):
    gate = LLMExitGate(_Completer(), "qwen3:8b", cache, threshold=0.8)
    d = gate.decide(_ctx())
    assert d.veto is True
    assert d.confidence == 0.95


def test_low_confidence_is_not_enough_to_override_an_exit(cache):
    gate = LLMExitGate(
        _Completer('{"veto": true, "confidence": 0.55, "reason": "unsure"}'),
        "qwen3:8b", cache, threshold=0.8)
    d = gate.decide(_ctx())
    assert d.veto is False
    assert "below threshold" in d.reason.lower()


def test_a_clear_exit_decision_is_honoured(cache):
    gate = LLMExitGate(
        _Completer('{"veto": false, "confidence": 0.9, "reason": "sell"}'),
        "qwen3:8b", cache, threshold=0.8)
    assert gate.decide(_ctx()).veto is False


def test_thinking_wrappers_and_code_fences_are_tolerated(cache):
    reply = ('<thinking>hmm</thinking>\n```json\n'
             '{"veto": true, "confidence": 0.91, "reason": "hold"}\n```')
    gate = LLMExitGate(_Completer(reply), "qwen3:8b", cache, threshold=0.8)
    assert gate.decide(_ctx()).veto is True


def test_malformed_output_raises_so_the_adapter_counts_a_fail_open(cache):
    gate = LLMExitGate(_Completer("I think you should hold."), "qwen3:8b", cache)
    with pytest.raises(ValueError):
        gate.decide(_ctx())


def test_a_repeated_context_is_answered_from_cache_without_calling_the_model(cache):
    comp = _Completer()
    gate = LLMExitGate(comp, "qwen3:8b", cache, threshold=0.8)
    first = gate.decide(_ctx())
    second = gate.decide(_ctx())
    assert comp.n == 1
    assert first.veto == second.veto
    assert cache.stats()["hits"] == 1


def test_changing_the_model_identity_invalidates_the_cache(cache):
    comp = _Completer()
    LLMExitGate(comp, "qwen3:8b", cache).decide(_ctx())
    LLMExitGate(comp, "qwen3.8:27b-mlx", cache).decide(_ctx())
    assert comp.n == 2


def test_the_gate_id_names_the_mode_and_the_model(cache):
    gate = LLMExitGate(_Completer(), "qwen3:8b", cache)
    assert gate.gate_id == "llm:hold_confidence:qwen3:8b"
    exit_gate = LLMExitGate(_Completer(), "qwen3:8b", cache,
                            mode="exit_confidence")
    assert exit_gate.gate_id == "llm:exit_confidence:qwen3:8b"


def test_a_marginally_different_context_is_a_different_question(cache):
    comp = _Completer()
    gate = LLMExitGate(comp, "qwen3:8b", cache, threshold=0.8)
    gate.decide(_ctx())
    gate.decide(_ctx(current_price=113.0))
    assert comp.n == 2


# ── the policy the user actually asked for: exit only on high confidence ──

def test_exit_confidence_mode_lets_a_confident_exit_proceed(cache):
    gate = LLMExitGate(_Completer('{"exit": true, "confidence": 0.92}'),
                       "qwen3:8b", cache, threshold=0.8,
                       mode="exit_confidence")
    assert gate.decide(_ctx()).veto is False


def test_exit_confidence_mode_holds_when_the_model_is_not_confident(cache):
    gate = LLMExitGate(_Completer('{"exit": true, "confidence": 0.45}'),
                       "qwen3:8b", cache, threshold=0.8,
                       mode="exit_confidence")
    d = gate.decide(_ctx())
    assert d.veto is True
    assert "not confident" in d.reason.lower()


def test_exit_confidence_mode_holds_when_the_model_says_do_not_exit(cache):
    gate = LLMExitGate(_Completer('{"exit": false, "confidence": 0.95}'),
                       "qwen3:8b", cache, threshold=0.8,
                       mode="exit_confidence")
    assert gate.decide(_ctx()).veto is True


def test_the_exit_confidence_prompt_asks_for_an_exit_decision():
    p = build_prompt(_ctx(), mode="exit_confidence")
    assert "exit" in p.lower()
    assert "veto" not in p.lower().split("reply")[0]


def test_both_polarities_are_available_and_labelled():
    import inspect
    sig = inspect.signature(LLMExitGate.__init__)
    assert sig.parameters["mode"].default in ("exit_confidence", "hold_confidence")
