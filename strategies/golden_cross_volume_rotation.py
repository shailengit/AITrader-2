"""
Golden Cross Volume Rotation Strategy
========================================
Scans 1500 stocks daily for EMA20/50 golden cross with volume confirmation.
Entry requires ALL of:
  - Price above 200-day SMA (trend filter)
  - EMA20 crosses above EMA50 on the signal day (golden cross)
  - Volume > 1.5x 50-day average on the cross day (volume confirmation)
  - 14-day daily-return std <= 5% (volatility filter)
Ranks by: 60% crossover angle + 40% market cap.
Buys the top 5, holds while a position stays in the top 10 (buy/hold spread),
rotates out only when a holding drops out of the top 10 or an exit rule fires.
Exits: death cross, trailing stop (20%), take profit (25%), time stop (90d),
hard stop loss (10%), or rotated out.
Minimum hold days: 10 before rotation close.
Score-weighted position sizing (higher composite score = larger position).
Sector diversification (max 2 per sector).
Bear market mode: SPY < SMA(200) -> go to cash (0% exposure).

Uses the StrategyBacktestAdapter internally so standalone and
in-app paths produce IDENTICAL results.

Usage:
  cd backend && ./venv/bin/python ../strategies/golden_cross_volume_rotation.py
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
from app.services.strategies.golden_cross_volume_rotation import GoldenCrossVolumeRotation

# ── Configuration ──
AS_OF = "2020-01-01"
END = "2026-09-04"
CAPITAL = 100_000.0


def main():
    print("=" * 80)
    print("  GOLDEN CROSS VOLUME ROTATION STRATEGY")
    print("=" * 80)
    print(f"  Period:     {AS_OF} → {END}")
    print(f"  Capital:    ${CAPITAL:,.2f}")
    print(f"  Holdings:   Top 5 (buy), hold while in top 10")
    print(f"  Ranking:    60% angle + 40% market cap")
    print(f"  Entry:      EMA20/50 golden cross + price>SMA200 + volume>1.5x50d")
    print(f"  Trailing:   20%")
    print(f"  Take Profit: 25%")
    print(f"  Hard Stop:  10%")
    print(f"  Time Stop:  90 days")
    print(f"  Min Hold:   10 days")
    print(f"  Max/Sector: 2")
    print(f"  Vol Filter: >5% daily std (skip)")
    print(f"  Sizing:     Score-weighted (higher score = larger position)")
    print(f"  Exits:      Death cross, hard stop, take profit, trailing stop, time stop, or rotation")
    print(f"  Bear Mode:  SPY < SMA(200) → cash (0% exposure)")
    print("=" * 80)

    adapter = StrategyBacktestAdapter(GoldenCrossVolumeRotation())
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
