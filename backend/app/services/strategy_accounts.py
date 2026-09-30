"""Canonical mapping of the running multi-account Alpaca strategies.

Single source of truth for which strategy runs on which paper account. Kept
separate so the Alpaca status router (alpaca.py), the Strategy Lab Library
(strategy_lab.py), and the Coach badge (coach/strategy_summary.py) all agree on
what is actually deployed and how to reach each account's live performance.

The multi-account design (see the alpaca-multi-account-strategies skill) runs
each strategy on its own Alpaca account via `alpaca_runner_by_name.py` and
`scripts/run_all_strategies.sh`. The legacy single-active `StrategyDeployment`
/ `deployments` registry only represents ONE active strategy, so it cannot be
the source of truth for a 3-account setup — this module is.
"""
from __future__ import annotations

from typing import Dict, List, Optional


class RunningStrategy:
    def __init__(
        self,
        label: str,
        module_name: str,
        class_name: str,
        prefix: str,
        file_stem: str,
        account_number: str,
    ) -> None:
        self.label = label
        self.module_name = module_name          # strategy file module (no .py)
        self.class_name = class_name            # Strategy subclass name
        self.prefix = prefix                    # Alpaca credential prefix ('' = default)
        self.file_stem = file_stem              # matches strategy_path stem for lookup
        self.account_number = account_number    # Alpaca paper account number

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "label": self.label,
            "module_name": self.module_name,
            "class_name": self.class_name,
            "prefix": self.prefix,
            "file_stem": self.file_stem,
            "account_number": self.account_number,
        }


# (label, module, class, prefix, file_stem, account_number) — in run order.
# account_number is the LIVE paper account behind each ALPACA_<prefix>_* key set
# (verified with a read-only GET /v2/account); the matching display names live in
# .env as ALPACA_<prefix>_NAME and are read by app/routers/alpaca.py.
RUNNING_STRATEGIES: List[RunningStrategy] = [
    RunningStrategy("DailyGoldenCross", "daily_golden_cross",
                    "DailyGoldenCrossRotation", "1", "daily_golden_cross", "PA3LE9Y79BU0"),
    RunningStrategy("DailyGoldenCrossRotation", "daily_golden_cross",
                    "DailyGoldenCrossRotation", "2", "daily_golden_cross", "PA33GEZZ5K7Y"),
    RunningStrategy("SectorTop5Pegy", "sector_top5_pegy",
                    "SectorTop5MomentumPEGY", "3", "sector_top5_pegy", "PA3CE4ALJ8OJ"),
]


def running_strategy_by_stem(stem: str) -> Optional[RunningStrategy]:
    """Return the running strategy whose file stem matches, else None."""
    if not stem:
        return None
    for s in RUNNING_STRATEGIES:
        if s.file_stem == stem:
            return s
    return None
