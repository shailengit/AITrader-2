"""Tests for the canonical running-strategy registry.

The Alpaca paper account numbers in RUNNING_STRATEGIES must match the live
accounts (verified with a read-only GET /v2/account per prefix) and the numbers
annotated in the root .env. Stale numbers here silently pointed the app, the
Coach badge, and the multi-account runner at the wrong accounts.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import app.services.strategy_accounts as strategy_accounts
from app.services.strategy_accounts import RUNNING_STRATEGIES, running_strategy_by_stem

# Live account numbers per credential prefix (paper accounts, read from Alpaca).
LIVE_ACCOUNT_NUMBERS = {
    "1": "PA3LE9Y79BU0",
    "2": "PA33GEZZ5K7Y",
    "3": "PA3CE4ALJ8OJ",
}

# Slot 3 was re-provisioned on 2026-09-29, so PA3CNDIA27J3 is stale too.
STALE_ACCOUNT_NUMBERS = ("PA3QALHOBO67", "PA3EW6COMH40", "PA3EWVY05TVQ", "PA3CNDIA27J3")

REPO_ROOT = Path(strategy_accounts.__file__).resolve().parents[3]
ENV_PATH = REPO_ROOT / ".env"


def test_running_strategies_use_the_live_account_numbers():
    assert {s.prefix: s.account_number for s in RUNNING_STRATEGIES} == LIVE_ACCOUNT_NUMBERS


def test_every_prefix_has_one_running_strategy():
    prefixes = [s.prefix for s in RUNNING_STRATEGIES]
    assert sorted(prefixes) == sorted(LIVE_ACCOUNT_NUMBERS)


def test_no_stale_account_numbers_remain_in_the_module():
    src = Path(strategy_accounts.__file__).read_text(encoding="utf-8")
    for stale in STALE_ACCOUNT_NUMBERS:
        assert stale not in src


def test_account_numbers_look_like_alpaca_account_numbers():
    for number in LIVE_ACCOUNT_NUMBERS.values():
        assert re.fullmatch(r"PA3[A-Z0-9]{9}", number), number


def test_env_defines_a_name_for_every_prefix():
    """.env must define ALPACA_<n>_NAME: that is the label the router shows.

    The `# Acct#<n>  (<number>)` comments in .env are documentation only and are
    NOT asserted here. They are user-owned, and after the 2026-09-29 key rotation
    the slot-3 comment still names the replaced account PA3CNDIA27J3 (reported
    separately; the live number is the one in LIVE_ACCOUNT_NUMBERS).
    """
    if not ENV_PATH.exists():
        pytest.skip(".env not present")
    text = ENV_PATH.read_text(encoding="utf-8")
    for prefix in LIVE_ACCOUNT_NUMBERS:
        assert re.search(rf"^ALPACA_{prefix}_NAME=\S", text, re.MULTILINE), (
            f"ALPACA_{prefix}_NAME is missing from .env"
        )


def test_running_strategy_lookup_still_works():
    assert running_strategy_by_stem("daily_golden_cross") is not None
    assert running_strategy_by_stem("nope") is None
