"""Tests for scripts/run_all_strategies.sh, the multi-account daily runner.

The batch used to run under `set -e`, so the first failing slot aborted the rest
of the run and a two-week `unauthorized.` outage stayed invisible. These tests
pin the fail-soft behaviour, the alerting, the disabled slot 3, and the live
account numbers in the header.

The runner is exercised in a throwaway sandbox tree (inside the repo, removed
afterwards) with a stubbed `backend/venv/bin/python`, so no Alpaca call is ever
made and no order is ever placed.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "run_all_strategies.sh"
SANDBOX_ROOT = Path(__file__).resolve().parent / ".runner_sandbox"

LIVE_ACCOUNT_NUMBERS = ("PA3LE9Y79BU0", "PA33GEZZ5K7Y", "PA3CE4ALJ8OJ")
STALE_ACCOUNT_NUMBERS = ("PA3QALHOBO67", "PA3EW6COMH40", "PA3EWVY05TVQ", "PA3CNDIA27J3")

# Stub `python` inside the sandbox: records each invocation and can be told to
# fail for one prefix. argv is: -m app.services.alpaca_runner_by_name <module> <prefix>
STUB_PYTHON = """#!/bin/bash
echo "$*" >> "$STUB_LOG"
module="$3"
prefix="$4"
if [ -n "$STUB_FAIL_PREFIX" ] && [ "$prefix" = "$STUB_FAIL_PREFIX" ]; then
    echo "stub: simulated failure for ${module} on prefix ${prefix}"
    exit 1
fi
echo "stub: ok ${module} on prefix ${prefix}"
exit 0
"""


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _effective_lines(text: str) -> list:
    """Non-comment, non-blank script lines."""
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


@pytest.fixture
def sandbox():
    """Throwaway project tree with a stubbed python; removed after the test."""
    root = SANDBOX_ROOT / uuid.uuid4().hex[:8]
    (root / "scripts").mkdir(parents=True)
    (root / "backend" / "venv" / "bin").mkdir(parents=True)
    (root / "backend" / "logs").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts" / "run_all_strategies.sh")
    stub = root / "backend" / "venv" / "bin" / "python"
    stub.write_text(STUB_PYTHON, encoding="utf-8")
    stub.chmod(0o755)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        try:
            SANDBOX_ROOT.rmdir()
        except OSError:
            pass


def _run(sandbox: Path, fail_prefix: str = "") -> subprocess.CompletedProcess:
    env_lines = [
        "ALPACA_1_NAME=Acct#1",
        "ALPACA_2_NAME=Acct#2",
        "ALPACA_3_NAME=Acct#3",
        f"STUB_LOG={sandbox / 'stub_calls.log'}",
    ]
    if fail_prefix:
        env_lines.append(f"STUB_FAIL_PREFIX={fail_prefix}")
    (sandbox / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    return subprocess.run(
        ["bash", str(sandbox / "scripts" / "run_all_strategies.sh")],
        capture_output=True,
        text=True,
        timeout=120,
    )


# ── Static guarantees ────────────────────────────────────────────────

def test_script_no_longer_aborts_the_batch_on_the_first_failure():
    effective = _effective_lines(_script_text())
    assert "set -e" not in effective
    assert not any(line.startswith("set -e") for line in effective)


def test_slot_three_is_commented_out_with_a_dated_reason():
    text = _script_text()
    assert 'run_one sector_top5_pegy "3"' not in "\n".join(_effective_lines(text))

    commented = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("#") and "run_one sector_top5_pegy" in line
    ]
    assert commented, "the slot-3 line must be kept, commented out"
    assert re.search(r"\d{4}-\d{2}-\d{2}", text), "the disabled note must be dated"
    assert "deploy" in text.lower(), "the disabled note must say how to restore it"


def test_failures_append_to_alerts_log_and_post_a_notification():
    text = _script_text()
    assert "ALERTS.log" in text
    assert "/usr/bin/osascript" in text
    assert "display notification" in text
    assert "|| true" in text, "the macOS notification must be non-fatal"
    assert "exit 1" in "\n".join(_effective_lines(text)), "a failed batch must exit non-zero"


def test_header_documents_the_live_account_numbers():
    text = _script_text()
    for number in LIVE_ACCOUNT_NUMBERS:
        assert number in text
    for stale in STALE_ACCOUNT_NUMBERS:
        assert stale not in text


# ── Sandboxed behaviour ──────────────────────────────────────────────

def test_batch_continues_past_a_failing_slot_and_alerts(sandbox):
    proc = _run(sandbox, fail_prefix="1")

    assert proc.returncode != 0, "a failed slot must make the batch exit non-zero"

    calls = (sandbox / "stub_calls.log").read_text(encoding="utf-8")
    assert "daily_golden_cross 1" in calls, "slot 1 should have run"
    assert "daily_golden_cross 2" in calls, (
        "slot 2 must still run after slot 1 failed (no fail-fast)"
    )

    alerts = (sandbox / "backend" / "logs" / "ALERTS.log").read_text(encoding="utf-8")
    assert "Acct#1" in alerts
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", alerts), "alert must be timestamped"


def test_slot_logs_use_the_env_account_names(sandbox):
    _run(sandbox, fail_prefix="")

    logs = sorted((sandbox / "backend" / "logs").glob("alpaca_daily_golden_cross_*.log"))
    assert logs, "the runner must write one log per slot"
    text = "\n".join(p.read_text(encoding="utf-8") for p in logs)
    assert "Acct#1" in text
    assert "Acct#2" in text
    assert "Acct#3" not in text, "the disabled slot 3 must not run"


def test_all_green_batch_exits_zero_and_writes_no_alert(sandbox):
    proc = _run(sandbox, fail_prefix="")

    assert proc.returncode == 0
    assert "All strategies complete" in proc.stdout

    alerts = sandbox / "backend" / "logs" / "ALERTS.log"
    assert not alerts.exists() or alerts.read_text(encoding="utf-8").strip() == ""


def test_diagnosis_run_failure_does_not_stop_the_batch_when_slot_two_fails(sandbox):
    """The historical outage shape: a later slot fails while earlier ones pass."""
    proc = _run(sandbox, fail_prefix="2")

    assert proc.returncode != 0
    calls = (sandbox / "stub_calls.log").read_text(encoding="utf-8")
    assert "daily_golden_cross 1" in calls
    assert "daily_golden_cross 2" in calls
    alerts = (sandbox / "backend" / "logs" / "ALERTS.log").read_text(encoding="utf-8")
    assert "Acct#2" in alerts
