"""Admin helpers for the Alpaca paper accounts: liquidate and update keys.

These make it painless to reset/replace a paper account from the app:
  - liquidate_account(): cancel all open orders and close all positions.
  - update_account_keys(): swap an account's API key/secret in .env and its
    account number in strategy_accounts.py. The account number is auto-fetched
    from Alpaca using the new keys, so the user only pastes the two keys.

NOTE: Alpaca's API cannot reset a paper account balance or create/delete
accounts (dashboard-only). This only automates the surrounding steps.
"""
from __future__ import annotations
import logging
import os
import re
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # AITrader-2
ENV_PATH = REPO_ROOT / ".env"
STRATEGY_ACCOUNTS_PATH = REPO_ROOT / "backend" / "app" / "services" / "strategy_accounts.py"


def _env_key(prefix: str, kind: str) -> str:
    suffix = f"_{prefix}" if prefix else ""
    return f"ALPACA{suffix}_{kind}"


def _update_env(prefix: str, api_key: str, secret_key: str) -> bool:
    """Replace the ALPACA_{prefix}_API_KEY / _SECRET_KEY lines in .env."""
    if not ENV_PATH.exists():
        logger.error("No .env at %s", ENV_PATH)
        return False
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    api_k = _env_key(prefix, "API_KEY")
    sec_k = _env_key(prefix, "SECRET_KEY")
    out = []
    api_done = sec_done = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(api_k + "="):
            out.append(f"{api_k}={api_key}")
            api_done = True
            continue
        if stripped.startswith(sec_k + "="):
            out.append(f"{sec_k}={secret_key}")
            sec_done = True
            continue
        out.append(line)
    if not api_done:
        out.append(f"{api_k}={api_key}")
    if not sec_done:
        out.append(f"{sec_k}={secret_key}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    # Also update the current process env so a freshly-built AlpacaClient(prefix)
    # uses the new keys immediately (no restart needed).
    os.environ[api_k] = api_key
    os.environ[sec_k] = secret_key
    return True


def _update_strategy_accounts_account_number(prefix: str, account_number: str) -> bool:
    """Replace the account_number (last string arg) of the RunningStrategy for `prefix`."""
    text = STRATEGY_ACCOUNTS_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r'RunningStrategy\(\s*"[^"]*",\s*"[^"]*",\s*"[^"]*",\s*"' + re.escape(prefix) + r'",\s*"[^"]*",\s*"[^"]*"\)',
        re.DOTALL,
    )
    m = pattern.search(text)
    if m is None:
        logger.error("No RunningStrategy entry for prefix %r in %s", prefix, STRATEGY_ACCOUNTS_PATH)
        return False
    block = m.group(0)
    # Rebuild the block with the new account number (last quoted string).
    new_block = re.sub(r'("[^"]*"\))$', f'"{account_number}")', block)
    text = text.replace(block, new_block, 1)
    STRATEGY_ACCOUNTS_PATH.write_text(text, encoding="utf-8")
    logger.info("Updated strategy_accounts.py account_number for prefix %r -> %s", prefix, account_number)
    return True


def liquidate_account(prefix: str) -> Dict:
    """Cancel all open orders and close all positions on an account."""
    from app.services.alpaca_client import AlpacaClient
    client = AlpacaClient(prefix=prefix)
    cancelled = client.cancel_all_orders()
    try:
        closed = client.api.close_all_positions()
        n_closed = len(closed) if closed else 0
    except Exception as e:
        logger.warning("close_all_positions failed for prefix %s: %s", prefix, e)
        n_closed = 0
    return {"prefix": prefix, "orders_cancelled": cancelled, "positions_closed": n_closed}


def update_account_keys(prefix: str, api_key: str, secret_key: str,
                       account_number: Optional[str] = None) -> Dict:
    """Swap an account's keys in .env and its account number in strategy_accounts.py.

    The account number is auto-fetched from Alpaca using the new keys if not
    provided, so the user only needs to paste the two keys.
    """
    if not api_key or not secret_key:
        raise ValueError("api_key and secret_key are required")
    ok_env = _update_env(prefix, api_key.strip(), secret_key.strip())
    if not ok_env:
        raise RuntimeError("Failed to update .env")

    # Fetch the account number with the new keys (env already updated in-process).
    from app.services.alpaca_client import AlpacaClient
    try:
        client = AlpacaClient(prefix=prefix)
        fetched = client.get_account().get("account_number")
        if not account_number:
            account_number = fetched
    except Exception as e:
        logger.warning("Could not fetch account number with new keys for prefix %s: %s", prefix, e)
        if not account_number:
            raise RuntimeError(f"Could not fetch account number: {e}")

    ok_acct = _update_strategy_accounts_account_number(prefix, account_number)
    if not ok_acct:
        raise RuntimeError("Failed to update strategy_accounts.py account number")

    return {
        "prefix": prefix,
        "account_number": account_number,
        "env_updated": ok_env,
        "strategy_accounts_updated": ok_acct,
    }
