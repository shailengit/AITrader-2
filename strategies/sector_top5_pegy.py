"""
Sector Top-5 Momentum + PEGY — standalone runner
================================================
Combines the Sector Scanner Top-5 Rotation v3 momentum engine with a PEGY
fundamental filter and a 50/50 blended composite ranking.

Universe:  market cap >= $5B, 14-day vol <= 5%, scanner sector filter,
           as-of PEGY < 1.0 (computable, else not buyable).
Ranking:   composite = 0.50*sigmoid(perf_3m) + 0.50*(1/(1+PEGY)).
Exits:     hard stop 20%, trailing 10%, +50% take profit, no rotation.

This standalone reuses the in-app Strategy subclass through the
StrategyBacktestAdapter, so standalone and in-app results are identical
by construction.

Usage:
  cd backend && ./venv/bin/python ../strategies/sector_top5_pegy.py
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
from app.services.strategies.sector_top5_pegy import SectorTop5MomentumPEGY
from app.services.run_viewer_generator import generate_run_viewer

# ── Configuration (see docs/strategies/sector_top5_pegy-spec.md) ────
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
    "PEGY Threshold": 1.0,
    "Momentum Weight": 0.50,
    "PEGY Weight": 0.50,
    "Hard Stop": "20%",
    "Trailing Stop": "10%",
    "Take Profit": "50%",
    "Rotation": "disabled",
}


def main():
    print("=" * 78)
    print("  SECTOR TOP-5 MOMENTUM + PEGY")
    print("=" * 78)
    print(f"  Period:      {AS_OF} → {END}")
    print(f"  Capital:     ${CAPITAL:,.2f}")
    print(f"  Holdings:    Top 5")
    print(f"  Universe:    mcap >= $5B, vol <= 5%, scanner sector filter, PEGY < 1.0")
    print(f"  Ranking:     50% momentum + 50% PEGY (composite)")
    print(f"  Hard Stop:   20%")
    print(f"  Trailing:    10%")
    print(f"  Take Profit: +50%")
    print(f"  Rotation:    disabled (ride the winners)")
    print("=" * 78)

    strategy = SectorTop5MomentumPEGY()
    adapter = StrategyBacktestAdapter(strategy)
    result = adapter.run(as_of=AS_OF, end=END, capital=CAPITAL)
    s = result["summary"]

    print(f"\n{'='*78}")
    print("  PORTFOLIO SUMMARY")
    print("=" * 78)
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

    reasons = s.get("exit_reasons", {})
    if reasons:
        print(f"\n  ── Exit Reasons ──")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {r:>20}: {c} trades")

    print(f"\n{'='*78}")
    print("  ✅ DONE")
    print("=" * 78)

    # ── Export JSON summary ───────────────────────────────────────────
    report_dir = os.path.join(os.path.dirname(__file__), "..", "docs", "reports")
    os.makedirs(report_dir, exist_ok=True)
    summary_path = os.path.join(report_dir, "sector_top5_pegy_summary.json")
    with open(summary_path, "w") as f:
        json.dump(s, f, indent=2)
    print(f"  📊 JSON exported to {summary_path}")

    # ── Generate interactive HTML report ──────────────────────────────
    code_text = open(os.path.abspath(__file__), encoding="utf-8").read()
    try:
        with open(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "backend", "app", "services", "strategies", "sector_top5_pegy.py"),
            encoding="utf-8",
        ) as f:
            code_text += "\n\n# ── In-app Strategy subclass ──\n" + f.read()
    except Exception:
        pass

    experiment = {
        "run_index": 1,
        "status": "completed",
        "start_date": AS_OF,
        "end_date": END,
        "kpis": s,
    }
    html_path = generate_run_viewer(
        experiments=[experiment],
        strategy_name="Sector Top-5 Momentum + PEGY",
        strategy_code=code_text,
        strategy_params=PARAMS,
        batch_id="sector_top5_pegy",
        session_id="standalone",
    )
    print(f"  📈 HTML report: {html_path}")


if __name__ == "__main__":
    main()
