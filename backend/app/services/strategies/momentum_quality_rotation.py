"""Momentum Quality Rotation (MQR) — pluggable Strategy implementation.

Design (v2, after honest backtesting):
  The pure momentum engine (sector_top5) already delivers ~46% CAGR on the
  full period. The single highest-value, defensible improvement is a MARKET
  REGIME FILTER: cut exposure to 50% when SPY < SMA(200). This preserves the
  momentum engine's return while reducing drawdown in bear markets.

  A quality (EPS-growth) factor was tested and REMOVED — it shrank the
  universe and reduced CAGR (4.5% vs 46%). Momentum alone is the edge here.

Universe filter (ALL must pass):
  - Market cap >= $5B
  - 14-day daily-return std <= 5%
  - Scanner sector filter: stock's 3-mo perf beats its sector ETF

Ranking: sigmoid(perf_3m * 10) descending, sector-capped at 2, top 5.

Exits: hard stop 20%, trailing 12%, take profit +50%, time stop 120d,
       rotation (14d min hold) with protect_winners.

Market regime: SPY < SMA(200) -> bear_exposure 0.50.
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from app.services.strategy_base import Strategy, Signal, RotationConfig
from app.services.strategies.sector_scanner_top5_rotation import (
    SectorScannerTop5Rotation,
    MAX_HOLDINGS, SIZING_PCTS, HARD_STOP, MIN_HOLD_DAYS,
    MAX_SECTOR_COUNT, MIN_MARKET_CAP, MAX_VOLATILITY, MOMENTUM_K,
)

logger = logging.getLogger(__name__)

# ── MQR-specific parameters ──────────────────────────────────────────
TRAILING_STOP = 0.12       # 12% trailing stop from peak
TAKE_PROFIT = 0.50         # +50% take profit
TIME_STOP_DAYS = 120       # time stop
BEAR_EXPOSURE = 0.50       # cut exposure when SPY < SMA200

# Defaults are the verified 100-run baseline (269 trades/run, Sharpe 1.58).
# Do not move one without re-measuring: the numbers are only comparable to a
# sweep variant if the baseline runs on exactly these values.
DEFAULTS = {
    "sizing_method": "linear",           # momentum-proportional
    "hard_stop_loss": HARD_STOP,         # 20% hard stop
    "trailing_stop": TRAILING_STOP,      # 12% trailing stop
    "trailing_stop_activation": 0.0,     # 0 = trail armed from entry (baseline)
    "take_profit": TAKE_PROFIT,          # +50% take profit
    "time_stop_days": TIME_STOP_DAYS,    # 120d time stop
    "min_hold_days": MIN_HOLD_DAYS,      # 14d before rotation can sell
    "max_sector_count": MAX_SECTOR_COUNT,
    "re_score_holdings": True,           # re-score holdings on current momentum daily
    "protect_winners": True,             # keep profitable names that leave top-N
    "bear_exposure": BEAR_EXPOSURE,      # 50% exposure in bear market
    "cost_bps": 0.0,                     # 0 = costless fills (baseline)
}


class MomentumQualityRotation(SectorScannerTop5Rotation, Strategy):
    """Top-5 momentum names with a market regime filter to cut drawdown."""

    def __init__(self, **overrides):
        super().__init__()
        # Sweep levers without editing the module. Unknown keys raise rather
        # than silently no-op, so a typo'd sweep cannot masquerade as a
        # baseline run.
        unknown = set(overrides) - set(DEFAULTS)
        if unknown:
            raise TypeError(
                f"unknown MomentumQualityRotation parameter(s): {sorted(unknown)}; "
                f"valid: {sorted(DEFAULTS)}"
            )
        self.p = {**DEFAULTS, **overrides}

    def get_name(self) -> str:
        return "Momentum Quality Rotation"

    def get_rotation_config(self) -> RotationConfig:
        return RotationConfig(
            sizing_method=self.p["sizing_method"],
            hard_stop_loss=self.p["hard_stop_loss"],
            trailing_stop=self.p["trailing_stop"],
            trailing_stop_activation=self.p["trailing_stop_activation"],
            take_profit=self.p["take_profit"],
            time_stop_days=self.p["time_stop_days"],
            min_hold_days=self.p["min_hold_days"],
            max_sector_count=self.p["max_sector_count"],
            re_score_holdings=self.p["re_score_holdings"],
            protect_winners=self.p["protect_winners"],
            bear_exposure=self.p["bear_exposure"],
            cost_bps=self.p["cost_bps"],
            exit_priority=[
                "hard_stop_loss",
                "trailing_stop",
                "take_profit",
                "time_stop",
            ],
        )

    # All signal generation, scoring, and exit logic is inherited from
    # SectorScannerTop5Rotation. The only change is the bear_exposure filter
    # in get_rotation_config(), which the adapter applies when SPY < SMA(200).
