"""Sector Scanner Top-5 Rotation v2 — "Protect the Winners" variant.

Same universe filter, ranking and momentum-proportional sizing as the
original sector_scanner_top5_rotation, but with a smarter exit policy that
lets the most profitable stocks ride higher instead of churning them out:

  - protect_winners=True: a holding that leaves the top-5 is KEPT as long as
    it is still profitable (above its entry price). Only genuinely weak
    (losing) names are rotated out to free a slot for a new leader. This
    directly addresses the start-date sensitivity: strong momentum names are
    no longer sold at +4% the moment a new name has slightly higher momentum.
  - Take profit (+50%) retained as the primary profit engine.

Empirically (100-run batch, identical signals): the original averaged ~29%
CAGR with a 13.7-57% spread; this variant raises the mean to ~35% and the
worst-case floor to ~17% while roughly doubling take-profit captures.
"""

from app.services.strategies.sector_scanner_top5_rotation import (
    SectorScannerTop5Rotation,
    MAX_HOLDINGS, SIZING_PCTS, HARD_STOP, TAKE_PROFIT, MIN_HOLD_DAYS,
    MAX_SECTOR_COUNT, MIN_MARKET_CAP, MAX_VOLATILITY, MOMENTUM_K,
)
from app.services.strategy_base import Strategy, RotationConfig


class SectorScannerTop5RotationV2(SectorScannerTop5Rotation, Strategy):
    """Protect-the-winners variant of the Sector Scanner Top-5 Rotation."""

    def get_name(self) -> str:
        return "Sector Scanner Top-5 Rotation v2 (Protect Winners)"

    def get_rotation_config(self) -> RotationConfig:
        return RotationConfig(
            sizing_method="linear",        # momentum-proportional
            hard_stop_loss=HARD_STOP,      # 20% hard stop
            trailing_stop=0.10,            # 10% trailing stop (best v2 config)
            take_profit=TAKE_PROFIT,       # +50% take profit
            time_stop_days=0,              # never (rotation/stop/TP are the exits)
            min_hold_days=MIN_HOLD_DAYS,   # 14 days before rotation can act
            max_sector_count=MAX_SECTOR_COUNT,
            re_score_holdings=True,        # re-score holdings on current momentum daily
            protect_winners=True,          # keep profitable names that leave the top-5
            bear_exposure=1.0,
            exit_priority=["hard_stop_loss", "trailing_stop", "take_profit"],
        )
