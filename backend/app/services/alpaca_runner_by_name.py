"""Generic multi-account strategy runner.

Runs ANY Strategy subclass on a specific Alpaca account (by credential prefix),
leaving the deployments-registry (default-account) strategy untouched.

Usage:
    python -m app.services.alpaca_runner_by_name <strategy_module> <prefix>

Examples:
    python -m app.services.alpaca_runner_by_name daily_golden_cross LS
    python -m app.services.alpaca_runner_by_name sector_scanner_top5_rotation 3

<strategy_module> is the strategy filename WITHOUT .py (imported from
app.services.strategies). <prefix> is the ALPACA_<PREFIX>_KEY credential prefix
('' = default keys, 'LS', '3', etc.). Real orders ARE placed.
"""
import importlib
import logging
import sys

from app.services.alpaca_runner import StrategyRunner
from app.services.alpaca_client import AlpacaClient


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    if len(sys.argv) < 3:
        print("usage: alpaca_runner_by_name <strategy_module> <prefix>")
        sys.exit(2)
    module_name, prefix = sys.argv[1], sys.argv[2]

    mod = importlib.import_module(f"app.services.strategies.{module_name}")
    strategy_cls = None
    from app.services.strategy_base import Strategy
    for name in dir(mod):
        obj = getattr(mod, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, Strategy)
            and obj is not Strategy
            and getattr(obj, "__module__", "") == mod.__name__
        ):
            strategy_cls = obj
            break
    if strategy_cls is None:
        print(f"no Strategy subclass in {module_name}")
        sys.exit(2)

    strategy = strategy_cls()
    runner = StrategyRunner(strategy)
    runner.alpaca = AlpacaClient(prefix=prefix)

    acct = runner.alpaca.get_account()
    print(f"Running {strategy.get_name()} on account {acct.get('account_number')} (prefix '{prefix or 'default'}')")

    result = runner.run_daily()

    print("=" * 60)
    print(f"  {strategy.get_name()} — DAILY RUN (prefix '{prefix or 'default'}')")
    print(f"  Date:   {result['date']}")
    print(f"  Status: {result['status']}")
    print("=" * 60)
    for o in result["orders_placed"]:
        print(f"    BUY  {o['ticker']:>6}  {o['qty']:>4}  score={o['score']:.2f}")
    for c in result["positions_closed"]:
        print(f"    SELL {c['ticker']:>6}  reason={c['reason']}")
    if result["errors"]:
        print(f"  Errors: {len(result['errors'])}")
        for e in result["errors"]:
            print(f"    ❌ {e}")
    print("=" * 60)


if __name__ == "__main__":
    main()
