"""Deploy a strategy to a specific Alpaca account by editing the live config.

The 3-account setup is driven by two files:
  - backend/app/services/strategy_accounts.py  (RUNNING_STRATEGIES — source of truth)
  - scripts/run_all_strategies.sh             (the daily scheduler's run_one lines)

This service swaps the strategy on a given account (by credential prefix) in
both files, so a UI deploy actually changes which strategy trades on that
account. It does NOT touch the legacy single-active deployments registry (that
only drives the old default-account runner).

The account_number and prefix are preserved; only the strategy module/class/
file_stem/label change. This is Workflow A from the alpaca-strategy-swap skill
(swap strategy, keep balance). Reset-to-$100k is a manual dashboard step.
"""
from __future__ import annotations

import importlib.util
import logging
import re
import sys
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # AITrader-2
STRATEGY_ACCOUNTS_PATH = REPO_ROOT / "backend" / "app" / "services" / "strategy_accounts.py"
RUN_ALL_PATH = REPO_ROOT / "scripts" / "run_all_strategies.sh"
STRATEGIES_DIR = REPO_ROOT / "backend" / "app" / "services" / "strategies"


def _load_strategy_class(strategy_class_path: str) -> Optional[type]:
    """Import the Strategy subclass from a repo-relative path; None on failure."""
    from app.services.strategy_base import Strategy
    full_path = REPO_ROOT / strategy_class_path
    if not full_path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_deploy_to_account", str(full_path))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_deploy_to_account"] = mod
        spec.loader.exec_module(mod)
        for name in dir(mod):
            obj = getattr(mod, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, Strategy)
                and obj is not Strategy
                and getattr(obj, "__module__", "") == mod.__name__
            ):
                return obj
    except Exception as e:
        logger.warning("Failed to load strategy %s: %s", strategy_class_path, e)
    return None


def _strategy_label(module_name: str) -> str:
    """Derive a friendly label from the module name (snake_case -> Title Case)."""
    return module_name.replace("_", " ").replace("-", " ").title().replace(" ", "")


def _update_strategy_accounts(prefix: str, module_name: str, class_name: str, file_stem: str, label: str) -> bool:
    """Replace the RunningStrategy entry for `prefix` in strategy_accounts.py."""
    text = STRATEGY_ACCOUNTS_PATH.read_text(encoding="utf-8")
    # Match the full RunningStrategy(...) block whose prefix arg equals `prefix`.
    # Format: RunningStrategy("LABEL", "module",\n  "CLASS", "PREFIX", "file_stem", "ACCOUNT"),
    pattern = re.compile(
        r'RunningStrategy\(\s*"[^"]*",\s*"[^"]*",\s*"[^"]*",\s*"' + re.escape(prefix) + r'",\s*"[^"]*",\s*"[^"]*"\)',
        re.DOTALL,
    )
    if not pattern.search(text):
        logger.error("No RunningStrategy entry found for prefix %r in %s", prefix, STRATEGY_ACCOUNTS_PATH)
        return False
    # Preserve the existing account_number (last string arg) by capturing it.
    m = pattern.search(text)
    if m is None:
        return False
    account_number = m.group(0).rsplit('"', 2)[-2]
    replacement = (
        f'RunningStrategy("{label}", "{module_name}",\n'
        f'                    "{class_name}", "{prefix}", "{file_stem}", "{account_number}")'
    )
    text = pattern.sub(replacement, text, count=1)
    STRATEGY_ACCOUNTS_PATH.write_text(text, encoding="utf-8")
    logger.info("Updated strategy_accounts.py: prefix %r -> %s", prefix, module_name)
    return True


def _update_run_all(prefix: str, module_name: str, label: str) -> bool:
    """Replace the run_one line for `prefix` in run_all_strategies.sh."""
    text = RUN_ALL_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r'run_one\s+\S+\s+"' + re.escape(prefix) + r'"\s+"[^"]*"',
    )
    if not pattern.search(text):
        logger.error("No run_one line found for prefix %r in %s", prefix, RUN_ALL_PATH)
        return False
    replacement = f'run_one {module_name} "{prefix}" "{label}"'
    text = pattern.sub(replacement, text, count=1)
    RUN_ALL_PATH.write_text(text, encoding="utf-8")
    logger.info("Updated run_all_strategies.sh: prefix %r -> %s", prefix, module_name)
    return True


def deploy_strategy_to_account(strategy_class_path: str, account_prefix: str) -> Dict[str, str]:
    """Swap the strategy on `account_prefix` to `strategy_class_path`.

    Returns a dict describing what changed. Raises ValueError on invalid input.
    """
    if not account_prefix:
        raise ValueError("account_prefix is required (e.g. '1', '2', '3')")

    strategy_class = _load_strategy_class(strategy_class_path)
    if strategy_class is None:
        raise ValueError(f"Could not load Strategy subclass from {strategy_class_path}")

    module_name = Path(strategy_class_path).stem
    class_name = strategy_class.__name__
    file_stem = module_name
    label = _strategy_label(module_name)

    ok1 = _update_strategy_accounts(account_prefix, module_name, class_name, file_stem, label)
    ok2 = _update_run_all(account_prefix, module_name, label)
    if not (ok1 and ok2):
        raise RuntimeError("Failed to update one or both config files (see logs)")

    return {
        "account_prefix": account_prefix,
        "strategy_class_path": strategy_class_path,
        "module_name": module_name,
        "class_name": class_name,
        "label": label,
    }
