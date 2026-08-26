"""
Momentum Quality Rotation (MQR) — standalone runner
====================================================
Combines 3-month momentum with an as-of earnings-growth quality factor, and
adds a market regime filter (SPY < SMA200 -> 50% exposure) to cut drawdown.

Universe:  market cap >= $5B, 14-day vol <= 5%, scanner sector filter,
           as-of EPS growth > 0 (computable, else not buyable).
Ranking:   composite = 0.70*sigmoid(perf_3m*10) + 0.30*sigmoid(eps_growth*2).
Exits:     hard stop 20%, trailing 12%, +50% take profit, time stop 120d,
           rotation (14d min hold) with protect_winners.
Regime:    SPY < SMA(200) -> 50% exposure.

This standalone reuses the in-app Strategy subclass through the
StrategyBacktestAdapter, so standalone and in-app results are identical
by construction.

Usage:
  cd backend && ./venv/bin/python ../strategies/momentum_quality_rotation.py
"""

import os
import sys
import json
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")

from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.momentum_quality_rotation import MomentumQualityRotation

# ── Configuration (see docs/strategies/momentum_quality_rotation-spec.md) ──
AS_OF = "2021-01-01"
END = "2025-12-31"
CAPITAL = 100_000.0
PARAMS = {
    "AS_OF": AS_OF,
    "END": END,
    "CAPITAL": f"${CAPITAL:,.0f}",
    "Max Holdings": 5,
    "Max per Sector": 2,
    "Market Cap Min": "$5B",
    "Max Volatility": "5% (14d)",
    "Momentum Weight": 0.70,
    "Quality Weight": 0.30,
    "Hard Stop": "20%",
    "Trailing Stop": "12%",
    "Take Profit": "50%",
    "Time Stop": "120d",
    "Min Hold": "14d",
    "Protect Winners": True,
    "Bear Exposure": "50% (SPY < SMA200)",
}


def main():
    print("=" * 78)
    print("  MOMENTUM QUALITY ROTATION (MQR)")
    print("=" * 78)
    print(f"  Period:     {AS_OF} → {END}")
    print(f"  Capital:    ${CAPITAL:,.2f}")
    print(f"  Holdings:   Top 5 (rotate daily)")
    print(f"  Ranking:    70% momentum + 30% EPS-growth quality")
    print(f"  Hard Stop:  20% | Trailing: 12% | Take Profit: 50% | Time Stop: 120d")
    print(f"  Regime:     SPY < SMA(200) → 50% exposure")
    print("=" * 78)

    adapter = StrategyBacktestAdapter(MomentumQualityRotation())
    result = adapter.run(as_of=AS_OF, end=END, capital=CAPITAL)
    s = result["summary"]

    print(f"\n{'='*78}")
    print("  PORTFOLIO SUMMARY")
    print("=" * 78)
    print(f"  Initial Capital:  ${s['initial_capital']:>10,.2f}")
    print(f"  Final Portfolio:  ${s['final_portfolio']:>10,.2f}")
    print(f"  Total Return:     {s['total_return_pct']:>+8.2f}%")
    print(f"  CAGR:             {s.get('cagr_pct', 0):>+8.2f}%")
    print(f"  SPY Return:       {s['spy_return_pct']:>+8.2f}%")
    print(f"  Alpha:            {s['alpha_pct']:>+8.2f}%")
    print(f"\n  ── Trade Statistics ──")
    print(f"  Total Trades:     {s['total_trades']}")
    print(f"  Win Rate:         {s['win_rate']:.1f}%")
    print(f"  Profit Factor:    {s['profit_factor']:.2f}")
    print(f"  Sharpe:           {s['sharpe_ratio']:.2f}")
    print(f"  Max DD:           {s['max_drawdown_pct']:.1f}%")

    reasons = s.get("exit_reasons", {})
    if reasons:
        print(f"\n  ── Exit Reasons ──")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {r:>20}: {c} trades")

    print(f"\n{'='*78}")
    print("  ✅ DONE")
    print("=" * 78)

    # Export
    report_dir = os.path.join(os.path.dirname(__file__), "..", "docs", "reports")
    os.makedirs(report_dir, exist_ok=True)
    with open(os.path.join(report_dir, "momentum_quality_rotation_summary.json"), "w") as f:
        json.dump(s, f, indent=2)
    print(f"  📊 Data exported to {report_dir}/")


if __name__ == "__main__":
    main()
