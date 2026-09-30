"""Reset all three Alpaca paper accounts to (possibly new) strategies in one command.

This avoids hand-editing strategy_accounts.py + run_all_strategies.sh. It calls
deploy_strategy_to_account() for each of the three running accounts, which swaps
the strategy module/class/label while PRESERVING the account prefix and paper
account number (Workflow A from the alpaca-strategy-swap skill).

Usage (from backend/):
  ./venv/bin/python scripts/redeploy_strategies.py \
      backend/app/services/strategies/momentum_quality_rotation.py \
      backend/app/services/strategies/daily_golden_cross.py \
      backend/app/services/strategies/sector_top5_pegy.py

Each path maps to account prefix "1","2","3" in order (1st arg -> account 1,
2nd -> account 2, 3rd -> account 3).

NOTE: This does NOT reset account cash/balance. Alpaca paper accounts are reset
to $100k from the Alpaca Dashboard (Paper trading -> account -> 'Reset Account').
This just repoints which strategy trades on each account.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.strategy_deploy import deploy_strategy_to_account

# (prefix, account label)
ACCOUNTS = [
    ("1", "Momentum Quality Rotation / account 1"),
    ("2", "Daily Golden Cross Rotation / account 2"),
    ("3", "Sector Top-5 PEGY / account 3"),
]


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        print("ERROR: provide exactly 3 strategy class paths (one per account).")
        return 2

    paths = sys.argv[1:4]
    for (prefix, label), path in zip(ACCOUNTS, paths):
        print("*" * 62)
        print("Deploying to prefix %s (%s)" % (prefix, label))
        try:
            result = deploy_strategy_to_account(path, prefix)
            print("  -> OK: %s / class=%s (module=%s)" % (
                result["label"], result["class_name"], result["module_name"]))
        except ValueError as e:
            print("  !! ERROR:", e)
            return 1
        except RuntimeError as e:
            print("  !! ERROR:", e)
            return 1

    print("=" * 62)
    print("All 3 accounts repointed. Next: reset cash to $100k in the Alpaca")
    print("paper dashboard, then run scripts/run_all_strategies.sh (or wait for the")
    print("20:00 schedule) so the new strategies place their first orders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
