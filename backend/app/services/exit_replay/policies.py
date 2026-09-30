"""Alternative exit policies: baseline plus one lever at a time.

`exit_priority` is left at the dataclass default (hard_stop -> trailing ->
take_profit -> time_stop), which is MQR's live order.
"""
from __future__ import annotations

import pandas as pd

from .engine import CURRENT_MQR_POLICY, OFF, ExitPolicy

FIT_END = pd.Timestamp("2023-12-31")
VAL_END = pd.Timestamp("2025-12-31")

POLICY_GRID: dict[str, ExitPolicy] = {"baseline": CURRENT_MQR_POLICY}

# ── trailing stop width ───────────────────────────────────────────────
for v in (0.08, 0.10, 0.15, 0.20, 0.25, 0.30):
    POLICY_GRID[f"trail_{v:.2f}"] = ExitPolicy(trailing_stop=v)
POLICY_GRID["trail_off"] = ExitPolicy(trailing_stop=OFF)

# ── trailing-stop activation threshold ────────────────────────────────
for v in (0.05, 0.10, 0.15, 0.20):
    POLICY_GRID[f"act_{v:.2f}"] = ExitPolicy(trailing_stop_activation=v)
POLICY_GRID["act_off"] = ExitPolicy(trailing_stop_activation=OFF)

# ── take profit ───────────────────────────────────────────────────────
for v in (0.25, 0.35, 0.75, 1.00):
    POLICY_GRID[f"tp_{v:.2f}"] = ExitPolicy(take_profit=v)
POLICY_GRID["tp_off"] = ExitPolicy(take_profit=OFF)

# ── time stop ─────────────────────────────────────────────────────────
for v in (40, 60, 90, 180):
    POLICY_GRID[f"time_{v}"] = ExitPolicy(time_stop_days=v)
POLICY_GRID["time_off"] = ExitPolicy(time_stop_days=OFF)

# ── hard stop ─────────────────────────────────────────────────────────
for v in (0.10, 0.15, 0.30):
    POLICY_GRID[f"hard_{v:.2f}"] = ExitPolicy(hard_stop_loss=v)
POLICY_GRID["hard_off"] = ExitPolicy(hard_stop_loss=OFF)
