"""MQR_V1 -- Momentum Quality Rotation with a delayed trailing stop.

What changed from MQR, and why
------------------------------
Exactly one exit lever. The 12% trailing stop is held off until the position is
**7 calendar days** old. Every other rule, parameter, filter and the signal
engine are inherited unchanged from `MomentumQualityRotation`.

Evidence (`docs/reports/mqr_exit_gate_stage0_5_20261112.md`): over 100 paired
starts at 10 bps per side, disabling the trail for the first 7 days moved median
CAGR by +7.56 pts (winning on 73/100 starts) and raised Sharpe by 0.07. The
mechanism is that rotation already waits 14 days, but the trailing stop bypassed
that protection and sold on ordinary early noise — often re-entering the same
name the same day.

Threshold caveat -- read before changing the number
---------------------------------------------------
The dose-response is NOT monotone: 5 days does nothing (−0.08), 7 days peaks
(+7.56), 10 days is good (+5.33), 14 days is a large loss (−4.58). 7 was the
best-scoring value *in the same 100 starts used to measure it*, so it carries
selection risk; 10 was the pre-registered alternative and is the safer
default if you want a threshold that was not chosen by its own backtest.
Max drawdown does NOT improve at either setting (+3.3 pts worse at 7, +1.2 at
10). This is a return lever, not a risk lever.

Deployment
----------
Backtests: `StrategyBacktestAdapter(MomentumQualityRotationV1()).run(...)`.
The adapter honours `trailing_stop_min_hold_days`, and so does the frozen-entry
replay engine, so research and simulation agree.

Live/paper: `app.services.alpaca_runner` reads the same `RotationConfig`. On
entry it places a bracket with the take-profit and a FIXED hard stop (no trail),
then attaches the trailing stop once the position is old enough. Set the
deployment row's `strategy_path` to this file.
"""
from __future__ import annotations

from app.services.strategies.momentum_quality_rotation import MomentumQualityRotation
from app.services.strategy_base import Strategy

#: Calendar days before the 12% trailing stop may fire. See the caveat above.
TRAILING_STOP_MIN_HOLD_DAYS = 7

#: Default per-side cost for backtests of this version (basis points).
DEFAULT_COST_BPS = 10.0


class MomentumQualityRotationV1(MomentumQualityRotation, Strategy):
    """MQR with the trailing stop disabled for a position's first 7 days."""

    def __init__(self, **overrides):
        overrides.setdefault("trailing_stop_min_hold_days",
                             TRAILING_STOP_MIN_HOLD_DAYS)
        # Report V1 with a realistic cost by default: its whole case rests on a
        # 10 bps/side measurement, and a costless display would overstate it.
        overrides.setdefault("cost_bps", DEFAULT_COST_BPS)
        super().__init__(**overrides)

    def get_name(self) -> str:
        return "Momentum Quality Rotation V1"
