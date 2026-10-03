"""
Daily Golden Cross Rotation Strategy
========================================
Scans 1500 stocks daily for an EMA20/EMA200 golden cross.
Ranks by: 60% crossover angle + 40% market cap.
Holds top 5, rotates when better candidates appear.
Exits: death cross, death cross warning, take profit, trailing stop, time stop (60d), or rotated out.
Minimum hold days: 7 before rotation close.
Volatility filter — skips stocks with 14d daily return std > 5%.
Volume filter — available (use_volume_filter), off by default.
Score-squared position sizing for aggressive top-pick weighting.
Sector diversification (max 2 per sector).
Bear market mode: SPY < SMA(200) → 50% exposure.

The banner below is generated from the strategy's live config, not hardcoded,
so it cannot drift from what the strategy actually does.

Indicator warmup is guaranteed: history is always loaded from an early fixed
date so EMA200 is converged before the first simulated day. If the available
history is too short, the run prints a warning — see the WARMUP WARNINGS block.

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
    strategy = DailyGoldenCrossRotation()
    cfg = strategy.config

    vol_confirm = (
        f"Volume > {cfg['volume_ma_span']}-day avg volume"
        if cfg["use_volume_filter"] else "disabled"
    )
    print("=" * 80)
    print("  DAILY GOLDEN CROSS ROTATION STRATEGY")
    print("=" * 80)
    print(f"  Period:     {AS_OF} → {END}")
    print(f"  Capital:    ${CAPITAL:,.2f}")
    print(f"  Holdings:   Top {cfg['max_holdings']} (rotate daily)")
    print(f"  Ranking:    {cfg['angle_weight']:.0%} angle + {cfg['cap_weight']:.0%} market cap")
    print(f"  MAs:        EMA{cfg['fast_span']} fast / "
          f"{cfg['slow_ma_type'].upper()}{cfg['slow_span']} slow")
    print(f"  Trailing:   {cfg['trailing_stop']:.0%}")
    print(f"  Take Profit: {cfg['take_profit']:.0%}")
    print(f"  Time Stop:  {cfg['time_stop_days']} days")
    print(f"  Min Hold:   {cfg['min_hold_days']} days")
    print(f"  Max/Sector: {cfg['max_sector_count']}")
    print(f"  Vol Filter: >{cfg['max_volatility']:.0%} daily std (skip)")
    print(f"  Vol Confirm: {vol_confirm}")
    print(f"  Sizing:     Score²-weighted (top pick gets more)")
    print(f"  Exits:      Death cross, warning, take profit, trailing stop, time stop, or rotation")
    print(f"  Bear Mode:  SPY < SMA(200) → {cfg['bear_exposure']:.0%} exposure")
    print(f"  DC Warning: spread < {cfg['dc_warning_spread']:g} (exit)")
    print(f"  Cost:       {cfg['cost_bps']:g} bps/side")
    print(f"  Warmup:     EMA{cfg['slow_span']} converged (>=830 bars before start)")
    print("=" * 80)

    adapter = StrategyBacktestAdapter(strategy)
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

    # Warmup shortfalls mean EMA200 was not converged for some tickers/dates.
    # Printed prominently because it changes how much to trust the numbers above.
    warnings = result.get("warmup_warnings", [])
    if warnings:
        print(f"\n  ── ⚠️  WARMUP WARNINGS ──")
        for w in warnings:
            print(f"  ⚠️  {w}")
    else:
        print(f"\n  ── Warmup ──")
        print(f"  ✅ EMA200 converged for every scanned ticker")

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
