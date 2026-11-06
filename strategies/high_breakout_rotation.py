"""
52-Week High Breakout Rotation Strategy
=======================================
Buys strength: a fresh 252-day closing high on above-average volume.
Ranks by: 70% 12-week relative strength + 30% log market cap (fixed scales).
Holds top 5, rotates when stronger breakouts appear.
Exits: momentum breakdown (close < EMA50), hard stop, take profit,
trailing stop, time stop, or rotated out.
Warmup is guaranteed: history loads from a 2008 floor so the 252-day high is
warm before the first simulated day.

This is a THIN CLI wrapper: all strategy logic lives in the in-app Strategy ABC
subclass, and both paths run through the same StrategyBacktestAdapter, so their
results are identical by construction.

The banner is generated from the strategy's live config, not hardcoded.

Usage:
  cd backend && ./venv/bin/python ../strategies/high_breakout_rotation.py
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
from app.services.strategies.high_breakout_rotation import HighBreakoutRotation

# ── Configuration ──
AS_OF = "2023-01-01"
END = "2026-09-30"
CAPITAL = 100_000.0


def main():
    strategy = HighBreakoutRotation()
    cfg = strategy.config

    vol_confirm = (
        f"Volume > {cfg['volume_mult']:g}x {cfg['volume_ma_span']}-day avg"
        if cfg["use_volume_filter"] else "disabled"
    )
    print("=" * 80)
    print("  52-WEEK HIGH BREAKOUT ROTATION STRATEGY")
    print("=" * 80)
    print(f"  Period:      {AS_OF} → {END}")
    print(f"  Capital:     ${CAPITAL:,.2f}")
    print(f"  Holdings:    Top {cfg['max_holdings']} (rotate daily)")
    print(f"  Entry:       Fresh {cfg['high_window']}-day high")
    print(f"  Vol Confirm: {vol_confirm}")
    print(f"  Vol Filter:  >{cfg['max_volatility']:.0%} 14d std (skip)")
    print(f"  Ranking:     {cfg['rs_weight']:.0%} {cfg['rs_window']}d rel-strength "
          f"+ {cfg['cap_weight']:.0%} log mkt-cap")
    print(f"  Sizing:      Linear score-weighted")
    print(f"  Exits:       Breakdown (close < EMA{cfg['fast_span']}), "
          f"stop {cfg['hard_stop_loss']:.0%}, TP {cfg['take_profit']:.0%}, "
          f"trail {cfg['trailing_stop']:.0%}, time {cfg['time_stop_days']}d")
    print(f"  Min Hold:    {cfg['min_hold_days']} days")
    print(f"  Max/Sector:  {cfg['max_sector_count']}")
    print(f"  Bear Mode:   SPY < SMA(200) → {cfg['bear_exposure']:.0%} exposure")
    print(f"  Cost:        {cfg['cost_bps']:g} bps/side")
    print(f"  Warmup:      >=300 bars before any signal")
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
    print(f"  CAGR:             {s['cagr_pct']:>+8.2f}%")
    print(f"\n  ── Trade Statistics ──")
    print(f"  Total Trades:     {s['total_trades']}")
    print(f"  Win Rate:         {s['win_rate']:.1f}%")
    print(f"  Profit Factor:    {s['profit_factor']:.2f}")
    print(f"  Sharpe:           {s['sharpe_ratio']:.2f}")
    print(f"  Max DD:           {s['max_drawdown_pct']:.1f}%")
    print(f"  Trades/yr:        {s['trades_per_year']:.1f}")

    reasons = s.get("exit_reasons", {})
    if reasons:
        print(f"\n  ── Exit Reasons ──")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {r:>22}: {c} trades")

    warnings_list = result.get("warmup_warnings", [])
    if warnings_list:
        print(f"\n  ── ⚠️  WARMUP WARNINGS ──")
        for w in warnings_list:
            print(f"  ⚠️  {w}")
    else:
        print(f"\n  ── Warmup ──")
        print(f"  ✅ Longest indicator warm for every scanned ticker")

    print(f"\n{'='*80}")
    print("  ✅ DONE")
    print("=" * 80)

    report_dir = os.path.join(os.path.dirname(__file__), "..", "docs", "reports")
    os.makedirs(report_dir, exist_ok=True)
    with open(os.path.join(report_dir, "high_breakout_rotation_summary.json"), "w") as f:
        json.dump(s, f, indent=2)
    print(f"  📊 Data exported to {report_dir}/")


if __name__ == "__main__":
    main()
