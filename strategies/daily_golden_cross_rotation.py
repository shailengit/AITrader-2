"""
Daily Golden Cross Rotation Strategy
========================================
Scans 1500 stocks daily for EMA20/200 golden cross.
Ranks by: 60% crossover angle + 40% market cap.
Holds top 5, rotates when better candidates appear.
Exits: death cross, death cross warning, take profit, trailing stop, time stop (60d), or rotated out.
Minimum hold days: 7 before rotation close.
Volatility filter — skips stocks with 14d daily return std > 5%.
Score-squared position sizing for aggressive top-pick weighting.
Sector diversification (max 2 per sector).
Bear market mode: SPY < SMA(200) → 50% exposure.

Uses the StrategyBacktestAdapter internally so standalone and
in-app paths produce IDENTICAL results.

Usage:
  cd backend && ./venv/bin/python ../strategies/daily_golden_cross_rotation.py
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
from app.services.strategies.daily_golden_cross import DailyGoldenCrossRotation

# ── Configuration ──
AS_OF = "2020-01-01"
END = "2026-07-08"
CAPITAL = 100_000.0


def main():
    print("=" * 80)
    print("  DAILY GOLDEN CROSS ROTATION STRATEGY")
    print("=" * 80)
    print(f"  Period:     {AS_OF} → {END}")
    print(f"  Capital:    ${CAPITAL:,.2f}")
    print(f"  Holdings:   Top 5 (rotate daily)")
    print(f"  Ranking:    60% angle + 40% market cap")
    print(f"  Trailing:   20%")
    print(f"  Take Profit: 30%")
    print(f"  Time Stop:  60 days")
    print(f"  Min Hold:   7 days")
    print(f"  Max/Sector: 2")
    print(f"  Vol Filter: >5% daily std (skip)")
    print(f"  Sizing:     Score²-weighted (top pick gets more)")
    print(f"  Exits:      Death cross, warning, take profit, trailing stop, time stop, or rotation")
    print(f"  Bear Mode:  SPY < SMA(200) → 50% exposure")
    print("=" * 80)

    adapter = StrategyBacktestAdapter(DailyGoldenCrossRotation())
    result = adapter.run(as_of=AS_OF, end=END, capital=CAPITAL)
    s = result["summary"]

    print(f"\n{'='*80}")
    print("  PORTFOLIO SUMMARY")
    print("=" * 80)
    print(f"  Initial Capital:  ${s['initial_capital']:>10,.2f}")
    print(f"  Final Portfolio:  ${s['final_portfolio']:>10,.2f}")
    print(f"  Total Return:     {s['total_return_pct']:>+8.2f}%")
    print(f"  SPY Return:       {s['spy_return_pct']:>+8.2f}%")
    print(f"  Alpha:            {s['alpha_pct']:>+8.2f}%")
    print(f"\n  ── Trade Statistics ──")
    print(f"  Total Trades:     {s['total_trades']}")
    print(f"  Win Rate:         {s['win_rate']:.1f}%")
    print(f"  Profit Factor:    {s['profit_factor']:.2f}")
    print(f"  Sharpe:           {s['sharpe_ratio']:.2f}")
    print(f"  Max DD:           {s['max_drawdown_pct']:.1f}%")

    # Exit reason breakdown
    reasons = s.get("exit_reasons", {})
    if reasons:
        print(f"\n  ── Exit Reasons ──")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {r:>20}: {c} trades")

    print(f"\n{'='*80}")
    print("  ✅ DONE")
    print("=" * 80)

    # Export
    report_dir = os.path.join(os.path.dirname(__file__), "..", "docs", "reports")
    os.makedirs(report_dir, exist_ok=True)
    with open(os.path.join(report_dir, "summary.json"), "w") as f:
        json.dump(s, f, indent=2)
    print(f"  📊 Data exported to {report_dir}/")


if __name__ == "__main__":
    main()
