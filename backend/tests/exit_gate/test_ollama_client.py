"""Wiring the gate to a local model, without letting it wander off-config.

Ollama's OpenAI-compatible endpoint silently ignores `think: false`, and the
qwen3 family then spends the whole token budget reasoning and returns empty
content. The native `/api/chat` endpoint honours the flag, so that is what this
module speaks. Measured on qwen3:8b: ~19 s/empty via /v1, ~6 s/valid JSON via
/api/chat with think=False.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from app.services.exit_gate.ollama import make_completer  # noqa: E402


def _transport(reply="{\"veto\": true, \"confidence\": 0.9, \"reason\": \"hold\"}"):
    calls = []

    def transport(url, body, timeout):
        calls.append((url, body, timeout))
        return {"message": {"content": reply, "thinking": None}}

    transport.calls = calls
    return transport


def test_the_request_uses_the_native_chat_endpoint_and_the_named_model():
    t = _transport()
    out = make_completer("qwen3:8b", transport=t)("prompt text")
    url, body, _ = t.calls[0]
    assert url.endswith("/api/chat")
    assert body["model"] == "qwen3:8b"
    assert body["messages"] == [{"role": "user", "content": "prompt text"}]
    assert body["stream"] is False
    assert "veto" in out


def test_temperature_is_zero_and_the_token_budget_is_bounded():
    t = _transport()
    make_completer("qwen3:8b", transport=t, max_tokens=256)("x")
    opts = t.calls[0][1]["options"]
    assert opts["temperature"] == 0
    assert opts["num_predict"] == 256


def test_thinking_can_be_disabled_and_is_omitted_when_unspecified():
    t = _transport()
    make_completer("qwen3:8b", transport=t, think=False)("x")
    assert t.calls[0][1]["think"] is False
    make_completer("qwen3:8b", transport=t)("x")
    assert "think" not in t.calls[1][1]


def test_a_null_content_becomes_an_empty_string():
    assert make_completer("m", transport=_transport(None))("x") == ""


def test_the_default_base_url_is_the_local_daemon():
    t = _transport()
    make_completer("qwen3:8b", transport=t)("x")
    assert "localhost:11434" in t.calls[0][0] or "127.0.0.1:11434" in t.calls[0][0]
