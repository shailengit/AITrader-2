"""Takeoff Momentum Day-Trade Strategy — standalone runner.

Scans ~1500 stocks on DAILY data (`sp1500_1d`) on signal day D for stocks
"primed to take off", then executes intraday on 1-MINUTE data (`sp1500_1m`)
on the next trading day D+1.

Daily composite screen (day D):
  - Momentum 70%  — EMA5 crosses above EMA200, close[yesterday] > EMA5[yesterday],
                    ranked by 5-day angle between EMA5 and EMA200.
  - Volatility 10% — Bollinger (20,2) squeeze (low bandwidth = building energy).
  - Volume    20%  — volume surge: volume[D] >= 1.5x the prior-5-day average.
  Filters: price > $10, avg 20d daily dollar volume > $50M; ETFs excluded.
  Select top 5, max 2 per sector.

Intraday execution (day D+1, on 1-minute bars):
  - Entry: close of first 1-min bar whose close > prior day close (confirmation).
  - Exits (priority): +4% take-profit -> -1% stop-loss -> 2% trailing ->
    3:55 PM end-of-day liquidation. No overnight positions.
Position sizing: score-weighted across the day's picks over $100k capital.

This standalone runner imports the SAME in-app engine
(`app.services.strategies.takeoff_momentum_day.TakeoffMomentumDay`) and calls
`intraday_backtest()`, so standalone and in-app results are IDENTICAL.

Usage:
  cd backend && ./venv/bin/python ../strategies/takeoff_momentum_day.py
"""

import os, sys, json, warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")

from app.services.strategies.takeoff_momentum_day import TakeoffMomentumDay

# ── Configuration ──
CAPITAL = 100_000.0
# Trade days = the days with 1-minute data (D+1). Leave empty (None) to derive
# automatically from the 1-minute database, so the backtest always uses the
# full available intraday window as data accumulates.
TRADE_DAYS = None


def main():
    print("=" * 80)
    print("  TAKEOFF MOMENTUM DAY-TRADE STRATEGY")
    print("=" * 80)
    print(f"  Capital:      ${CAPITAL:,.2f}")
    print(f"  Trade days:   auto-derived from 1-minute database (full available window)")
    print(f"  Screen:       EMA5>EMA200 cross + close>EMA5, ranked by 5d angle")
    print(f"  Composite:    70% momentum + 10% volatility + 20% volume")
    print(f"  Volume surge: >=1.5x prior-5-day avg; dollar-vol > $50M; price > $10")
    print(f"  Max holdings: 5 (max 2/sector)")
    print(f"  Sizing:       Score-weighted")
    print(f"  Entry:        Confirmation bar (close > prior day close)")
    print(f"  Exits:        +4% TP -> -2% SL -> 2% trail -> 3:55 PM close\n  Entry filter:  skip gap-up > 2.5% (momentum-exhaustion avoid)")
    print("=" * 80)

    strategy = TakeoffMomentumDay()
    result = strategy.intraday_backtest(trade_days=TRADE_DAYS, capital=CAPITAL)
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

    reasons = s.get("exit_reasons", {})
    if reasons:
        print(f"\n  ── Exit Reasons ──")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {r:>20}: {c} trades")

    print(f"\n  ── Daily P&L ──")
    from collections import defaultdict
    byday = defaultdict(list)
    for t in result["trades"]:
        if t["side"] == "SELL":
            byday[t["exit_date"]].append(t)
    for d in sorted(byday):
        day_pnl = sum(t["pnl_dollars"] for t in byday[d])
        print(f"  {d}: ${day_pnl:>+10,.2f}  ({len(byday[d])} trades)")

    print(f"\n{'='*80}")
    print("  ✅ DONE")
    print("=" * 80)

    # Export report data
    report_dir = os.path.join(os.path.dirname(__file__), "..", "docs", "reports")
    os.makedirs(report_dir, exist_ok=True)
    # Capture the actual trade days used (derived from the 1m DB when TRADE_DAYS is None)
    used_days = sorted({t["entry_date"] for t in result["trades"]})
    data = {
        "strategy": "takeoff_momentum_day",
        "capital": CAPITAL,
        "trade_days": used_days,
        "summary": s,
        "trades": result["trades"],
        "daily_equity": result["daily_equity"],
    }
    with open(os.path.join(report_dir, "takeoff_momentum_day_data.json"), "w") as f:
        json.dump(data, f, indent=2)
    print(f"  📊 Data exported to {report_dir}/takeoff_momentum_day_data.json")


if __name__ == "__main__":
    main()
