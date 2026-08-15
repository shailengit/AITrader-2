"""Sector Scanner Top-5 Rotation v3 — "No Rotation / Ride the Winners".

Same universe filter, ranking and momentum-proportional sizing as the
original, but with rotation DISABLED: the top-5 momentum names are bought and
held until a real exit fires (hard stop, trailing stop, or +50% take-profit),
and only then is the freed slot filled with the next top-5 name.

Why: the 100-run A/B showed that every rotation buys a MORE extended momentum
name (higher 3-month momentum = more overbought), which tends to mean-revert.
So the churn itself is net-negative. Disabling rotation lets the strongest
names ride to the +50% take-profit instead of being churned out at +4%.

Empirically (100-run batch, identical signals) this is the strongest variant:
  - Mean CAGR 29.2% -> 38.3%
  - Worst-case floor 13.7% -> 22.6%  (directly shrinks the start-date spread)
  - Max drawdown 62.0% -> 57.7%     (lowest of all variants)
"""

from app.services.strategies.sector_scanner_top5_rotation import (
    SectorScannerTop5Rotation,
    MAX_HOLDINGS, SIZING_PCTS, HARD_STOP, TAKE_PROFIT, MIN_HOLD_DAYS,
    MAX_SECTOR_COUNT, MIN_MARKET_CAP, MAX_VOLATILITY, MOMENTUM_K,
)
from app.services.strategy_base import Strategy, RotationConfig

# A huge min-hold disables the rotation exit entirely (hold until stop/TP/trailing).
_NO_ROTATION_HOLD_DAYS = 1_000_000


class SectorScannerTop5RotationV3(SectorScannerTop5Rotation, Strategy):
    """No-rotation variant: hold the top-5 momentum names until a real exit."""

    def get_name(self) -> str:
        return "Sector Scanner Top-5 Rotation v3 (No Rotation)"

    def get_rotation_config(self) -> RotationConfig:
        return RotationConfig(
            sizing_method="linear",        # momentum-proportional
            hard_stop_loss=HARD_STOP,      # 20% hard stop
            trailing_stop=0.10,            # 10% trailing stop (exits dead money)
            take_profit=TAKE_PROFIT,       # +50% take profit
            time_stop_days=0,              # never
            min_hold_days=_NO_ROTATION_HOLD_DAYS,  # rotation effectively disabled
            max_sector_count=MAX_SECTOR_COUNT,
            re_score_holdings=True,        # re-score holdings on current momentum daily
            protect_winners=False,
            bear_exposure=1.0,
            exit_priority=["hard_stop_loss", "trailing_stop", "take_profit"],
        )
