"""Ollama-backed completer for the LLM exit gate -- native API, not /v1.

Why the native endpoint: Ollama's OpenAI-compatible `/v1/chat/completions`
silently ignores `think: false`. The qwen3 family then spends its whole token
budget reasoning and returns empty `content`. Measured on qwen3:8b with a real
gate prompt:

    /v1/chat/completions, max_tokens=512   ->  finish=length, content=''   (12-19 s)
    /api/chat, think=False, num_predict=256 ->  valid JSON               (5-6 s)

So the gate speaks `/api/chat`. `think` is passed explicitly by the caller; it
is omitted when unspecified so non-reasoning models are unaffected.

A slow or empty reply is not caught here. It surfaces as an exception from the
gate's JSON parser, which `consult_gate` records as a fail-open -- a broken
model must never look like a policy that happens to hold.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Callable, Optional

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_TOKENS = 256

Transport = Callable[[str, dict, float], dict]


def _native_url(base_url: Optional[str]) -> str:
    """`http://host:11434/v1` and `http://host:11434` both -> `/api/chat`."""
    base = (base_url or os.environ.get("LOCAL_LLM_API_BASE")
            or DEFAULT_BASE_URL).rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base + "/api/chat"


def _default_transport(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def make_completer(
    model: str,
    *,
    think: Optional[bool] = None,
    base_url: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    transport: Optional[Transport] = None,
) -> Callable[[str], str]:
    """Return `complete(prompt) -> str` bound to `model` on the local daemon."""
    url = _native_url(base_url)
    send = transport or _default_transport

    def complete(prompt: str) -> str:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0, "num_predict": max_tokens},
        }
        if think is not None:
            body["think"] = think
        data = send(url, body, timeout)
        content = (data.get("message") or {}).get("content")
        return "" if content is None else str(content)

    return complete
