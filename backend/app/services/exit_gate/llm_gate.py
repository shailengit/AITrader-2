"""LLM exit gate: ask a local decision model whether to override an exit.

Design constraints that matter more than the prompt:

* **Anonymised by default.** No ticker, no calendar date, no absolute price.
  A general model has seen famous tickers' price paths and will answer from
  what happened next; that is a lookahead channel unique to LLMs. The named
  variant exists only as a leakage diagnostic.
* **Content-addressed cache.** Same question, same model, same answer -- the
  backtest is replayable and the sweep is finite. A changed model or prompt
  version is a different question.
* **Strict parsing.** Malformed output raises; `consult_gate` then records a
  fail-open and the experiment can refuse to trust an arm whose model was
  mostly broken. Silently treating garbage as "hold" would hide that.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from app.services.exit_gate.cache import DecisionCache, canonicalize
from app.services.exit_gate.types import ExitContext, VetoDecision

Completer = Callable[[str], str]

_SYSTEM_HOLD = (
    "You are a risk manager for a momentum trading system. A price exit rule "
    "has fired on an open position. Decide whether to HOLD the position "
    "instead (veto the exit) or let the exit proceed.\n"
    "Only veto when you are confident that holding is better than selling and "
    "redeploying the capital.\n"
    "Answer with STRICT JSON only, no prose:\n"
    '{"veto": true|false, "confidence": 0.0-1.0, "reason": "<=12 words"}'
)

_SYSTEM_EXIT = (
    "You are a risk manager for a momentum trading system. A price exit rule "
    "has fired on an open position. Decide whether this exit should PROCEED, "
    "or whether the position should be held instead.\n"
    "Recommend proceeding only when you are confident the exit is correct; if "
    "you are unsure, recommend holding.\n"
    "Answer with STRICT JSON only, no prose:\n"
    '{"exit": true|false, "confidence": 0.0-1.0, "reason": "<=12 words"}'
)

MODES = ("exit_confidence", "hold_confidence")


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def build_prompt(ctx: ExitContext, include_identity: bool = False,
                 mode: str = "hold_confidence") -> str:
    """Render the decision as relative numbers only.

    Percentages and ratios, never price levels: an absolute price plus a date
    is close to a fingerprint of the historical moment.

    `mode` selects the question. `exit_confidence` is the policy the user asked
    for (proceed only when confident); `hold_confidence` asks the opposite
    (override only when confident).
    """
    if mode not in MODES:
        raise ValueError(f"unknown gate mode {mode!r}; expected one of {MODES}")
    lines = [
        _SYSTEM_EXIT if mode == "exit_confidence" else _SYSTEM_HOLD,
        "",
        "Position:",
        f"- rule that fired: {ctx.rule}",
        f"- holding period: {ctx.hold_days} calendar days",
        f"- unrealised return since entry: {_pct(ctx.ret)}",
        f"- gain at the peak: {_pct(ctx.peak_gain)}",
        f"- drawdown from that peak: {_pct(-ctx.drawdown_from_peak)}",
        f"- sector: {ctx.sector}",
        f"- free slots before this exit: {ctx.n_open_slots}",
        "",
        "Replacement opportunity (what the freed slot could buy today):",
        f"- feasible candidates: {len(ctx.top_candidates)}",
    ]
    if ctx.top_candidates:
        best = ctx.top_candidates[0][1]
        worst = ctx.top_candidates[-1][1]
        lines.append(f"- best candidate momentum score: {best:.3f}")
        lines.append(f"- momentum spread across candidates: {best - worst:.3f}")
    else:
        lines.append("- nothing qualifies; the freed cash would sit idle")
    if ctx.features:
        lines.append("")
        lines.append("Market context:")
        for key in sorted(ctx.features):
            val = ctx.features[key]
            if isinstance(val, (int, float)):
                lines.append(f"- {key}: {val:.4f}")
    if include_identity:
        lines.append("")
        lines.append(f"Instrument: {ctx.ticker} (LEAKAGE DIAGNOSTIC ONLY)")
        lines.append(f"Date: {ctx.as_of_date}")
    lines.append("")
    lines.append("Reply with the JSON object only.")
    return "\n".join(lines)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a reply, tolerating fences and thinking."""
    if text is None:
        raise ValueError("empty model response")
    candidates = []
    m = _FENCE.search(text)
    if m:
        candidates.append(m.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    candidates.append(text)
    for cand in candidates:
        try:
            obj = json.loads(cand.strip())
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError(f"no JSON object in model response: {text[:160]!r}")


class LLMExitGate:
    """Consult a local model, with either polarity.

    `exit_confidence` (the requested policy): the exit proceeds only when the
    model both says "exit" and is at least `threshold` confident; otherwise the
    position is held. `hold_confidence` is the opposite, more conservative
    framing: the exit is cancelled only when the model is confident that
    holding is better.
    """

    def __init__(self, complete: Completer, model: str, cache: DecisionCache,
                 threshold: float = 0.80, prompt_version: str = "v1",
                 include_identity: bool = False,
                 mode: str = "hold_confidence"):
        if mode not in MODES:
            raise ValueError(f"unknown gate mode {mode!r}; expected one of {MODES}")
        self.complete = complete
        self.model = model
        self.cache = cache
        self.threshold = threshold
        self.prompt_version = prompt_version
        self.include_identity = include_identity
        self.mode = mode
        self.gate_id = f"llm:{mode}:{model}"

    def decide(self, ctx: ExitContext) -> VetoDecision:
        prompt = build_prompt(ctx, include_identity=self.include_identity,
                              mode=self.mode)
        canonical = canonicalize({"prompt": prompt, "mode": self.mode,
                                  "identity": self.include_identity})
        key = self.cache.key(self.model, self.prompt_version, canonical)

        cached = self.cache.get(key)
        if cached is not None:
            return self._to_decision(cached)

        raw = self.complete(prompt)
        payload = _extract_json(raw)
        conf = float(payload.get("confidence", 0.0) or 0.0)
        reason = json.dumps(payload.get("reason", ""), default=str).strip('"')[:120]
        if self.mode == "exit_confidence":
            if "exit" not in payload:
                raise ValueError(f"model reply has no 'exit' field: {raw[:160]!r}")
            decision = {"exit": bool(payload.get("exit")), "confidence": conf,
                        "reason": reason}
        else:
            if "veto" not in payload:
                raise ValueError(f"model reply has no 'veto' field: {raw[:160]!r}")
            decision = {"veto": bool(payload.get("veto")), "confidence": conf,
                        "reason": reason}
        self.cache.put(key, {"model": self.model,
                             "prompt_version": self.prompt_version,
                             "prompt": prompt},
                       {"raw": raw}, decision, 0.0)
        return self._to_decision(decision)

    def _to_decision(self, decision: dict) -> VetoDecision:
        conf = float(decision.get("confidence", 0.0) or 0.0)
        reason = str(decision.get("reason", ""))
        if self.mode == "exit_confidence":
            wants_exit = bool(decision.get("exit"))
            if wants_exit and conf >= self.threshold:
                return VetoDecision(veto=False, confidence=conf,
                                    reason=reason or "exit approved",
                                    gate_id=self.gate_id)
            if wants_exit:
                return VetoDecision(
                    veto=True, confidence=conf, gate_id=self.gate_id,
                    reason=f"model not confident enough to exit "
                           f"({conf:.2f} < {self.threshold:.2f})")
            return VetoDecision(veto=True, confidence=conf, gate_id=self.gate_id,
                                reason=reason or "model recommended holding")
        veto = bool(decision.get("veto"))
        if veto and conf < self.threshold:
            return VetoDecision(
                veto=False, confidence=conf, gate_id=self.gate_id,
                reason=f"confidence {conf:.2f} below threshold {self.threshold:.2f}")
        return VetoDecision(veto=veto, confidence=conf, reason=reason,
                            gate_id=self.gate_id)
