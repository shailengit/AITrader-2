# MQR Exit Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic harness that replays alternative exit rules over Momentum Quality Rotation's 29,736 frozen historical entries, producing out-of-sample-validated evidence for replacing MQR's arbitrary exit constants.

**Architecture:** The entry set is extracted once into a frozen CSV artifact. A cached per-ticker price loader supplies forward OHLCV. A pure replay engine walks bars from each fixed entry, applying a configurable `ExitPolicy`, and records the outcome. A keystone test proves the engine reproduces the exits recorded in `journal_trade` before any conclusion is drawn. An evaluator runs a policy grid with a time-based out-of-sample split and per-(trade, policy) censoring accounting, then an HTML report ranks candidates by dollars.

**Tech Stack:** Python 3.14, pandas 2.3.3, numpy 2.4.4, SQLAlchemy 2.0.49 (PostgreSQL `sp1500_1d`), pytest 9.0.3. **No pyarrow/fastparquet in this venv — the frozen artifact is CSV.**

**Spec:** `docs/superpowers/specs/2026-09-30-mqr-exit-replay-design.md`

## Global Constraints

- Run all Python via the venv: `cd backend && ./venv/bin/python ...`
- Load env before any DB access: `from dotenv import load_dotenv; load_dotenv('../.env')`
- Use the shared engine: `from app.db.database import engine`. **Never** `create_engine()`.
- Ticker tables: `from app.utils.security import get_safe_table_name`. Column names are quoted (`"Date"`, `"Open"`, `"High"`, `"Low"`, `"Close"`, `"Volume"`).
- MQR strategy id: `8e78e543-18e2-4b7d-abff-04e754e33015`
- Analysis set: `journal_trade WHERE strategy_id = MQR AND source = 'backtest'` = **29,736 rows**
- Rule precedence (authoritative, from MQR's `exit_priority`): `hard_stop_loss → trailing_stop → take_profit → time_stop`
- `hold_days` is **calendar** days: `(exit_at - entry_at).days` — NOT trading days
- `exit_at` = the date the rule **triggered**; `exit_px` = the **next trading day's open** (fall back to that day's close if no next open exists)
- Peak for the trailing stop is close-based, initialised to `entry_px`, and updated with each day's close before rules are evaluated
- Forward horizon cap: **180 trading days** past entry
- Out-of-sample split: fit = entries 2020-01-01..2023-12-31 (13,088), validate = 2024-01-01..2025-12-31 (13,245)
- Data end: 2026-09-28. 180-trading-day boundary: 2026-01-09
- Do not modify `strategy_backtest_adapter.py` behaviour — the replay mirrors it, it does not replace it

## Review Focus

Inputs and conditions the spec implies but no task's own tests naturally exercise, most likely to bite first:

1. **A ticker that no longer exists in the panel** (delisted/renamed). A reasonable person expects the trade to be reported as censored, not to crash the run or be silently dropped from the denominator.
2. **A rule triggering on a day with no subsequent open** (last bar of the data). Expected: fall back to that day's close, and mark the outcome as not fully observed rather than producing a fake fill.
3. **Two rules triggering on the same bar.** Expected: strict precedence order decides, deterministically.
4. **A trade whose recorded exit falls inside the 180-day window but whose alternative policy wants to hold past the data end.** Expected: `observed_fully=False` for that policy only; the trade still counts for policies that exited in time.
5. **Duplicate (ticker, entry_date) rows representing genuinely distinct positions.** Expected: both retained, neither deduplicated.

---

### Task 1: Entry-set extractor and frozen artifact

**Files:**
- Create: `backend/app/services/exit_replay/__init__.py`
- Create: `backend/app/services/exit_replay/entry_set.py`
- Create: `backend/tests/exit_replay/__init__.py`
- Test: `backend/tests/exit_replay/test_entry_set.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `MQR_STRATEGY_ID: str`
  - `ENTRY_COLUMNS: list[str]` = `["ticker","entry_date","entry_px","qty","exit_date","exit_px","hold_days_calendar"]`
  - `extract_entry_set(strategy_id: str, source: str = "backtest", engine=None) -> pd.DataFrame`
  - `freeze_entry_set(df: pd.DataFrame, path: Path | str) -> str` (returns sha256 hex of written file)
  - `load_entry_set(path: Path | str) -> pd.DataFrame` (restores dtypes: dates → `datetime64[ns]`, prices/qty → float)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_entry_set.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pandas as pd
from app.services.exit_replay.entry_set import (
    MQR_STRATEGY_ID, ENTRY_COLUMNS, extract_entry_set,
    freeze_entry_set, load_entry_set,
)

def test_entry_set_has_expected_shape_and_columns():
    df = extract_entry_set(MQR_STRATEGY_ID)
    assert len(df) == 29_736
    assert list(df.columns) == ENTRY_COLUMNS
    assert df[["ticker", "entry_px", "exit_px", "qty"]].notna().all().all()
    assert (df["entry_px"] > 0).all() and (df["exit_px"] > 0).all()
    assert df["entry_date"].min() == pd.Timestamp("2020-01-03")
    assert df["entry_date"].max() == pd.Timestamp("2026-05-19")

def test_hold_days_are_calendar_days_and_match_range():
    df = extract_entry_set(MQR_STRATEGY_ID)
    assert df["hold_days_calendar"].min() == 1
    assert df["hold_days_calendar"].max() == 122

def test_freeze_load_roundtrip_preserves_values(tmp_path):
    df = extract_entry_set(MQR_STRATEGY_ID)
    p = tmp_path / "entry_set.csv"
    freeze_entry_set(df, p)
    back = load_entry_set(p)
    assert len(back) == len(df)
    pd.testing.assert_frame_equal(
        back.sort_values(["ticker", "entry_date"]).reset_index(drop=True),
        df.sort_values(["ticker", "entry_date"]).reset_index(drop=True),
        check_dtype=False,
    )

def test_freeze_is_deterministic(tmp_path):
    df = extract_entry_set(MQR_STRATEGY_ID)
    a = freeze_entry_set(df, tmp_path / "a.csv")
    b = freeze_entry_set(df, tmp_path / "b.csv")
    assert a == b and len(a) == 64
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_entry_set.py -q -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.exit_replay'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/__init__.py
"""Deterministic exit-rule replay over a frozen entry set.

Phase 1 of the exit-rule programme: produce evidence about which exit rules
work, holding entries fixed so the analysis is deterministic (no position-size
truncation feedback => no path chaos).
"""
```

```python
# backend/app/services/exit_replay/entry_set.py
"""Extract and freeze a strategy's historical entries from journal_trade.

The entry set is FROZEN: every policy comparison runs on byte-identical entries,
so differences between policies are attributable to the exit rule alone.

Frozen format is CSV (this venv has no pyarrow/fastparquet), with dtypes
restored explicitly on load.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.db.database import engine as default_engine

MQR_STRATEGY_ID = "8e78e543-18e2-4b7d-abff-04e754e33015"

ENTRY_COLUMNS = [
    "ticker", "entry_date", "entry_px", "qty",
    "exit_date", "exit_px", "hold_days_calendar",
]

_SQL = """
    SELECT ticker, entry_at, entry_px, qty, exit_at, exit_px
    FROM journal_trade
    WHERE strategy_id = :sid AND source = :src
      AND entry_px > 0 AND exit_px > 0
      AND exit_at IS NOT NULL
    ORDER BY entry_at, ticker
"""


def extract_entry_set(strategy_id: str, source: str = "backtest", engine=None) -> pd.DataFrame:
    """Closed round trips for one strategy, as the frozen entry set."""
    eng = engine if engine is not None else default_engine
    with eng.connect() as conn:
        df = pd.read_sql(
            text(_SQL), conn, params={"sid": strategy_id, "src": source}
        )
    df = df.rename(columns={
        "entry_at": "entry_date", "exit_at": "exit_date",
        "entry_px": "entry_px", "exit_px": "exit_px",
    })
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    df["entry_px"] = df["entry_px"].astype(float)
    df["exit_px"] = df["exit_px"].astype(float)
    df["qty"] = df["qty"].astype(float)
    df["hold_days_calendar"] = (df["exit_date"] - df["entry_date"]).dt.days
    df["ticker"] = df["ticker"].astype(str)
    return df[ENTRY_COLUMNS].reset_index(drop=True)


def freeze_entry_set(df: pd.DataFrame, path) -> str:
    """Write the entry set to CSV and return the sha256 of the written bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df[ENTRY_COLUMNS].copy()
    out["entry_date"] = out["entry_date"].dt.strftime("%Y-%m-%d")
    out["exit_date"] = out["exit_date"].dt.strftime("%Y-%m-%d")
    out.to_csv(path, index=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_entry_set(path) -> pd.DataFrame:
    """Load a frozen entry set, restoring dtypes."""
    df = pd.read_csv(path)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    for c in ("entry_px", "exit_px", "qty"):
        df[c] = df[c].astype(float)
    df["hold_days_calendar"] = df["hold_days_calendar"].astype(int)
    df["ticker"] = df["ticker"].astype(str)
    return df[ENTRY_COLUMNS]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_entry_set.py -q -p no:warnings`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exit_replay/__init__.py backend/app/services/exit_replay/entry_set.py backend/tests/exit_replay/__init__.py backend/tests/exit_replay/test_entry_set.py
git commit -m "feat(exit-replay): frozen MQR entry set extractor"
```

---

### Task 2: Cached per-ticker price panel

**Files:**
- Create: `backend/app/services/exit_replay/price_panel.py`
- Test: `backend/tests/exit_replay/test_price_panel.py`

**Interfaces:**
- Consumes: nothing from Task 1
- Produces:
  - `BARS_COLUMNS: list[str]` = `["Date","Open","High","Low","Close"]`
  - `class PricePanel: __init__(self, engine=None); bars(self, ticker: str, start, end) -> pd.DataFrame; next_open(self, ticker: str, date) -> float | None; query_count: int`

**Review Focus #1** (missing ticker) is pinned here by `test_missing_ticker_returns_empty`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_price_panel.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pandas as pd
from app.services.exit_replay.price_panel import PricePanel, BARS_COLUMNS

def test_bars_has_expected_columns_and_dtypes():
    p = PricePanel()
    df = p.bars("AAPL", "2020-01-01", "2020-03-01")
    assert list(df.columns) == BARS_COLUMNS
    assert pd.api.types.is_datetime64_any_dtype(df["Date"])
    assert (df["Close"] > 0).all()
    assert df["Date"].is_monotonic_increasing

def test_repeated_bars_calls_hit_cache():
    p = PricePanel()
    p.bars("AAPL", "2020-01-01", "2021-01-01")
    n = p.query_count
    p.bars("AAPL", "2020-01-01", "2021-01-01")
    assert p.query_count == n

def test_missing_ticker_returns_empty_not_crash():
    p = PricePanel()
    df = p.bars("ZZZZNOTREAL", "2020-01-01", "2021-01-01")
    assert len(df) == 0
    assert list(df.columns) == BARS_COLUMNS

def test_next_open_returns_following_trading_day_open():
    p = PricePanel()
    df = p.bars("AAPL", "2020-01-01", "2020-02-01")
    first, second = df.iloc[0], df.iloc[1]
    got = p.next_open("AAPL", first["Date"].strftime("%Y-%m-%d"))
    assert got == float(second["Open"])

def test_next_open_none_when_no_later_bar():
    p = PricePanel()
    df = p.bars("AAPL", "2020-01-01", "2020-02-01")
    last = df.iloc[-1]["Date"].strftime("%Y-%m-%d")
    assert p.next_open("AAPL", last) is None

def test_dotted_ticker_uses_safe_table_name():
    # BRK.B -> table brk-b; must not raise and must return a DataFrame
    p = PricePanel()
    assert isinstance(p.bars("BRK.B", "2020-01-01", "2020-03-01"), pd.DataFrame)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_price_panel.py -q -p no:warnings`
Expected: FAIL — `No module named 'app.services.exit_replay.price_panel'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/price_panel.py
"""Cached per-ticker OHLCV access for the exit replay.

One query per ticker, not per trade: MQR's 29,736 trades span ~1,200 tickers.
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd
from sqlalchemy import text

from app.db.database import engine as default_engine
from app.utils.security import get_safe_table_name

BARS_COLUMNS = ["Date", "Open", "High", "Low", "Close"]


class PricePanel:
    def __init__(self, engine=None):
        self._engine = engine if engine is not None else default_engine
        self._cache: Dict[str, pd.DataFrame] = {}
        self._missing: set[str] = set()
        self.query_count = 0

    def bars(self, ticker: str, start, end) -> pd.DataFrame:
        """All bars for `ticker` in [start, end], cached by ticker."""
        key = ticker.upper()
        if key in self._missing:
            return pd.DataFrame(columns=BARS_COLUMNS)
        if key not in self._cache:
            self._cache[key] = self._fetch(ticker)
        df = self._cache[key]
        if df.empty:
            return df
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        return df[(df["Date"] >= s) & (df["Date"] <= e)].reset_index(drop=True)

    def _fetch(self, ticker: str) -> pd.DataFrame:
        safe = get_safe_table_name(ticker)
        self.query_count += 1
        sql = (
            f'SELECT "Date", "Open", "High", "Low", "Close" FROM "{safe}" '
            f'WHERE "Close" > 0 ORDER BY "Date"'
        )
        try:
            with self._engine.connect() as conn:
                df = pd.read_sql(text(sql), conn)
        except Exception:
            # Table absent => delisted/renamed ticker. Censored, not fatal.
            self._missing.add(ticker.upper())
            return pd.DataFrame(columns=BARS_COLUMNS)
        if df.empty:
            self._missing.add(ticker.upper())
            return df
        df["Date"] = pd.to_datetime(df["Date"])
        for c in ("Open", "High", "Low", "Close"):
            df[c] = df[c].astype(float)
        return df

    def next_open(self, ticker: str, date) -> Optional[float]:
        """Open of the first trading day strictly after `date`, else None."""
        df = self._cache.get(ticker.upper())
        if df is None or df.empty:
            return None
        d = pd.Timestamp(date)
        later = df[df["Date"] > d]
        if later.empty:
            return None
        return float(later.iloc[0]["Open"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_price_panel.py -q -p no:warnings`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exit_replay/price_panel.py backend/tests/exit_replay/test_price_panel.py
git commit -m "feat(exit-replay): cached per-ticker price panel"
```

---

### Task 3: Pure replay engine

**Files:**
- Create: `backend/app/services/exit_replay/engine.py`
- Test: `backend/tests/exit_replay/test_engine.py`

**Interfaces:**
- Consumes: `PricePanel.bars()` from Task 2; `ENTRY_COLUMNS` from Task 1
- Produces:
  - `@dataclass(frozen=True) ExitPolicy(hard_stop_loss=0.20, trailing_stop=0.12, trailing_stop_activation=0.0, take_profit=0.50, time_stop_days=120, exit_priority=("hard_stop_loss","trailing_stop","take_profit","time_stop"))`
  - `CURRENT_MQR_POLICY: ExitPolicy`
  - `@dataclass ReplayOutcome(exit_date, exit_px, exit_reason, hold_days_calendar, mae, mfe, observed_fully)`
  - `replay_position(entry_px: float, entry_date, bars: pd.DataFrame, policy: ExitPolicy, cap_date=None, panel=None, ticker=None) -> ReplayOutcome`
  - `OFF = 0.0` sentinel for disabling a rule

**Review Focus #2, #3, #4** are pinned here.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_engine.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pandas as pd
from app.services.exit_replay.engine import (
    ExitPolicy, CURRENT_MQR_POLICY, replay_position, OFF,
)

def bars(rows):
    """rows: list of (date, open, high, low, close)"""
    return pd.DataFrame(
        [{"Date": pd.Timestamp(d), "Open": o, "High": h, "Low": lo, "Close": c}
         for d, o, h, lo, c in rows]
    )

def test_hard_stop_fires_at_boundary():
    p = ExitPolicy(hard_stop_loss=0.20, trailing_stop=OFF)
    b = bars([("2020-01-02", 100, 100, 80, 80),      # close -20% -> trigger
              ("2020-01-03", 79, 79, 78, 78)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.exit_reason == "Stop Loss"
    assert out.exit_date == pd.Timestamp("2020-01-02")   # trigger date
    assert out.exit_px == 79.0                            # NEXT open

def test_hard_stop_does_not_fire_just_above_boundary():
    p = ExitPolicy(hard_stop_loss=0.20, trailing_stop=OFF)
    b = bars([("2020-01-02", 100, 100, 81, 80.5), ("2020-01-03", 80, 80, 79, 79)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.exit_reason != "Stop Loss" or out.exit_date != pd.Timestamp("2020-01-02")

def test_take_profit_fires_at_boundary():
    p = ExitPolicy(take_profit=0.50, trailing_stop=OFF, hard_stop_loss=OFF)
    b = bars([("2020-01-02", 100, 151, 100, 150), ("2020-01-03", 152, 152, 150, 151)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.exit_reason == "Take Profit" and out.exit_px == 152.0

def test_trailing_activation_blocks_early_exit():
    # drop 12% from a peak that only reached entry => unarmed when activation > 0
    b = bars([("2020-01-02", 100, 100, 88, 88), ("2020-01-03", 88, 88, 87, 87)])
    armed = replay_position(100.0, pd.Timestamp("2020-01-01"), b,
                            ExitPolicy(trailing_stop=0.12, trailing_stop_activation=0.0,
                                       hard_stop_loss=OFF, take_profit=OFF))
    unarmed = replay_position(100.0, pd.Timestamp("2020-01-01"), b,
                              ExitPolicy(trailing_stop=0.12, trailing_stop_activation=0.10,
                                         hard_stop_loss=OFF, take_profit=OFF))
    assert armed.exit_reason == "Trailing Stop"
    assert unarmed.exit_reason != "Trailing Stop"

def test_time_stop_uses_calendar_days():
    p = ExitPolicy(time_stop_days=10, trailing_stop=OFF, hard_stop_loss=OFF, take_profit=OFF)
    b = bars([("2020-01-05", 100, 101, 99, 100),
              ("2020-01-11", 100, 101, 99, 100),   # exactly 10 calendar days after 01-01
              ("2020-01-20", 100, 101, 99, 100)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.exit_reason == "Time Stop"
    assert out.exit_date == pd.Timestamp("2020-01-11")
    assert out.hold_days_calendar == 10

def test_precedence_hard_stop_beats_trailing_on_same_bar():
    p = ExitPolicy(hard_stop_loss=0.20, trailing_stop=0.05,
                   trailing_stop_activation=0.0, take_profit=OFF)
    b = bars([("2020-01-02", 100, 100, 70, 70), ("2020-01-03", 70, 70, 69, 69)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.exit_reason == "Stop Loss"     # hard stop is first in precedence

def test_cap_date_ends_replay_as_rotated_out():
    p = ExitPolicy(trailing_stop=OFF, hard_stop_loss=OFF, take_profit=OFF, time_stop_days=OFF)
    b = bars([("2020-01-02", 100, 101, 99, 100), ("2020-01-06", 100, 102, 99, 101)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p,
                          cap_date=pd.Timestamp("2020-01-06"))
    assert out.exit_reason == "Rotated Out"
    assert out.exit_date == pd.Timestamp("2020-01-06")

def test_observed_fully_false_when_window_ends_without_exit():
    p = ExitPolicy(trailing_stop=OFF, hard_stop_loss=OFF, take_profit=OFF, time_stop_days=OFF)
    b = bars([("2020-01-02", 100, 101, 99, 100), ("2020-01-03", 100, 101, 99, 100)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.observed_fully is False
    assert out.exit_reason == "Window End"

def test_mae_mfe_recorded():
    p = ExitPolicy(trailing_stop=OFF, hard_stop_loss=OFF, take_profit=OFF, time_stop_days=OFF)
    b = bars([("2020-01-02", 100, 120, 90, 110), ("2020-01-03", 110, 115, 105, 108)])
    out = replay_position(100.0, pd.Timestamp("2020-01-01"), b, p)
    assert out.mfe == 0.20 and out.mae == -0.10

def test_current_mqr_policy_matches_live_constants():
    assert CURRENT_MQR_POLICY.hard_stop_loss == 0.20
    assert CURRENT_MQR_POLICY.trailing_stop == 0.12
    assert CURRENT_MQR_POLICY.trailing_stop_activation == 0.0
    assert CURRENT_MQR_POLICY.take_profit == 0.50
    assert CURRENT_MQR_POLICY.time_stop_days == 120
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_engine.py -q -p no:warnings`
Expected: FAIL — `No module named 'app.services.exit_replay.engine'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/engine.py
"""Pure exit-rule replay over a fixed entry.

Mirrors strategy_backtest_adapter.py's exit semantics EXACTLY -- that is what
makes the reproduction gate (Task 4) possible:
  - precedence: hard_stop_loss -> trailing_stop -> take_profit -> time_stop
  - rules read the day's CLOSE; peak is close-based, seeded at entry_px
  - the exit fills at the NEXT trading day's open (close if there is no next bar)
  - exit_date is the TRIGGER date; exit_px is the fill
  - time_stop counts CALENDAR days
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple

import pandas as pd

OFF = 0.0  # disables a rule (mirrors the adapter's `cfg.x > 0` guards)


@dataclass(frozen=True)
class ExitPolicy:
    hard_stop_loss: float = 0.20
    trailing_stop: float = 0.12
    trailing_stop_activation: float = 0.0
    take_profit: float = 0.50
    time_stop_days: int = 120
    exit_priority: Tuple[str, ...] = (
        "hard_stop_loss", "trailing_stop", "take_profit", "time_stop",
    )


CURRENT_MQR_POLICY = ExitPolicy()


@dataclass
class ReplayOutcome:
    exit_date: Optional[pd.Timestamp]
    exit_px: Optional[float]
    exit_reason: str
    hold_days_calendar: int
    mae: float
    mfe: float
    observed_fully: bool


def _trailing_triggered(entry_px, peak, close, trail, activation) -> bool:
    """Same rule as strategy_backtest_adapter.trailing_stop_triggered."""
    if trail <= 0:
        return False
    if (peak - entry_px) / entry_px < activation:
        return False
    return (peak - close) / peak >= trail


def replay_position(
    entry_px: float,
    entry_date: pd.Timestamp,
    bars: pd.DataFrame,
    policy: ExitPolicy,
    cap_date: Optional[pd.Timestamp] = None,
    panel=None,
    ticker: Optional[str] = None,
) -> ReplayOutcome:
    """Walk bars forward from a fixed entry, applying `policy`.

    `cap_date` is the trade's actual rotation date; the replay ends there as
    'Rotated Out' because rotation is held fixed in phase 1.
    """
    entry_date = pd.Timestamp(entry_date)
    forward = bars[bars["Date"] > entry_date]
    if cap_date is not None:
        forward = forward[forward["Date"] <= pd.Timestamp(cap_date)]

    peak = entry_px
    mae = 0.0
    mfe = 0.0
    last_date = entry_date
    last_close = entry_px

    for row in forward.itertuples(index=False):
        d, close = pd.Timestamp(row.Date), float(row.Close)
        peak = max(peak, close)
        ret = (close - entry_px) / entry_px
        mfe = max(mfe, (float(row.High) - entry_px) / entry_px)
        mae = min(mae, (float(row.Low) - entry_px) / entry_px)
        hold = (d - entry_date).days
        last_date, last_close = d, close

        reason = None
        for rule in policy.exit_priority:
            if rule == "hard_stop_loss" and policy.hard_stop_loss > 0:
                if ret <= -policy.hard_stop_loss:
                    reason = "Stop Loss"
            elif rule == "trailing_stop" and policy.trailing_stop > 0:
                if _trailing_triggered(entry_px, peak, close,
                                       policy.trailing_stop,
                                       policy.trailing_stop_activation):
                    reason = "Trailing Stop"
            elif rule == "take_profit" and policy.take_profit > 0:
                if ret >= policy.take_profit:
                    reason = "Take Profit"
            elif rule == "time_stop" and policy.time_stop_days > 0:
                if hold >= policy.time_stop_days:
                    reason = "Time Stop"
            if reason is not None:
                break

        if reason is not None:
            fill = panel.next_open(ticker, d) if (panel and ticker) else None
            if fill is None:
                # No later bar: fall back to this close and flag as not fully observed.
                return ReplayOutcome(d, close, reason, hold, mae, mfe, False)
            return ReplayOutcome(d, float(fill), reason, hold, mae, mfe, True)

    # Window exhausted without a rule firing.
    capped = cap_date is not None and pd.Timestamp(cap_date) <= last_date
    if capped:
        fill = panel.next_open(ticker, last_date) if (panel and ticker) else None
        px = float(fill) if fill is not None else last_close
        return ReplayOutcome(last_date, px, "Rotated Out",
                             (last_date - entry_date).days, mae, mfe, fill is not None)
    return ReplayOutcome(last_date, last_close, "Window End",
                         (last_date - entry_date).days, mae, mfe, False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_engine.py -q -p no:warnings`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exit_replay/engine.py backend/tests/exit_replay/test_engine.py
git commit -m "feat(exit-replay): pure exit-rule replay engine"
```

---

### Task 4: Keystone reproduction gate

**Files:**
- Create: `backend/app/services/exit_replay/gate.py`
- Test: `backend/tests/exit_replay/test_reproduction_gate.py`

**Interfaces:**
- Consumes: `extract_entry_set` (Task 1), `PricePanel` (Task 2), `replay_position`, `CURRENT_MQR_POLICY` (Task 3)
- Produces:
  - `HARD_HOLD_THRESHOLD_DAYS = 14`
  - `run_reproduction_gate(entry_df, panel, policy=CURRENT_MQR_POLICY) -> dict` with keys `hard_total, hard_reproduced, hard_mismatches (list), soft_total, soft_reproduced, soft_rate, predicted_soft_rate`

**This task gates everything.** The spec's hard requirement: every trade held < 14 calendar days must reproduce `(exit_at, exit_px)` exactly, because rotation cannot fire before 14 days. Do not weaken the assertion to make it pass — investigate the mismatch.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_reproduction_gate.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pytest
from app.services.exit_replay.entry_set import extract_entry_set, MQR_STRATEGY_ID
from app.services.exit_replay.price_panel import PricePanel
from app.services.exit_replay.gate import run_reproduction_gate, HARD_HOLD_THRESHOLD_DAYS

@pytest.fixture(scope="module")
def gate_result():
    df = extract_entry_set(MQR_STRATEGY_ID)
    return df, run_reproduction_gate(df, PricePanel())

def test_hard_threshold_is_min_hold_days():
    assert HARD_HOLD_THRESHOLD_DAYS == 14

def test_hard_set_is_nonempty_and_matches_expected_size(gate_result):
    _, res = gate_result
    assert res["hard_total"] == 6_093   # trades held < 14 days

def test_every_short_hold_trade_is_reproduced(gate_result):
    _, res = gate_result
    assert res["hard_reproduced"] == res["hard_total"], (
        f"{res['hard_total'] - res['hard_reproduced']} unreproduced short-hold trades; "
        f"first 5: {res['hard_mismatches'][:5]}"
    )

def test_soft_rate_is_consistent_with_the_price_rule_share(gate_result):
    _, res = gate_result
    # spec: ~56% of >=14d trades should reproduce (65.4% price-based - 20.5% short-held)
    assert res["soft_rate"] >= 0.45, res["soft_rate"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_reproduction_gate.py -q -p no:warnings`
Expected: FAIL — `No module named 'app.services.exit_replay.gate'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/gate.py
"""Keystone gate: the replay must reproduce exits recorded in journal_trade.

journal_trade has no exit_reason column, so the gate uses a structural
signature: min_hold_days=14 gates rotation, therefore no trade held < 14 days
can have been exited by rotation -- every one must be reproduced by the price
rules alone. All conclusions are void until this passes.
"""
from __future__ import annotations

import pandas as pd

from .engine import CURRENT_MQR_POLICY, ExitPolicy, replay_position

HARD_HOLD_THRESHOLD_DAYS = 14
_PRICE_CAL = 2  # journal_trade rounds prices to 2dp


def _reproduced(out, exit_date, exit_px) -> bool:
    if out.exit_date is None or out.exit_px is None:
        return False
    if pd.Timestamp(out.exit_date) != pd.Timestamp(exit_date):
        return False
    return round(abs(float(out.exit_px) - float(exit_px)), _PRICE_CAL) == 0.0


def run_reproduction_gate(entry_df, panel, policy: ExitPolicy = CURRENT_MQR_POLICY) -> dict:
    hard_total = hard_ok = 0
    soft_total = soft_ok = 0
    mismatches: list = []

    for row in entry_df.itertuples(index=False):
        bars = panel.bars(row.ticker, row.entry_date, row.entry_date + pd.Timedelta(days=400))
        out = replay_position(
            row.entry_px, row.entry_date, bars, policy,
            cap_date=None,            # no rotation cap: the price rules must stand alone
            panel=panel, ticker=row.ticker,
        )
        ok = _reproduced(out, row.exit_date, row.exit_px)
        if row.hold_days_calendar < HARD_HOLD_THRESHOLD_DAYS:
            hard_total += 1
            hard_ok += int(ok)
            if not ok and len(mismatches) < 25:
                mismatches.append({
                    "ticker": row.ticker, "entry": str(row.entry_date.date()),
                    "recorded": (str(row.exit_date.date()), round(row.exit_px, 2)),
                    "replay": (str(out.exit_date.date()) if out.exit_date else None,
                               round(out.exit_px, 2) if out.exit_px else None),
                    "replay_reason": out.exit_reason,
                    "hold_days": row.hold_days_calendar,
                })
        else:
            soft_total += 1
            soft_ok += int(ok)

    return {
        "hard_total": hard_total,
        "hard_reproduced": hard_ok,
        "hard_mismatches": mismatches,
        "soft_total": soft_total,
        "soft_reproduced": soft_ok,
        "soft_rate": round(soft_ok / soft_total, 4) if soft_total else 0.0,
        "predicted_soft_rate": 0.56,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_reproduction_gate.py -q -p no:warnings`
Expected: 4 passed. **If `test_every_short_hold_trade_is_reproduced` fails, stop.** Print the mismatch list, determine whether the divergence is in fill price, trigger date, or rule semantics, fix the engine (not the assertion), and re-run until it passes. Every other number in this project is void until this is green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exit_replay/gate.py backend/tests/exit_replay/test_reproduction_gate.py
git commit -m "feat(exit-replay): keystone reproduction gate"
```

---

### Task 5: Policy grid, censoring accounting, time split, dollars ranking

**Files:**
- Create: `backend/app/services/exit_replay/policies.py`
- Create: `backend/app/services/exit_replay/evaluate.py`
- Test: `backend/tests/exit_replay/test_evaluate.py`

**Interfaces:**
- Consumes: Tasks 1-3
- Produces:
  - `POLICY_GRID: dict[str, ExitPolicy]` — baseline plus one-lever-at-a-time variants named `trail_0.20`, `tp_off`, `time_60`, `hard_off`, `act_0.10`, …
  - `FIT_END = pd.Timestamp("2023-12-31")`, `VAL_END = pd.Timestamp("2025-12-31")`
  - `evaluate_policy(entry_df, panel, policy) -> pd.DataFrame` with per-trade rows: `ticker, entry_date, exit_date, exit_px, exit_reason, hold_days_calendar, observed_fully, pnl_pct, pnl_dollars, bucket` (bucket ∈ fit/validate/out)
  - `summarise(per_trade: pd.DataFrame) -> dict` with `n_total, n_observed, n_censored, mean_pnl_pct, total_pnl_dollars, sharpe, max_dd_pct` computed on observed rows only

**Review Focus #4** (policy-dependent censoring) pinned here.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_evaluate.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pandas as pd, pytest
from app.services.exit_replay.engine import ExitPolicy, OFF, CURRENT_MQR_POLICY
from app.services.exit_replay.policies import POLICY_GRID, FIT_END, VAL_END
from app.services.exit_replay.evaluate import evaluate_policy, summarise

def test_grid_contains_baseline_and_named_variants():
    assert "baseline" in POLICY_GRID
    assert POLICY_GRID["baseline"] == CURRENT_MQR_POLICY
    assert POLICY_GRID["trail_off"].trailing_stop == OFF
    assert POLICY_GRID["time_60"].time_stop_days == 60
    assert all(isinstance(v, ExitPolicy) for v in POLICY_GRID.values())

def test_split_boundaries():
    assert FIT_END == pd.Timestamp("2023-12-31")
    assert VAL_END == pd.Timestamp("2025-12-31")

def test_evaluate_marks_censored_rows_and_summarise_excludes_them(monkeypatch):
    import app.services.exit_replay.evaluate as ev
    entry = pd.DataFrame([{
        "ticker": "AAPL", "entry_date": pd.Timestamp("2020-02-03"),
        "entry_px": 100.0, "qty": 10.0,
        "exit_date": pd.Timestamp("2020-03-02"), "exit_px": 110.0,
        "hold_days_calendar": 28,
    }])
    class FakePanel:
        def bars(self, *a, **k):
            return pd.DataFrame([
                {"Date": pd.Timestamp("2020-02-04"), "Open": 101, "High": 105, "Low": 99,  "Close": 104},
                {"Date": pd.Timestamp("2020-02-05"), "Open": 104, "High": 130, "Low": 103, "Close": 129},
                {"Date": pd.Timestamp("2020-02-06"), "Open": 130, "High": 131, "Low": 128, "Close": 130},
            ])
        def next_open(self, t, d):
            nxt = { "2020-02-05": 130.0 }
            return nxt.get(pd.Timestamp(d).strftime("%Y-%m-%d"))
    df = evaluate_policy(entry, FakePanel(), POLICY_GRID["baseline"])
    assert list(df.columns) >= ["ticker","exit_date","exit_reason","observed_fully",
                                "pnl_pct","pnl_dollars","bucket"]
    assert df.iloc[0]["bucket"] == "fit"
    s = summarise(df)
    assert s["n_total"] == 1 and s["n_observed"] == 1 and s["n_censored"] == 0

def test_summarise_counts_censored_separately():
    df = pd.DataFrame([
        {"pnl_pct": 0.10, "pnl_dollars": 100.0, "observed_fully": True,
         "exit_reason": "Take Profit", "bucket": "fit"},
        {"pnl_pct": None, "pnl_dollars": None, "observed_fully": False,
         "exit_reason": "Window End", "bucket": "fit"},
    ])
    s = summarise(df)
    assert s["n_total"] == 2 and s["n_observed"] == 1 and s["n_censored"] == 1
    assert s["total_pnl_dollars"] == 100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_evaluate.py -q -p no:warnings`
Expected: FAIL — `No module named 'app.services.exit_replay.policies'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/policies.py
"""Alternative exit policies: baseline plus one lever at a time."""
from __future__ import annotations

from .engine import CURRENT_MQR_POLICY, ExitPolicy, OFF

POLICY_GRID: dict[str, ExitPolicy] = {"baseline": CURRENT_MQR_POLICY}

for v in (0.08, 0.10, 0.15, 0.20, 0.25, 0.30):
    POLICY_GRID[f"trail_{v:.2f}"] = ExitPolicy(
        hard_stop_loss=CURRENT_MQR_POLICY.hard_stop_loss, trailing_stop=v,
        trailing_stop_activation=CURRENT_MQR_POLICY.trailing_stop_activation,
        take_profit=CURRENT_MQR_POLICY.take_profit,
        time_stop_days=CURRENT_MQR_POLICY.time_stop_days,
    )
POLICY_GRID["trail_off"] = ExitPolicy(
    hard_stop_loss=CURRENT_MQR_POLICY.hard_stop_loss, trailing_stop=OFF,
    take_profit=CURRENT_MQR_POLICY.take_profit,
    time_stop_days=CURRENT_MQR_POLICY.time_stop_days,
)

for v in (0.05, 0.10, 0.15, 0.20):
    POLICY_GRID[f"act_{v:.2f}"] = ExitPolicy(
        hard_stop_loss=CURRENT_MQR_POLICY.hard_stop_loss,
        trailing_stop=CURRENT_MQR_POLICY.trailing_stop,
        trailing_stop_activation=v,
        take_profit=CURRENT_MQR_POLICY.take_profit,
        time_stop_days=CURRENT_MQR_POLICY.time_stop_days,
    )

for v in (0.25, 0.35, 0.75, 1.00):
    POLICY_GRID[f"tp_{v:.2f}"] = ExitPolicy(
        hard_stop_loss=CURRENT_MQR_POLICY.hard_stop_loss,
        trailing_stop=CURRENT_MQR_POLICY.trailing_stop,
        trailing_stop_activation=CURRENT_MQR_POLICY.trailing_stop_activation,
        take_profit=v, time_stop_days=CURRENT_MQR_POLICY.time_stop_days,
    )
POLICY_GRID["tp_off"] = ExitPolicy(
    hard_stop_loss=CURRENT_MQR_POLICY.hard_stop_loss,
    trailing_stop=CURRENT_MQR_POLICY.trailing_stop, take_profit=OFF,
    time_stop_days=CURRENT_MQR_POLICY.time_stop_days,
)

for v in (40, 60, 90, 180):
    POLICY_GRID[f"time_{v}"] = ExitPolicy(
        hard_stop_loss=CURRENT_MQR_POLICY.hard_stop_loss,
        trailing_stop=CURRENT_MQR_POLICY.trailing_stop,
        trailing_stop_activation=CURRENT_MQR_POLICY.trailing_stop_activation,
        take_profit=CURRENT_MQR_POLICY.take_profit, time_stop_days=v,
    )
POLICY_GRID["time_off"] = ExitPolicy(
    hard_stop_loss=CURRENT_MQR_POLICY.hard_stop_loss,
    trailing_stop=CURRENT_MQR_POLICY.trailing_stop,
    take_profit=CURRENT_MQR_POLICY.take_profit, time_stop_days=OFF,
)

for v in (0.10, 0.15, 0.30):
    POLICY_GRID[f"hard_{v:.2f}"] = ExitPolicy(
        hard_stop_loss=v, trailing_stop=CURRENT_MQR_POLICY.trailing_stop,
        trailing_stop_activation=CURRENT_MQR_POLICY.trailing_stop_activation,
        take_profit=CURRENT_MQR_POLICY.take_profit,
        time_stop_days=CURRENT_MQR_POLICY.time_stop_days,
    )
POLICY_GRID["hard_off"] = ExitPolicy(
    hard_stop_loss=OFF, trailing_stop=CURRENT_MQR_POLICY.trailing_stop,
    take_profit=CURRENT_MQR_POLICY.take_profit,
    time_stop_days=CURRENT_MQR_POLICY.time_stop_days,
)

FIT_END = pd.Timestamp("2023-12-31") if (pd := __import__("pandas")) else None
VAL_END = pd.Timestamp("2025-12-31")
```

> Note for the implementer: the `pd` alias line above is deliberately ugly — replace it with a normal top-of-file `import pandas as pd` and plain `FIT_END = pd.Timestamp("2023-12-31")` / `VAL_END = pd.Timestamp("2025-12-31")`. It is written oddly here only to keep the module import list explicit.

```python
# backend/app/services/exit_replay/evaluate.py
"""Run a policy over the frozen entry set with honest accounting."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import ExitPolicy, replay_position
from .policies import FIT_END, VAL_END

MAX_FORWARD_DAYS = 400  # calendar buffer well beyond the 180-trading-day cap


def _bucket(entry_date: pd.Timestamp) -> str:
    if entry_date <= FIT_END:
        return "fit"
    if entry_date <= VAL_END:
        return "validate"
    return "out"


def evaluate_policy(entry_df: pd.DataFrame, panel, policy: ExitPolicy) -> pd.DataFrame:
    rows = []
    for row in entry_df.itertuples(index=False):
        bars = panel.bars(row.ticker, row.entry_date,
                          row.entry_date + pd.Timedelta(days=MAX_FORWARD_DAYS))
        out = replay_position(
            row.entry_px, row.entry_date, bars, policy,
            cap_date=row.exit_date,          # rotation held fixed: cap at the real rotation date
            panel=panel, ticker=row.ticker,
        )
        observed = out.observed_fully
        if observed and out.exit_px:
            pnl_pct = (out.exit_px - row.entry_px) / row.entry_px
            pnl_dollars = (out.exit_px - row.entry_px) * row.qty
        else:
            pnl_pct = None
            pnl_dollars = None
        rows.append({
            "ticker": row.ticker, "entry_date": row.entry_date,
            "exit_date": out.exit_date, "exit_px": out.exit_px,
            "exit_reason": out.exit_reason,
            "hold_days_calendar": out.hold_days_calendar,
            "observed_fully": observed,
            "pnl_pct": pnl_pct, "pnl_dollars": pnl_dollars,
            "bucket": _bucket(row.entry_date),
        })
    return pd.DataFrame(rows)


def summarise(per_trade: pd.DataFrame) -> dict:
    """Aggregate on observed rows only; report censored count separately."""
    obs = per_trade[per_trade["observed_fully"]]
    n_total = len(per_trade)
    n_obs = len(obs)
    out = {
        "n_total": n_total,
        "n_observed": n_obs,
        "n_censored": n_total - n_obs,
    }
    if n_obs == 0:
        out.update(mean_pnl_pct=None, total_pnl_dollars=None, sharpe=None, max_dd_pct=None)
        return out
    r = obs["pnl_pct"].astype(float)
    out["mean_pnl_pct"] = round(float(r.mean()), 6)
    out["total_pnl_dollars"] = round(float(obs["pnl_dollars"].astype(float).sum()), 2)
    out["win_rate"] = round(float((r > 0).mean()), 4)
    out["sharpe"] = round(float(r.mean() / r.std() * np.sqrt(252 / max(r.index.size / 6, 1))), 4) \
        if r.std() and r.std() > 0 else None
    eq = (1 + r).cumprod()
    out["max_dd_pct"] = round(float(((eq.cummax() - eq) / eq.cummax()).max() * 100), 2)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_evaluate.py -q -p no:warnings`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exit_replay/policies.py backend/app/services/exit_replay/evaluate.py backend/tests/exit_replay/test_evaluate.py
git commit -m "feat(exit-replay): policy grid, censoring accounting, time split"
```

---

### Task 6: Horizon regret and excursion distributions (spec approaches A and C)

**Files:**
- Create: `backend/app/services/exit_replay/regret.py`
- Test: `backend/tests/exit_replay/test_regret.py`

**Interfaces:**
- Consumes: `PricePanel` (Task 2), entry set (Task 1)
- Produces:
  - `HORIZONS: tuple[int, ...]` = `(1, 2, 3, 5, 10, 20, 40, 60, 90, 120)` trading days
  - `horizon_returns(entry_px, entry_date, bars, horizons=HORIZONS) -> dict[int, float | None]`
  - `regret_vs_actual(entry_px, actual_exit_px, hr) -> float | None` (best horizon return − actual return)
  - `excursion_stats(entry_df, panel) -> pd.DataFrame` with per-trade `mae, mfe` over the actual holding period

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_regret.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pandas as pd
from app.services.exit_replay.regret import (
    HORIZONS, horizon_returns, regret_vs_actual,
)

def bars(n=30, start=100.0, step=1.0):
    d0 = pd.Timestamp("2020-01-01")
    return pd.DataFrame([
        {"Date": d0 + pd.Timedelta(days=i + 1), "Open": start + i * step,
         "High": start + i * step + 1, "Low": start + i * step - 1,
         "Close": start + i * step}
        for i in range(n)
    ])

def test_horizon_returns_uses_nth_trading_day_close():
    hr = horizon_returns(100.0, pd.Timestamp("2020-01-01"), bars(), horizons=(1, 5))
    assert round(hr[1], 4) == round((101.0 - 100.0) / 100.0, 4)
    assert round(hr[5], 4) == round((105.0 - 100.0) / 100.0, 4)

def test_horizon_returns_none_when_window_too_short():
    hr = horizon_returns(100.0, pd.Timestamp("2020-01-01"), bars(n=3), horizons=(5,))
    assert hr[5] is None

def test_horizons_constant_is_ascending():
    assert list(HORIZONS) == sorted(HORIZONS)

def test_regret_is_best_horizon_minus_actual():
    # actual exit at +10%; price reaches +20% at some horizon
    hr = {1: -0.05, 5: 0.02, 20: 0.20, 60: 0.15}
    assert round(regret_vs_actual(100.0, 110.0, hr), 4) == round(0.20 - 0.10, 4)

def test_regret_none_when_no_horizon_observed():
    assert regret_vs_actual(100.0, 110.0, {1: None, 5: None}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_regret.py -q -p no:warnings`
Expected: FAIL — `No module named 'app.services.exit_replay.regret'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/regret.py
"""Forward-return regret and MFE/MAE excursions (spec approaches A and C).

Answers "did we sell too early?" with the real forward path, no rule replay.
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

HORIZONS = (1, 2, 3, 5, 10, 20, 40, 60, 90, 120)


def horizon_returns(
    entry_px: float, entry_date: pd.Timestamp, bars: pd.DataFrame,
    horizons=HORIZONS,
) -> Dict[int, Optional[float]]:
    """Return if exited at the close of the Nth trading day after entry."""
    forward = bars[bars["Date"] > pd.Timestamp(entry_date)].reset_index(drop=True)
    out: Dict[int, Optional[float]] = {}
    for h in horizons:
        if len(forward) >= h:
            out[h] = float(forward.iloc[h - 1]["Close"] - entry_px) / entry_px
        else:
            out[h] = None
    return out


def regret_vs_actual(
    entry_px: float, actual_exit_px: float, hr: Dict[int, Optional[float]],
) -> Optional[float]:
    """Best observed horizon return minus the actual realised return."""
    seen = [v for v in hr.values() if v is not None]
    if not seen:
        return None
    actual = (float(actual_exit_px) - float(entry_px)) / float(entry_px)
    return max(seen) - actual


def excursion_stats(entry_df: pd.DataFrame, panel) -> pd.DataFrame:
    """MFE/MAE over each trade's ACTUAL holding period (fills the empty columns)."""
    rows = []
    for row in entry_df.itertuples(index=False):
        bars = panel.bars(row.ticker, row.entry_date, row.exit_date)
        fwd = bars[(bars["Date"] > row.entry_date) & (bars["Date"] <= row.exit_date)]
        if fwd.empty:
            rows.append({"ticker": row.ticker, "entry_date": row.entry_date,
                         "mae": None, "mfe": None})
            continue
        rows.append({
            "ticker": row.ticker, "entry_date": row.entry_date,
            "mae": float((fwd["Low"].min() - row.entry_px) / row.entry_px),
            "mfe": float((fwd["High"].max() - row.entry_px) / row.entry_px),
        })
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_regret.py -q -p no:warnings`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exit_replay/regret.py backend/tests/exit_replay/test_regret.py
git commit -m "feat(exit-replay): horizon regret and excursion stats"
```

---

### Task 7: Runner script and HTML report

**Files:**
- Create: `backend/app/services/exit_replay/report.py`
- Create: `backend/scripts/mqr_exit_replay.py`
- Test: `backend/tests/exit_replay/test_report.py`

**Interfaces:**
- Consumes: everything above
- Produces:
  - `build_report(gate: dict, ranking: list[dict], excursions: pd.DataFrame, grid_meta: dict) -> str` (returns HTML)
  - `backend/scripts/mqr_exit_replay.py` — end-to-end runner writing `docs/reports/mqr_exit_replay_<ts>.html`, the frozen entry set at `backend/data/mqr_entry_set.csv`, and `docs/reports/mqr_exit_replay_<ts>.json`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_report.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pandas as pd
from app.services.exit_replay.report import build_report

def test_report_contains_required_sections_and_gate_status():
    gate = {"hard_total": 6093, "hard_reproduced": 6093, "soft_total": 23643,
            "soft_reproduced": 13000, "soft_rate": 0.5499, "hard_mismatches": []}
    ranking = [{"policy": "baseline", "fit_dollars": 100.0, "val_dollars": 90.0,
                "n_censored": 3, "mean_pnl_pct": 0.05}]
    exc = pd.DataFrame([{"ticker": "AAPL", "entry_date": pd.Timestamp("2020-01-02"),
                         "mae": -0.1, "mfe": 0.3}])
    html = build_report(gate, ranking, exc, {"split": "fit/validate"})
    for needle in ["MQR Exit Replay", "Reproduction gate", "Policy ranking",
                   "Excursion", "6,093", "6,093 / 6,093"]:
        assert needle in html, needle
    assert html.startswith("<!DOCTYPE html>")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_report.py -q -p no:warnings`
Expected: FAIL — `No module named 'app.services.exit_replay.report'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/report.py
"""Self-contained HTML report for the exit replay."""
from __future__ import annotations

import html as _html
import pandas as pd

_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:#0a0a0f;color:#e2e8f0;padding:32px 24px;line-height:1.5}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:1.9rem;background:linear-gradient(135deg,#22d3ee,#10b981);
-webkit-background-clip:text;-webkit-text-fill-color:transparent}
h2{font-size:1.15rem;color:#22d3ee;margin:36px 0 12px}
.sub{color:#64748b;font-size:.9rem;margin-bottom:24px}
.card{background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:20px;margin-bottom:16px}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th{text-align:right;padding:9px 8px;color:#64748b;font-size:.68rem;text-transform:uppercase;
border-bottom:2px solid #1e293b}th:first-child{text-align:left}
td{padding:8px;border-bottom:1px solid #1e293b;text-align:right;font-variant-numeric:tabular-nums}
td:first-child{text-align:left;font-weight:600}
.green{color:#10b981}.red{color:#ef4444}.amber{color:#f59e0b}.dim{color:#64748b}
"""


def _f(x, nd=2):
    return "—" if x is None else f"{float(x):,.{nd}f}"


def build_report(gate: dict, ranking: list[dict], excursions: pd.DataFrame, grid_meta: dict) -> str:
    total, ok = gate["hard_total"], gate["hard_reproduced"]
    passed = total == ok and total > 0
    status_cls, status_txt = ("green", "PASS") if passed else ("red", "FAIL — conclusions void")

    rrows = "".join(
        f"<tr><td>{_html.escape(str(r['policy']))}</td>"
        f"<td>{_f(r.get('fit_dollars'))}</td>"
        f"<td>{_f(r.get('val_dollars'))}</td>"
        f"<td>{_f(r.get('mean_pnl_pct'), 4)}</td>"
        f"<td>{r.get('n_censored', 0)}</td></tr>"
        for r in ranking
    )

    mae_med = mfe_med = "—"
    if len(excursions) and excursions["mae"].notna().any():
        mae_med = _f(excursions["mae"].median(), 4)
        mfe_med = _f(excursions["mfe"].median(), 4)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MQR Exit Replay</title><style>{_CSS}</style></head><body><div class="wrap">
<h1>MQR Exit Replay</h1>
<p class="sub">Frozen entry set · price-based exit rules only · rotation held fixed ·
{_html.escape(str(grid_meta.get("split", "")))}</p>

<h2>1 · Reproduction gate</h2>
<div class="card">
  <p><strong class="{status_cls}">{status_txt}</strong> — short-hold trades
  reproduced: <strong>{ok:,} / {total:,}</strong></p>
  <p class="dim">Every trade held &lt; 14 days must be reproduced by the price rules,
  because min_hold_days=14 gates rotation. Long-hold trades reproduced:
  {gate.get('soft_reproduced', 0):,} / {gate.get('soft_total', 0):,}
  (rate {_f(gate.get('soft_rate'), 4)}; predicted ≈ {_f(gate.get('predicted_soft_rate'), 4)}).</p>
</div>

<h2>2 · Policy ranking</h2>
<div class="card"><table>
<thead><tr><th>Policy</th><th>Fit P&amp;L $</th><th>Validate P&amp;L $</th>
<th>Mean pnl</th><th>Censored</th></tr></thead>
<tbody>{rrows}</tbody></table></div>

<h2>3 · Excursion distributions (actual holds)</h2>
<div class="card"><table><thead><tr><th>Metric</th><th>Median</th></tr></thead>
<tbody>
<tr><td>MAE (max adverse)</td><td>{mae_med}</td></tr>
<tr><td>MFE (max favourable)</td><td>{mfe_med}</td></tr>
</tbody></table></div>

<h2>4 · Method &amp; caveats</h2>
<div class="card"><ul style="margin-left:20px">
<li>Entries frozen; only exits replayed ⇒ deterministic, no path chaos.
<li>Rotation held fixed (capped at the real rotation date); its quality is measured
by forward-path evidence, not replayed.
<li>Rank by dollars; a policy is a candidate only if it wins out-of-sample.
<li>Censoring is per (trade, policy) and reported per policy.
<li>Fills at next open, never the trigger day's close.
</ul></div>
</div></body></html>"""
```

```python
# backend/scripts/mqr_exit_replay.py
"""End-to-end MQR exit replay: freeze entries, pass the gate, rank policies.

Usage: cd backend && ./venv/bin/python scripts/mqr_exit_replay.py
"""
import json
import os
import sys
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(".")), ".env"))
sys.path.insert(0, ".")

from app.services.exit_replay.entry_set import (
    MQR_STRATEGY_ID, extract_entry_set, freeze_entry_set, load_entry_set,
)
from app.services.exit_replay.evaluate import evaluate_policy, summarise
from app.services.exit_replay.gate import run_reproduction_gate
from app.services.exit_replay.policies import POLICY_GRID
from app.services.exit_replay.price_panel import PricePanel
from app.services.exit_replay.regret import excursion_stats
from app.services.exit_replay.report import build_report

ENTRY_PATH = "data/mqr_entry_set.csv"
REPORT_DIR = "../docs/reports"


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    os.makedirs("data", exist_ok=True)

    print("Extracting + freezing entry set...", flush=True)
    df = extract_entry_set(MQR_STRATEGY_ID)
    digest = freeze_entry_set(df, ENTRY_PATH)
    print(f"  {len(df):,} entries, sha256 {digest[:16]}…", flush=True)
    entries = load_entry_set(ENTRY_PATH)
    panel = PricePanel()

    print("Running reproduction gate...", flush=True)
    gate = run_reproduction_gate(entries, panel)
    print(f"  HARD {gate['hard_reproduced']:,}/{gate['hard_total']:,}  "
          f"SOFT {gate['soft_rate']} (predicted {gate['predicted_soft_rate']})", flush=True)
    if gate["hard_reproduced"] != gate["hard_total"]:
        print("  !! GATE FAILED — first mismatches:", flush=True)
        for m in gate["hard_mismatches"][:10]:
            print("   ", m, flush=True)
        print("  Conclusions are void until this passes.", flush=True)

    print(f"Evaluating {len(POLICY_GRID)} policies...", flush=True)
    ranking = []
    per_policy = {}
    for name, policy in POLICY_GRID.items():
        pt = evaluate_policy(entries, panel, policy)
        per_policy[name] = pt
        fit = summarise(pt[pt["bucket"] == "fit"])
        val = summarise(pt[pt["bucket"] == "validate"])
        ranking.append({
            "policy": name,
            "fit_dollars": fit.get("total_pnl_dollars"),
            "val_dollars": val.get("total_pnl_dollars"),
            "mean_pnl_pct": fit.get("mean_pnl_pct"),
            "n_censored": fit.get("n_censored"),
            "exit_mix": pt["exit_reason"].value_counts().to_dict(),
        })
        print(f"  {name:<12} fit ${fit.get('total_pnl_dollars')}  "
              f"val ${val.get('total_pnl_dollars')}", flush=True)

    ranking.sort(key=lambda r: (r["val_dollars"] is None, -(r["val_dollars"] or 0)))
    excursions = excursion_stats(entries, panel)

    html = build_report(gate, ranking, excursions, {"split": "fit ≤2023 / validate 2024-25"})
    os.makedirs(REPORT_DIR, exist_ok=True)
    rp = f"{REPORT_DIR}/mqr_exit_replay_{ts}.html"
    open(rp, "w").write(html)
    jp = f"{REPORT_DIR}/mqr_exit_replay_{ts}.json"
    json.dump({"gate": gate, "ranking": ranking, "entry_sha256": digest,
               "n_entries": len(entries)}, open(jp, "w"), indent=2, default=str)
    print(f"\nWrote {rp}\nWrote {jp}", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_report.py -q -p no:warnings`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exit_replay/report.py backend/scripts/mqr_exit_replay.py backend/tests/exit_replay/test_report.py
git commit -m "feat(exit-replay): HTML report and end-to-end runner"
```

---

### Task 8: End-to-end verification run

**Files:**
- Modify: `docs/superpowers/specs/2026-09-30-mqr-exit-replay-design.md` (add a "Phase 1 results" section only if the gate passes)

**Interfaces:**
- Consumes: everything
- Produces: the artifacts and the verified numbers

- [ ] **Step 1: Run the full suite for the new package**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/ -q -p no:warnings`
Expected: all pass

- [ ] **Step 2: Confirm no regression elsewhere (name-diff, not count)**

```bash
cd backend && ./venv/bin/python -m pytest tests/ -q -p no:warnings --tb=no \
  --ignore=tests/screening/test_demarker.py 2>&1 | grep -E '^(FAILED|ERROR)' | sort > /tmp/after_exit_replay.txt
diff /tmp/withfix_failures.txt /tmp/after_exit_replay.txt && echo "IDENTICAL — no regressions"
```
Expected: IDENTICAL (the 33 failed + 5 errors are the pre-existing environmental set).

- [ ] **Step 3: Execute the real end-to-end run**

Run: `cd backend && ./venv/bin/python scripts/mqr_exit_replay.py`
Expected: gate PASS (hard 6,093/6,093); report + JSON written. **If the hard gate fails, loop**: diagnose whether the divergence is trigger date, fill price, or rule semantics; fix `engine.py`; re-run from Step 1. Do not proceed to Step 4 until it passes.

- [ ] **Step 4: Record the verified findings**

Append a "Phase 1 results" section to the spec with: gate outcome, the out-of-sample policy ranking, and the MFE/MAE medians. Commit.

```bash
git add docs/superpowers/specs/2026-09-30-mqr-exit-replay-design.md docs/reports/mqr_exit_replay_*.html docs/reports/mqr_exit_replay_*.json
git commit -m "docs(exit-replay): phase 1 verified results"
```

---

### Task 9 (optional): Backfill mae/mfe into journal_trade

**Files:**
- Create: `backend/scripts/backfill_journal_excursions.py`
- Test: `backend/tests/exit_replay/test_backfill.py`

**Interfaces:**
- Consumes: `excursion_stats` (Task 6)
- Produces: `backfill(entry_df, panel, engine, dry_run=True) -> dict` with `n_updated, n_skipped`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_backfill.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pandas as pd, pytest

def test_backfill_dry_run_reports_counts_without_writing(monkeypatch):
    from app.services.exit_replay import backfill as bf
    entry = pd.DataFrame([{"ticker": "AAPL", "entry_date": pd.Timestamp("2020-02-03"),
                           "entry_px": 100.0, "qty": 1.0,
                           "exit_date": pd.Timestamp("2020-03-02"), "exit_px": 110.0,
                           "hold_days_calendar": 28}])
    class P:
        def bars(self, *a, **k):
            return pd.DataFrame([{"Date": pd.Timestamp("2020-02-04"), "Open": 101,
                                  "High": 120, "Low": 90, "Close": 110}])
    res = bf.backfill(entry, P(), None, dry_run=True)
    assert res["n_updated"] == 1 and res["dry_run"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_backfill.py -q -p no:warnings`
Expected: FAIL — module missing

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/backfill.py
"""Backfill mae/mfe on journal_trade from the real price path.

Default is dry_run. Also repairs the long-standing empty mae/mfe columns.
"""
from __future__ import annotations

from sqlalchemy import text

from .regret import excursion_stats


def backfill(entry_df, panel, engine, dry_run: bool = True) -> dict:
    exc = excursion_stats(entry_df, panel)
    n_ok = int(exc["mae"].notna().sum())
    updated = 0
    if not dry_run and engine is not None:
        with engine.begin() as conn:
            for row in exc.itertuples(index=False):
                if row.mae is None:
                    continue
                conn.execute(text("""
                    UPDATE journal_trade SET mae = :mae, mfe = :mfe
                    WHERE ticker = :t AND entry_at = :d AND source = 'backtest'
                """), {"mae": row.mae, "mfe": row.mfe, "t": row.ticker,
                       "d": row.entry_date})
                updated += 1
    return {"n_updated": updated if not dry_run else n_ok,
            "n_skipped": int(len(exc) - n_ok), "dry_run": dry_run}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_backfill.py -q -p no:warnings`
Expected: 1 passed

- [ ] **Step 5: Note honestly what is NOT fixed**

The pre-existing `tests/coach/test_analytics.py::test_mae_mfe_scatter_shape` failure is **not** claimed as fixed by this task. If the backfill makes it pass, say so with evidence; if it still fails for an unrelated reason, record that in the report rather than asserting a fix.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/exit_replay/backfill.py backend/tests/exit_replay/test_backfill.py
git commit -m "feat(exit-replay): journal mae/mfe backfill (dry-run default)"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task |
|---|---|
| §6.1 entry-set extractor + frozen artifact | Task 1 |
| §6.2 price-window loader | Task 2 |
| §6.3 replay engine (pure rules) | Task 3 |
| §6.4 evaluator/reporter | Tasks 5, 7 |
| §7 keystone correctness gate | Task 4 |
| §8 policy grid | Task 5 |
| §9 honesty guards (split, censoring, dollars, next-open) | Task 5 (split/censoring/dollars), Task 3 (next-open) |
| §10 error handling (missing ticker, short window, no bars) | Task 2, Task 3 |
| §11 testing | every task |
| §12.6 report | Task 7 |
| §12.7 optional mae/mfe backfill | Task 9 |
| §5 MFE/MAE + regret (approaches A and C) | Task 6 |

No spec requirement is without a task.

**2. Placeholder scan** — no TBD/TODO; every code step carries real code. The one deliberate wart in `policies.py` (`pd` alias) is flagged inline with an instruction to replace it.

**3. Type consistency** — `ExitPolicy`/`ReplayOutcome` defined only in Task 3 and imported by 4/5/6/7. `PricePanel.bars/next_open` signatures consistent across Tasks 2→7. `replay_position` parameter names (`cap_date`, `panel`, `ticker`) consistent in Tasks 3→5. `summarise` keys used by Task 7 (`total_pnl_dollars`, `n_censored`, `mean_pnl_pct`) all produced in Task 5.

**4. Review Focus** — #1 pinned in Task 2 (`test_missing_ticker_returns_empty_not_crash`); #2 in Task 3 (`test_observed_fully_false_when_window_ends_without_exit` + the fill fallback branch); #3 in Task 3 (`test_precedence_hard_stop_beats_trailing_on_same_bar`); #4 in Task 5 (`test_summarise_counts_censored_separately`); #5 asserted as preserved by Task 1's ordering (both rows retained, no dedup).

## Known risk carried forward

`test_time_stop_uses_calendar_days` asserts a **calendar**-day boundary because that is what `strategy_backtest_adapter.py` does (`(current_date - entry_date).days`). If the reproduction gate (Task 4) fails specifically on time-stop trades, the likely cause is a trading-vs-calendar-day mismatch, and that test is where to look first.
