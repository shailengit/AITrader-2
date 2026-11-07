"""
Trend-Pullback Resumption Rotation Strategy
===========================================
Buys strength on a dip: a stock in a rising EMA200 regime, aligned on EMA50 >
EMA200, that pulls back below EMA20 and then crosses back above it with MACD
turning up and RSI between 45 and 75.

Ranks by: 60% risk-adjusted 126-day momentum + 40% log market cap (fixed scales).
Holds top 5, rotates when stronger candidates appear.
Exits: trend break (close < EMA200), hard stop 10%, take profit 40%,
trailing stop 20%, time stop 120 days, or rotated out.
Risk: max 2 per sector, 50% exposure when SPY < SMA200, 5bps/side costs.

Warmup is guaranteed: history loads from a 2008 floor so EMA200 is converged
(>=830 bars) before the first simulated day.

This is a THIN CLI wrapper: all strategy logic lives in the in-app Strategy ABC
subclass, and both paths run through the same StrategyBacktestAdapter, so their
results are identical by construction.

The banner is generated from the strategy's live config, not hardcoded.

Usage:
  cd backend && ./venv/bin/python ../strategies/trend_pullback_resumption.py
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
from app.services.strategies.trend_pullback_resumption import TrendPullbackResumption

# ── Configuration ──
AS_OF = "2020-01-01"
END = "2026-09-30"
CAPITAL = 100_000.0


def main():
    strategy = TrendPullbackResumption()
    cfg = strategy.config

    print("=" * 80)
    print("  TREND-PULLBACK RESUMPTION ROTATION STRATEGY")
    print("=" * 80)
    print(f"  Period:       {AS_OF} → {END}")
    print(f"  Capital:      ${CAPITAL:,.2f}")
    print(f"  Holdings:     Top {cfg['max_holdings']} (rotate daily)")
    print(f"  Regime:       Close > EMA{cfg['ema_slow']}, EMA{cfg['ema_slow']} rising "
          f"{cfg['slow_rising_lookback']}d")
    print(f"  Structure:    EMA{cfg['ema_mid']} > EMA{cfg['ema_slow']}")
    trigger = (
        f"Pullback below EMA{cfg['ema_fast']} within {cfg['pullback_window']}d, "
        f"then close back above it"
        if cfg["use_pullback"]
        else f"Close crosses back above EMA{cfg['ema_fast']} (no pullback test)"
    )
    guard = (
        f"RSI({cfg['rsi_period']}) in [{cfg['rsi_floor']:g}, {cfg['rsi_ceiling']:g}]"
        if cfg["use_rsi_filter"] else "off (measured inert)"
    )
    print(f"  Trigger:      {trigger}")
    print(f"  Momentum:     MACD {cfg['macd_fast']}/{cfg['macd_slow']}/{cfg['macd_signal']} "
          f"> signal line")
    print(f"  Guard:        {guard}")
    print(f"  Liquidity:    >= ${cfg['min_dollar_volume']/1e6:,.0f}M 20d dollar volume")
    print(f"  Vol Filter:   >{cfg['max_volatility']:.0%} 20d std (skip)")
    print(f"  Fresh Cross:  {'required within %dd' % cfg['cross_window'] if cfg['require_fresh_cross'] else 'not required (state only)'}")
    print(f"  Ranking:      {cfg['mom_weight']:.0%} risk-adj {cfg['mom_window']}d momentum "
          f"+ {cfg['cap_weight']:.0%} log mkt-cap")
    print(f"  Sizing:       Linear score-weighted")
    print(f"  Exits:        Trend break (<EMA{cfg['ema_slow']}), stop "
          f"{cfg['hard_stop_loss']:.0%}, TP {cfg['take_profit']:.0%}, "
          f"trail {cfg['trailing_stop']:.0%}, time {cfg['time_stop_days']}d")
    print(f"  Min Hold:     {cfg['min_hold_days']} days")
    print(f"  Max/Sector:   {cfg['max_sector_count']}")
    print(f"  Bear Mode:    SPY < SMA(200) → {cfg['bear_exposure']:.0%} exposure")
    print(f"  Cost:         {cfg['cost_bps']:g} bps/side")
    print(f"  Warmup:       EMA{cfg['ema_slow']} converged (>=830 bars before start)")
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
    print(f"  Alpha / year:     {s['alpha_per_year_pct']:>+8.2f}%")
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
        print(f"  ✅ EMA{cfg['ema_slow']} converged for every scanned ticker")

    print(f"\n{'='*80}")
    print("  ✅ DONE")
    print("=" * 80)

    report_dir = os.path.join(os.path.dirname(__file__), "..", "docs", "reports")
    os.makedirs(report_dir, exist_ok=True)
    with open(os.path.join(report_dir, "trend_pullback_resumption_summary.json"), "w") as f:
        json.dump(s, f, indent=2)
    print(f"  📊 Data exported to {report_dir}/")


if __name__ == "__main__":
    main()
