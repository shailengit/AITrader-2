"""
Momentum Quality Rotation V1
============================
Same engine as Momentum Quality Rotation, with ONE change:

  the 12% trailing stop is not armed until a position is 7 calendar days old.

Why: rotation already waits 14 days, but the trailing stop bypassed that
protection and sold on ordinary early noise — often re-buying the same name the
same day. Over 100 paired start dates at 10 bps/side, postponing the trail moved
median CAGR by +7.56 pts (73/100 starts) and Sharpe by +0.07.

Caveat: the dose-response is not monotone (5d ≈ 0, 7d +7.56, 10d +5.33,
14d −4.58) and 7 was the best-scoring value in the same sample that measured it.
10 days is the safer, pre-registered alternative. Max drawdown does NOT improve
(+3.3 pts worse at 7d): this is a return lever, not a risk lever.

Everything else is inherited unchanged: $5B cap + 5% vol + sector-relative
momentum filter; sigmoid(perf_3m × 10) ranking; sector cap 2; top 5; hard stop
20%; take profit +50%; time stop 120d; 14-day rotation minimum with
protect_winners; 50% exposure when SPY < SMA200.

This file is a THIN WRAPPER: it delegates to MomentumQualityRotationV1 through
StrategyBacktestAdapter, so standalone and in-app runs are identical by
construction — the logic is never duplicated here.

Usage:
  cd backend && ./venv/bin/python ../strategies/momentum_quality_rotation_v1.py
"""

import os
import sys
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")

from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.momentum_quality_rotation_v1 import (
    MomentumQualityRotationV1,
)

# ── Configuration ──
AS_OF = "2020-01-01"
END = "2026-11-11"
CAPITAL = 100_000.0
COST_BPS = 10.0          # honest default: 10 bps per side

strategy = MomentumQualityRotationV1(cost_bps=COST_BPS)
adapter = StrategyBacktestAdapter(strategy)
result = adapter.run(as_of=AS_OF, end=END, capital=CAPITAL)


def main():
    s = result["summary"]
    cfg = strategy.get_rotation_config()
    print("=" * 64)
    print(f"  {strategy.get_name()}")
    print(f"  {AS_OF} → {END}   capital ${CAPITAL:,.0f}   costs {COST_BPS:.0f} bps/side")
    print("=" * 64)
    print(f"  trailing stop armed after : {cfg.trailing_stop_min_hold_days} calendar days")
    print(f"  trailing stop            : {cfg.trailing_stop:.0%} from peak")
    print(f"  hard stop / take profit  : {cfg.hard_stop_loss:.0%} / {cfg.take_profit:.0%}")
    print(f"  time stop / min hold     : {cfg.time_stop_days}d / {cfg.min_hold_days}d")
    print(f"  bear exposure            : {cfg.bear_exposure:.0%}")
    print("-" * 64)
    print(f"  CAGR              : {s['cagr_pct']:.2f}%")
    print(f"  Alpha / yr        : {s['alpha_per_year_pct']:.2f} pp")
    print(f"  Sharpe            : {s['sharpe_ratio']:.2f}")
    print(f"  Max drawdown      : {s['max_drawdown_pct']:.1f}%")
    print(f"  Trades / yr       : {s['trades_per_year']:.1f}")
    print(f"  Win rate / PF     : {s['win_rate']:.1f}% / {s['profit_factor']:.2f}")
    print(f"  Final portfolio   : ${s['final_portfolio']:,.0f}")
    print(f"  Exit mix          : {s['exit_reasons']}")
    if result.get("warmup_warnings"):
        print("  WARMUP WARNINGS   :", result["warmup_warnings"])
    print("=" * 64)
    return result


if __name__ == "__main__":
    main()
