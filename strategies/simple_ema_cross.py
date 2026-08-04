"""
Simple EMA20/50 Crossover Strategy
===================================
Scans stocks for EMA20 crossing above EMA50.
Ranks by: 60% crossover angle + 40% market cap.
Holds top 3, score-squared sizing.
Exits: death cross (EMA20 < EMA50) or time stop (30d).

Uses the StrategyBacktestAdapter internally so standalone and
in-app paths produce IDENTICAL results.

Usage:
  cd backend && ./venv/bin/python ../strategies/simple_ema_cross.py
"""

import os, sys, json
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")

from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.simple_ema_cross import SimpleEMACross

# ── Configuration ──
AS_OF = "2020-01-01"
END = "2024-01-01"
CAPITAL = 100_000.0


def main():
    print("=" * 60)
    print("  SIMPLE EMA20/50 CROSSOVER STRATEGY")
    print("=" * 60)
    print(f"  Period:   {AS_OF} → {END}")
    print(f"  Capital:  ${CAPITAL:,.2f}")
    print("=" * 60)

    adapter = StrategyBacktestAdapter(SimpleEMACross())
    result = adapter.run(as_of=AS_OF, end=END, capital=CAPITAL)
    s = result["summary"]

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"  Return:     {s['total_return_pct']:>+8.2f}%")
    print(f"  Trades:     {s['total_trades']}")
    print(f"  Win Rate:   {s['win_rate']:.1f}%")
    print(f"  Profit Fac: {s['profit_factor']:.2f}")
    print(f"{'='*60}")

    # Export
    report_dir = os.path.join(os.path.dirname(__file__), "..", "docs", "reports")
    os.makedirs(report_dir, exist_ok=True)
    with open(os.path.join(report_dir, "summary.json"), "w") as f:
        json.dump(s, f, indent=2)
    print(f"  📊 Data exported")


if __name__ == "__main__":
    main()
