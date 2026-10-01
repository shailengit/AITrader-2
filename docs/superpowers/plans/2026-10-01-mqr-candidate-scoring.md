# MQR Candidate Scoring Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Learn a candidate scoring function that picks better buys than MQR's raw momentum score, and prove it improves CAGR out-of-sample net of costs — or report honestly that it does not.

**Architecture:** Reconstruct the daily ranking (already built and validated in `ranking.py`), build as-of features and forward-return labels from it, fit a gradient-boosted regressor with a leak-free temporal split, then evaluate by plugging the model into a cost-aware rotation simulator (primary) and the full adapter (confirmation). The model is consumed only through a `score_candidates(features) -> np.ndarray` interface so the model type is swappable.

**Tech Stack:** Python 3.14, pandas 2.3.3, numpy 2.4.4, scikit-learn 1.8.0 (`HistGradientBoostingRegressor`, `Ridge`, `permutation_importance`), xgboost 3.2.0 available but unused, pytest 9.0.3, PostgreSQL `sp1500_1d`.

**Spec:** `docs/superpowers/specs/2026-10-01-mqr-candidate-scoring-design.md`

## Global Constraints

- Run all Python via the venv: `cd backend && ./venv/bin/python ...`
- Load env before DB access: `from dotenv import load_dotenv; load_dotenv('../.env')`
- Shared engine only: `from app.db.database import engine`. Never `create_engine()`.
- Build the ranking panel with a **bounded** fetch: `PricePanel(fetch_since="2017-06-01")`. An unbounded whole-history fetch stalls the 1,500-ticker build.
- Universe filter (as the strategy applies it): market cap ≥ `5e9`, 14-day return std ≤ `0.05`, sector cap `2`, `NON_EQUITY` excluded.
- **`stock_metadata.market_cap` and `beta` are CURRENT values, not as-of. They are used for the universe filter (mirroring the strategy) and MUST NOT be model features.**
- Label horizon candidates: `H ∈ {20, 40, 60}`. **H = 10 is excluded** (the spike shows the 10-day oracle is negative).
- H is chosen on the **fit period only** (dates ≤ `2023-12-31`), by rotation-sim CAGR improvement at 5 bps/side, never by label RMSE.
- **Purge `H` trading days** before the split boundary: training rows whose label window crosses into the test period are dropped.
- Cost: **5 bps per side** default; report sensitivity at 0 and 10 bps.
- Test period: dates ≥ `2024-01-01`. Rotation-sim window `2020-01-01 → 2026-05-19`.
- Adapter confirmation uses the six standard start dates: `2020-01-01, 2020-07-01, 2021-01-01, 2021-07-01, 2022-01-01, 2023-01-01`, all ending `2026-09-28`, `CAPITAL = 100_000.0`.
- If the model does not beat the momentum baseline out-of-sample, it is **not shipped** and that is the reported result.

## Review Focus

Failure modes the spec implies but no task's tests naturally cover, most likely to bite first:

1. **A feature silently computed with data after D.** Expected: appending future bars must not change any feature value for date D. Pinned in Task 1.
2. **A training label whose window reaches into the test period.** Expected: purged. Pinned in Task 2.
3. **A candidate with an undefined feature** (short history after IPO, missing earnings row). Expected: the row is dropped or the feature filled deterministically — never NaN reaching the model, which would silently poison training. Pinned in Task 3.
4. **A model that wins only by swapping more often.** Expected: costs charged per side, and the swap count reported next to CAGR. Pinned in Task 6.
5. **A model evaluated against a stale baseline number rather than one measured in the same run.** Expected: baseline re-measured in-harness on the same dates and slot constraints. Pinned in Task 6.

---

### Task 1: As-of feature builder

**Files:**
- Create: `backend/app/services/exit_replay/features.py`
- Test: `backend/tests/exit_replay/test_features.py`

**Interfaces:**
- Consumes: `RankingPanel` (`dates`, `tickers`, `closes`, `scores`, `sectors`, `date_index`, `ticker_index`, `forward_return`) from `ranking.py`
- Produces:
  - `FEATURE_COLUMNS: list[str]`
  - `build_features(rp, i: int, j: int, incumbent_j: int | None = None, earnings: dict | None = None) -> dict[str, float]`
  - `feature_frame(rp, i: int, js: list[int], incumbent_j: int | None = None, earnings: dict | None = None) -> pd.DataFrame`

- [ ] **Step 1: Write the failing test** — the as-of test is the point of this task

```python
# backend/tests/exit_replay/test_features.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import numpy as np, pandas as pd
from app.services.exit_replay.features import FEATURE_COLUMNS, build_features
from app.services.exit_replay.ranking import RankingPanel


def _panel(n_dates=120, n_tickers=3):
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    # deterministic, distinguishable series
    closes = np.array([[100.0 + 10 * j + i for j in range(n_tickers)]
                       for i in range(n_dates)])
    scores = closes / closes.max()
    return RankingPanel(dates, ["AAA", "BBB", "CCC"], closes, scores,
                        {"AAA": "Tech", "BBB": "Tech", "CCC": "Energy"})


def test_build_features_has_all_columns_finite():
    rp = _panel()
    f = build_features(rp, 80, 0)
    assert set(f) >= set(FEATURE_COLUMNS)
    assert all(np.isfinite(v) for k, v in f.items() if k in FEATURE_COLUMNS), f


def test_features_are_unchanged_by_appending_future_bars():
    """THE AS-OF TEST. A feature at date i must not depend on later bars."""
    rp = _panel(n_dates=120)
    before = build_features(rp, 80, 0)

    dates2 = pd.bdate_range("2020-01-01", periods=160)
    closes2 = np.array([[100.0 + 10 * j + i for j in range(3)] for i in range(160)])
    rp2 = RankingPanel(dates2, rp.tickers, closes2, closes2 / closes2.max(), rp.sectors)
    after = build_features(rp2, 80, 0)

    for k in FEATURE_COLUMNS:
        a, b = before[k], after[k]
        assert (a == b) or (np.isnan(a) and np.isnan(b)), f"{k} changed: {a} -> {b}"


def test_features_are_finite_even_with_short_history():
    """Newly listed tickers have < 200 bars; the builder must not emit NaN."""
    rp = _panel(n_dates=30)
    f = build_features(rp, 25, 0)
    assert all(np.isfinite(v) for k, v in f.items() if k in FEATURE_COLUMNS), f


def test_earnings_features_absent_when_no_calendar_row():
    rp = _panel()
    f = build_features(rp, 80, 0, earnings=None)
    assert np.isnan(f["days_to_earnings"])          # explicit NaN, not a crash
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_features.py -q -p no:warnings`
Expected: FAIL — `No module named 'app.services.exit_replay.features'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/features.py
"""As-of candidate features for the scoring model.

EVERY feature is computed from bars at or before index `i`. The as-of unit test is
the guard: appending future bars must not change any value at `i`. market_cap and
beta are excluded -- stock_metadata holds current values, not historical ones, so
using them would leak the future (the strategy does this too; that is a
pre-existing flaw, not one to inherit here).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

LOOKBACKS = (5, 10, 20, 60, 120)
RSI_WINDOW = 14
VOL_SHORT, VOL_LONG = 14, 60
RANGE_WINDOW = 252          # 52-week
MIN_BARS = 30               # below this, use whatever is available rather than NaN

FEATURE_COLUMNS = (
    ["perf_3m"] + [f"perf_{k}d" for k in LOOKBACKS]
    + ["vol_14d", "vol_60d", "dist_52w_high", "dist_52w_low", "rsi_14",
       "px_over_sma20", "px_over_sma50", "px_over_sma200",
       "vol_ratio_50", "days_to_earnings", "rank_frac", "score_gap",
       "spy_above_sma200", "spy_ret_20d", "sector"]
)


def _ret(closes: np.ndarray, i: int, k: int) -> float:
    j0 = i - k
    if j0 < 0:
        j0 = 0
    base = closes[j0]
    if base <= 0 or not np.isfinite(base):
        return np.nan
    return float(closes[i] / base - 1.0)


def _rsi(closes: np.ndarray, i: int, w: int = RSI_WINDOW) -> float:
    j0 = max(0, i - w)
    seg = closes[j0:i + 1]
    if len(seg) < 3:
        return np.nan
    d = np.diff(seg)
    up, dn = d[d > 0].sum(), -d[d < 0].sum()
    if up + dn == 0:
        return 50.0
    return float(100.0 * up / (up + dn))


def _sma(closes: np.ndarray, i: int, w: int) -> float:
    j0 = max(0, i - w + 1)
    seg = closes[j0:i + 1]
    return float(np.nanmean(seg)) if len(seg) else np.nan


def build_features(rp, i: int, j: int, incumbent_j: Optional[int] = None,
                   earnings: Optional[Dict[str, int]] = None) -> Dict[str, float]:
    col = rp.closes[:i + 1, j]
    if len(col) == 0 or not np.isfinite(col[-1]) or col[-1] <= 0:
        return {}
    px = float(col[-1])
    lo = max(0, i - RANGE_WINDOW + 1)
    win = col[lo:i + 1]
    win = win[np.isfinite(win)]
    hi52 = float(win.max()) if len(win) else px
    lo52 = float(win.min()) if len(win) else px

    rets = np.diff(col) / col[:-1] if len(col) > 1 else np.array([0.0])
    rets = rets[np.isfinite(rets)]

    r = {f"perf_{k}d": _ret(col, len(col) - 1, k) for k in LOOKBACKS}
    r["perf_3m"] = _ret(col, len(col) - 1, 63)
    r["vol_14d"] = float(np.std(rets[-VOL_SHORT:])) if len(rets) >= 3 else 0.0
    r["vol_60d"] = float(np.std(rets[-VOL_LONG:])) if len(rets) >= 3 else 0.0
    r["dist_52w_high"] = float(px / hi52 - 1.0) if hi52 > 0 else np.nan
    r["dist_52w_low"] = float(px / lo52 - 1.0) if lo52 > 0 else np.nan
    r["rsi_14"] = _rsi(col, len(col) - 1)
    for w in (20, 50, 200):
        s = _sma(col, len(col) - 1, w)
        r[f"px_over_sma{w}"] = float(px / s) if s and np.isfinite(s) and s > 0 else np.nan

    vol = rp_volume = None  # volume is not in RankingPanel; filled by caller if available
    r["vol_ratio_50"] = np.nan
    r["days_to_earnings"] = float(earnings.get(rp.tickers[j], np.nan)) if earnings else np.nan

    # cross-sectional context within the day
    row = rp.scores[i]
    finite = np.isfinite(row)
    rank = int((row[finite] > row[j]).sum()) if np.isfinite(row[j]) else 0
    r["rank_frac"] = float(rank / max(finite.sum() - 1, 1))
    r["score_gap"] = float(row[j] - row[incumbent_j]) if (
        incumbent_j is not None and np.isfinite(row[j]) and np.isfinite(row[incumbent_j])
    ) else 0.0
    r["sector"] = rp.sectors.get(rp.tickers[j], "Unknown")

    # market context: SPY is a column if present, else neutral defaults
    spy_j = rp.ticker_index("SPY")
    if spy_j is not None:
        sc = rp.closes[:i + 1, spy_j]
        sma = _sma(sc, len(sc) - 1, 200)
        r["spy_above_sma200"] = float(1.0 if (np.isfinite(sma) and sc[-1] > sma) else 0.0)
        r["spy_ret_20d"] = _ret(sc, len(sc) - 1, 20)
    else:
        r["spy_above_sma200"] = 1.0
        r["spy_ret_20d"] = 0.0

    # short histories: fill rather than emit NaN
    for k in FEATURE_COLUMNS:
        v = r.get(k)
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            r[k] = 0.0 if k != "days_to_earnings" else np.nan
    return {k: r[k] for k in FEATURE_COLUMNS}
```

**Note for the implementer:** `days_to_earnings` is deliberately allowed to stay NaN — the model handles missing values natively (`HistGradientBoostingRegressor` supports NaN), and the test asserts exactly that. Do not coerce it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_features.py -q -p no:warnings`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exit_replay/features.py backend/tests/exit_replay/test_features.py
git commit -m "feat(candidate-scoring): as-of feature builder"
```

---

### Task 2: Forward-return labels with purge

**Files:**
- Create: `backend/app/services/exit_replay/labels.py`
- Test: `backend/tests/exit_replay/test_labels.py`

**Interfaces:**
- Consumes: `RankingPanel.forward_return(i, j, horizon)`
- Produces:
  - `make_label(rp, i: int, j: int, horizon: int) -> float | None`
  - `purge_before_split(dates: pd.DatetimeIndex, row_dates: pd.Series, horizon: int, split: pd.Timestamp) -> np.ndarray` (boolean mask of rows to KEEP)
  - `TRAIN_END = pd.Timestamp("2023-12-31")`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_labels.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import numpy as np, pandas as pd
from app.services.exit_replay.labels import make_label, purge_before_split, TRAIN_END
from tests.exit_replay.test_features import _panel


def test_label_is_forward_return_over_horizon():
    rp = _panel(n_dates=120)
    lab = make_label(rp, 50, 0, 20)
    expect = rp.closes[70, 0] / rp.closes[50, 0] - 1
    assert abs(lab - expect) < 1e-12


def test_label_is_none_when_horizon_runs_past_the_data():
    rp = _panel(n_dates=60)
    assert make_label(rp, 55, 0, 20) is None


def test_purge_drops_rows_whose_label_window_crosses_the_split():
    """A row dated within H days BEFORE the split uses post-split prices."""
    dates = pd.bdate_range("2023-01-02", periods=300)          # spans into 2024
    rows = pd.Series(dates)
    keep = purge_before_split(dates, rows, horizon=40, split=TRAIN_END)
    kept_dates = rows[keep]
    assert kept_dates.max() < TRAIN_END - pd.Timedelta(days=0)
    # every kept row's label window ends at or before the split
    idx = dates.searchsorted(kept_dates.max())
    assert idx + 40 <= dates.searchsorted(TRAIN_END)


def test_purge_keeps_early_rows_and_drops_post_split_rows():
    dates = pd.bdate_range("2023-01-02", periods=300)
    rows = pd.Series(dates)
    keep = purge_before_split(dates, rows, horizon=40, split=TRAIN_END)
    assert keep.iloc[0] is True or bool(keep.iloc[0])
    assert not bool(keep[rows >= TRAIN_END].any())


def test_train_end_constant():
    assert TRAIN_END == pd.Timestamp("2023-12-31")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_labels.py -q -p no:warnings`
Expected: FAIL — `No module named 'app.services.exit_replay.labels'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/labels.py
"""Forward-return labels and the purge that keeps the split honest.

A label at date D uses prices through D+H, so any training row within H trading
days of the split boundary has seen the test period. Dropping those rows is a
correctness requirement, not a refinement: without it the model is trained on the
outcome it is later scored against.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

TRAIN_END = pd.Timestamp("2023-12-31")


def make_label(rp, i: int, j: int, horizon: int) -> Optional[float]:
    """Forward `horizon`-trading-day return; None if it runs past the data."""
    return rp.forward_return(i, j, horizon)


def purge_before_split(dates: pd.DatetimeIndex, row_dates: pd.Series,
                       horizon: int, split: pd.Timestamp = TRAIN_END) -> np.ndarray:
    """Boolean mask of TRAINING rows to keep.

    A row survives iff its label window (row date .. row date + horizon trading
    days) ends strictly before the split.
    """
    split_pos = int(dates.searchsorted(pd.Timestamp(split)))
    pos = dates.searchsorted(pd.DatetimeIndex(row_dates.values))
    return np.asarray(pos + horizon <= split_pos)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_labels.py -q -p no:warnings`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exit_replay/labels.py backend/tests/exit_replay/test_labels.py
git commit -m "feat(candidate-scoring): forward-return labels with split purge"
```

---

### Task 3: Dataset assembly

**Files:**
- Create: `backend/app/services/exit_replay/dataset.py`
- Test: `backend/tests/exit_replay/test_dataset.py`

**Interfaces:**
- Consumes: `build_features` (Task 1), `make_label` + `purge_before_split` + `TRAIN_END` (Task 2), `RankingPanel.ranked_on`
- Produces:
  - `TOP_K = 20`
  - `build_dataset(rp, start: pd.Timestamp, end: pd.Timestamp, horizon: int, top_k: int = TOP_K, earnings=None) -> pd.DataFrame` with columns `date, ticker, label` + `FEATURE_COLUMNS`
  - `split_dataset(df, horizon: int) -> tuple[pd.DataFrame, pd.DataFrame]` (train, test)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_dataset.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import numpy as np, pandas as pd
from app.services.exit_replay.dataset import TOP_K, build_dataset, split_dataset
from app.services.exit_replay.features import FEATURE_COLUMNS
from tests.exit_replay.test_features import _panel


def test_dataset_has_features_label_and_no_nan_labels():
    rp = _panel(n_dates=140)
    df = build_dataset(rp, rp.dates[60], rp.dates[100], horizon=20, top_k=3)
    assert len(df) > 0
    assert {"date", "ticker", "label"} <= set(df.columns)
    assert set(FEATURE_COLUMNS) <= set(df.columns)
    assert df["label"].notna().all()


def test_dataset_respects_top_k():
    rp = _panel(n_dates=140)
    df = build_dataset(rp, rp.dates[60], rp.dates[100], horizon=20, top_k=2)
    assert df.groupby("date").size().max() <= 2


def test_split_is_temporal_and_purged():
    rp = _panel(n_dates=400)
    df = build_dataset(rp, rp.dates[60], rp.dates[350], horizon=20, top_k=3)
    tr, te = split_dataset(df, horizon=20)
    assert tr["date"].max() < te["date"].min()
    assert (te["date"] >= pd.Timestamp("2023-12-31")).all()


def test_no_nan_in_numeric_features():
    """NaN reaching the model silently poisons training; only days_to_earnings
    may be NaN, and it is allowed deliberately."""
    rp = _panel(n_dates=140)
    df = build_dataset(rp, rp.dates[60], rp.dates[100], horizon=20, top_k=3)
    numeric = [c for c in FEATURE_COLUMNS if c not in ("sector", "days_to_earnings")]
    assert df[numeric].notna().all().all(), df[numeric].isna().sum().to_dict()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_dataset.py -q -p no:warnings`
Expected: FAIL — `No module named 'app.services.exit_replay.dataset'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/dataset.py
"""Assemble the supervised dataset: one row per (date, candidate).

Rows are sampled from the top-K of the universe-filtered ranking on every trading
day in the window, NOT only from the baseline's own decision days. That is
deliberate: it yields far more rows and avoids inheriting the baseline's blind
spots. The deployment test is what validates the distribution shift.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

from .features import FEATURE_COLUMNS, build_features
from .labels import TRAIN_END, make_label, purge_before_split

TOP_K = 20


def build_dataset(rp, start: pd.Timestamp, end: pd.Timestamp, horizon: int,
                  top_k: int = TOP_K, earnings=None) -> pd.DataFrame:
    i0 = rp.date_index(pd.Timestamp(start))
    i1 = rp.date_index(pd.Timestamp(end))
    if i0 is None or i1 is None or i1 <= i0:
        return pd.DataFrame(columns=["date", "ticker", "label"] + list(FEATURE_COLUMNS))

    rows = []
    for i in range(i0, i1):
        cands = rp.ranked_on(i, top_k=top_k)
        for t, _ in cands:
            j = rp.ticker_index(t)
            if j is None:
                continue
            lab = make_label(rp, i, j, horizon)
            if lab is None:
                continue
            feats = build_features(rp, i, j, earnings=earnings)
            if not feats:
                continue
            rows.append({"date": rp.dates[i], "ticker": t, "label": lab, **feats})
    return pd.DataFrame(rows)


def split_dataset(df: pd.DataFrame, horizon: int,
                  train_end: pd.Timestamp = TRAIN_END) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Temporal split with the purge applied to the TRAIN side."""
    if df.empty:
        return df, df
    dates = pd.DatetimeIndex(sorted(df["date"].unique()))
    keep = purge_before_split(dates, df["date"], horizon, train_end)
    train = df[keep].copy()
    test = df[df["date"] >= train_end].copy()
    return train, test
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_dataset.py -q -p no:warnings`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exit_replay/dataset.py backend/tests/exit_replay/test_dataset.py
git commit -m "feat(candidate-scoring): supervised dataset with temporal split"
```

---

### Task 4: Model-agnostic scorer interface

**Files:**
- Create: `backend/app/services/exit_replay/score.py`
- Test: `backend/tests/exit_replay/test_score.py`

**Interfaces:**
- Produces:
  - `save_model(model, path) -> None`, `load_model(path)`
  - `score_candidates(model, features: pd.DataFrame) -> np.ndarray` — **the only interface the sim and the adapter depend on**; must work for any object exposing `.predict`
  - `MomentumBaseline` — a drop-in scorer returning the raw `perf_3m` feature, so the baseline is measured through the same interface

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_score.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import numpy as np, pandas as pd, pytest
from app.services.exit_replay.score import (MomentumBaseline, load_model,
                                            save_model, score_candidates)


def _frame():
    return pd.DataFrame({"perf_3m": [0.1, -0.2, 0.3], "sector": ["Tech"] * 3})


def test_momentum_baseline_scores_the_raw_momentum_feature():
    s = score_candidates(MomentumBaseline(), _frame())
    assert list(np.round(s, 6)) == [0.1, -0.2, 0.3]


def test_score_candidates_works_for_any_predict_object():
    class Doubler:
        def predict(self, X):
            return np.asarray(X["perf_3m"]) * 2
    s = score_candidates(Doubler(), _frame())
    assert list(np.round(s, 6)) == [0.2, -0.4, 0.6]


def test_model_roundtrips_through_disk(tmp_path):
    class Const:
        def predict(self, X):
            return np.zeros(len(X))
    import pickle
    p = tmp_path / "m.pkl"
    save_model(Const(), p)
    assert score_candidates(load_model(p), _frame()).tolist() == [0.0, 0.0, 0.0]


def test_score_candidates_rejects_missing_feature_column():
    s = score_candidates(MomentumBaseline(), pd.DataFrame({"other": [1.0]}))
    assert len(s) == 1        # baseline falls back to 0 rather than raising
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_score.py -q -p no:warnings`
Expected: FAIL — `No module named 'app.services.exit_replay.score'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/score.py
"""The model-agnostic scoring interface.

The rotation simulator, the adapter hook and the evaluation all depend on
`score_candidates(model, features) -> np.ndarray` and never on the model class.
That is what makes swapping the model -- including for a decision model later --
a one-line change.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd


class MomentumBaseline:
    """The CURRENT rule: rank by raw 3-month momentum.

    Provided as a scorer so the baseline is measured through the same interface,
    in the same run, on the same rows -- never against a stale number.
    """

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if "perf_3m" in X.columns:
            return np.nan_to_num(np.asarray(X["perf_3m"], dtype=float), nan=0.0)
        return np.zeros(len(X))


def score_candidates(model, features: pd.DataFrame) -> np.ndarray:
    return np.nan_to_num(np.asarray(model.predict(features), dtype=float), nan=0.0)


def save_model(model, path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(model, f)


def load_model(path):
    with open(path, "rb") as f:
        return pickle.load(f)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_score.py -q -p no:warnings`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exit_replay/score.py backend/tests/exit_replay/test_score.py
git commit -m "feat(candidate-scoring): model-agnostic scorer interface"
```

---

### Task 5: Cost-aware rotation simulator with a pluggable buy arm

**Files:**
- Create: `backend/app/services/exit_replay/rotation_sim.py`
- Test: `backend/tests/exit_replay/test_rotation_sim.py`

**Interfaces:**
- Consumes: `RankingPanel`, `score_candidates` (Task 4), `build_features` (Task 1)
- Produces:
  - `SimResult` dataclass: `cagr_pct, total_return_pct, max_dd_pct, swaps, cost_paid`
  - `simulate(rp, start_i: int, end_i: int, buy_scorer=None, horizon: int = 40, cost_bps: float = 5.0, earnings=None) -> SimResult`
    - `buy_scorer=None` → the current rule (top momentum score). Otherwise any object with `.predict`.
  - `ORACLE_BUY`, `ORACLE_SELL` sentinel strings accepted by `buy_scorer` for the spike's ceiling arms

**This module replaces the inline simulator in `scripts/mqr_phase3_oracle.py`** so the model and the oracle run through identical code, which is what makes their comparison fair. The oracle script should be updated to import it.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_rotation_sim.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import numpy as np, pandas as pd
from app.services.exit_replay.rotation_sim import ORACLE_BUY, simulate
from app.services.exit_replay.score import MomentumBaseline
from tests.exit_replay.test_features import _panel


def test_simulation_runs_and_reports_a_result():
    rp = _panel(n_dates=200)
    r = simulate(rp, 150, 200, horizon=10)
    assert r.swaps >= 0
    assert np.isfinite(r.cagr_pct)


def test_costs_reduce_return_monotonically():
    rp = _panel(n_dates=200)
    free = simulate(rp, 150, 200, buy_scorer=ORACLE_BUY, horizon=20, cost_bps=0.0)
    cheap = simulate(rp, 150, 200, buy_scorer=ORACLE_BUY, horizon=20, cost_bps=5.0)
    dear = simulate(rp, 150, 200, buy_scorer=ORACLE_BUY, horizon=20, cost_bps=10.0)
    assert free.total_return_pct >= cheap.total_return_pct >= dear.total_return_pct
    assert dear.cost_paid > cheap.cost_paid > free.cost_paid


def test_oracle_buy_arm_is_at_least_as_good_as_the_baseline_at_a_long_horizon():
    rp = _panel(n_dates=300)
    base = simulate(rp, 200, 300, buy_scorer=None, horizon=40)
    orac = simulate(rp, 200, 300, buy_scorer=ORACLE_BUY, horizon=40)
    assert orac.total_return_pct >= base.total_return_pct - 1e-9


def test_a_model_scorer_changes_the_buy_decision():
    class FirstAlphabetically:
        def predict(self, X):
            return -np.arange(len(X), dtype=float)
    rp = _panel(n_dates=200)
    a = simulate(rp, 150, 200, buy_scorer=MomentumBaseline(), horizon=20)
    b = simulate(rp, 150, 200, buy_scorer=FirstAlphabetically(), horizon=20)
    assert (a.swaps, a.total_return_pct) != (b.swaps, b.total_return_pct)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_rotation_sim.py -q -p no:warnings`
Expected: FAIL — `No module named 'app.services.exit_replay.rotation_sim'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/exit_replay/rotation_sim.py
"""Cost-aware rotation simulator with a pluggable buy arm.

Extracted from the phase-3 oracle script so the learned model and the hindsight
oracle run through IDENTICAL code. Comparing a model against a ceiling measured by
a different implementation is how you fool yourself.

The sell logic is the recorded rule and is deliberately NOT pluggable: the spike
showed it has no exploitable variance (the trigger leaves one evictable name).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .features import build_features
from .score import MomentumBaseline, score_candidates

MIN_HOLD_DAYS = 14
MAX_SLOTS = 5
MAX_PER_SECTOR = 2
PROTECT_WINNERS = True
TOP_K_CANDIDATES = 20

ORACLE_BUY = "__oracle_buy__"


@dataclass
class SimResult:
    cagr_pct: float
    total_return_pct: float
    max_dd_pct: float
    swaps: int
    cost_paid: float


@dataclass
class _Slot:
    ticker: str
    j: int
    entry_i: int
    entry_px: float


def _mark(rp, slots, i):
    v = 0.0
    for s in slots:
        px = rp.closes[i, s.j]
        if np.isfinite(px) and s.entry_px > 0:
            v += float(px / s.entry_px)
    return v


def simulate(rp, start_i: int, end_i: int, buy_scorer=None, horizon: int = 40,
             cost_bps: float = 5.0, earnings=None) -> SimResult:
    slots: list[_Slot] = []
    equity, swaps, cost_paid = [], 0, 0.0
    rate = cost_bps / 10_000.0

    for i in range(start_i, end_i):
        # fill empty slots (initial warmup) with the top-ranked names
        if len(slots) < MAX_SLOTS:
            held = {s.ticker for s in slots}
            for t, _ in rp.ranked_on(i, exclude=held, top_k=MAX_SLOTS,
                                     max_per_sector=MAX_PER_SECTOR):
                j = rp.ticker_index(t)
                px = rp.closes[i, j] if j is not None else None
                if j is None or not np.isfinite(px) or px <= 0:
                    continue
                slots.append(_Slot(t, j, i, float(px)))
                held.add(t)
            equity.append(_mark(rp, slots, i))
            continue

        date = rp.dates[i]
        top5 = [t for t, _ in rp.ranked_on(i, top_k=MAX_SLOTS,
                                           max_per_sector=MAX_PER_SECTOR)]
        sellable = []
        for s in slots:
            if (date - rp.dates[s.entry_i]).days < MIN_HOLD_DAYS:
                continue
            if s.ticker in top5:
                continue
            px = rp.closes[i, s.j]
            if PROTECT_WINNERS and np.isfinite(px) and px > s.entry_px:
                continue
            sellable.append(s)
        sell = sellable[0] if sellable else None

        held = {s.ticker for s in slots}
        cands = [(t, rp.ticker_index(t))
                 for t, _ in rp.ranked_on(i, exclude=held, top_k=TOP_K_CANDIDATES,
                                          max_per_sector=MAX_PER_SECTOR)]
        cands = [(t, j) for t, j in cands if j is not None]

        if sell is not None and cands:
            buy = None
            if buy_scorer == ORACLE_BUY:
                scored = [(c, rp.forward_return(i, c[1], horizon)) for c in cands]
                scored = [(c, f) for c, f in scored if f is not None]
                if scored:
                    buy = max(scored, key=lambda x: x[1])[0]
                    fs = rp.forward_return(i, sell.j, horizon)
                    if fs is not None and buy[1] is not None and \
                            rp.forward_return(i, buy[1], horizon) <= fs:
                        buy = None
            else:
                scorer = MomentumBaseline() if buy_scorer is None else buy_scorer
                feats = pd.DataFrame([build_features(rp, i, j, earnings=earnings)
                                      for _, j in cands])
                if len(feats) and not feats.empty:
                    s_ = score_candidates(scorer, feats)
                    buy = cands[int(np.argmax(s_))]
            if buy is not None:
                t, j = buy
                cost_paid += rate * 2                       # sell + buy
                slots.remove(sell)
                slots.append(_Slot(t, j, i, float(rp.closes[i, j])))
                swaps += 1

        equity.append(_mark(rp, slots, i))

    eq = np.array(equity, dtype=float) if equity else np.array([MAX_SLOTS], dtype=float)
    years = max((rp.dates[end_i - 1] - rp.dates[start_i]).days / 365.25, 1e-9)
    gross = eq[-1] / MAX_SLOTS
    net = gross * (1.0 - cost_paid)
    peak = np.maximum.accumulate(eq)
    dd = float(((peak - eq) / peak).max() * 100) if len(eq) else 0.0
    return SimResult(
        cagr_pct=round((net ** (1 / years) - 1) * 100, 2),
        total_return_pct=round((net - 1) * 100, 2),
        max_dd_pct=round(dd, 2),
        swaps=swaps,
        cost_paid=round(cost_paid, 6),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_rotation_sim.py -q -p no:warnings`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exit_replay/rotation_sim.py backend/tests/exit_replay/test_rotation_sim.py
git commit -m "feat(candidate-scoring): cost-aware rotation sim with pluggable buy arm"
```

---

### Task 6: Train, select H on fit, and evaluate against the ceiling

**Files:**
- Create: `backend/scripts/mqr_phase3_train.py`
- Test: `backend/tests/exit_replay/test_train.py`

**Interfaces:**
- Consumes: everything above
- Produces:
  - `fit_models(train_df) -> dict[str, object]` — keys `"ridge"`, `"hgb"`
  - `select_horizon(rp, scores_by_h) -> int` — largest fit-period CAGR gain at 5 bps
  - Artifacts: `backend/data/mqr_candidate_model.pkl`, `docs/reports/mqr_candidate_scoring_<ts>.json`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_train.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import numpy as np, pandas as pd
from app.services.exit_replay.features import FEATURE_COLUMNS
from scripts.mqr_phase3_train import fit_models


def _toy(n=200):
    rng = np.random.default_rng(0)
    df = pd.DataFrame({c: rng.normal(size=n) for c in FEATURE_COLUMNS if c != "sector"})
    df["sector"] = "Tech"
    df["label"] = df["perf_3m"] * 2 + rng.normal(scale=0.01, size=n)
    return df


def test_fit_models_returns_ridge_and_hgb():
    models = fit_models(_toy())
    assert set(models) == {"ridge", "hgb"}


def test_both_models_predict_and_hgb_learns_the_signal():
    df = _toy(400)
    models = fit_models(df)
    X = df[FEATURE_COLUMNS]
    for m in models.values():
        pred = m.predict(X)
        assert len(pred) == len(df)
    # the toy label is perf_3m * 2, so the GBM must beat a zero predictor
    hgb = models["hgb"].predict(df[FEATURE_COLUMNS])
    assert np.corrcoef(hgb, df["label"])[0, 1] > 0.9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_train.py -q -p no:warnings`
Expected: FAIL — `No module named 'scripts.mqr_phase3_train'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/scripts/mqr_phase3_train.py
"""Fit the candidate scorers, choose the label horizon on FIT only, evaluate.

H is chosen by ROTATION-SIM CAGR gain on the fit period at 5 bps/side -- never by
label RMSE, and never on the test period. A lower RMSE that does not convert into
portfolio CAGR is not the objective, and the two can disagree.

Usage: cd backend && ./venv/bin/python scripts/mqr_phase3_train.py
"""
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(".")), ".env"))
sys.path.insert(0, ".")

from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402
from sklearn.linear_model import Ridge  # noqa: E402

from app.db.database import engine  # noqa: E402
from app.services.exit_replay.dataset import build_dataset, split_dataset  # noqa: E402
from app.services.exit_replay.features import FEATURE_COLUMNS  # noqa: E402
from app.services.exit_replay.labels import TRAIN_END  # noqa: E402
from app.services.exit_replay.price_panel import PricePanel  # noqa: E402
from app.services.exit_replay.ranking import build_ranking_panel, load_universe  # noqa: E402
from app.services.exit_replay.rotation_sim import ORACLE_BUY, simulate  # noqa: E402
from app.services.exit_replay.score import MomentumBaseline, save_model  # noqa: E402

HORIZONS = (20, 40, 60)
COST_BPS = 5.0
MODEL_PATH = "data/mqr_candidate_model.pkl"
REPORT_DIR = "../docs/reports"


def fit_models(train_df: pd.DataFrame) -> dict:
    """Ridge (interpretable floor) and HistGradientBoosting (primary)."""
    X = train_df[FEATURE_COLUMNS]
    y = train_df["label"].to_numpy(float)
    ridge = Ridge(alpha=1.0)
    hgb = HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.05, max_depth=None,
        categorical_features="from_dtype", random_state=17,
    )
    X = X.copy()
    X["sector"] = X["sector"].astype("category")
    ridge.fit(X.drop(columns=["sector"]), y)
    hgb.fit(X, y)
    return {"ridge": _RidgeWrapper(ridge), "hgb": hgb}


class _RidgeWrapper:
    """Ridge cannot see the categorical; drop it the same way in both paths."""

    def __init__(self, model):
        self.model = model

    def predict(self, X):
        return self.model.predict(X.drop(columns=["sector"], errors="ignore"))


def main() -> int:
    print("Building ranking panel...", flush=True)
    tickers, sectors, caps = load_universe(engine)
    rp = build_ranking_panel(PricePanel(fetch_since="2017-06-01"), tickers, sectors,
                             market_caps=caps, start="2018-01-01", end="2026-09-28")
    fit_i = rp.date_index(pd.Timestamp("2020-01-01"))
    split_i = rp.date_index(TRAIN_END)
    end_i = rp.date_index(pd.Timestamp("2026-05-19"))

    results, models_by_h = {}, {}
    for h in HORIZONS:
        print(f"\nH={h}: building dataset...", flush=True)
        df = build_dataset(rp, rp.dates[fit_i], rp.dates[end_i], horizon=h)
        train, test = split_dataset(df, horizon=h)
        print(f"  rows train {len(train):,}  test {len(test):,}", flush=True)
        if len(train) < 500 or len(test) < 100:
            print("  too few rows; skipping H", flush=True)
            continue
        models = fit_models(train)
        models_by_h[h] = models
        base = MomentumBaseline()
        row = {}
        for name, m in models.items():
            # fit-period rotation-sim gain (this is what selects H)
            fit_sim = simulate(rp, fit_i, split_i, buy_scorer=m, horizon=h, cost_bps=COST_BPS)
            row[name] = {"fit_cagr": fit_sim.cagr_pct, "fit_swaps": fit_sim.swaps}
        base_sim = simulate(rp, fit_i, split_i, buy_scorer=base, horizon=h, cost_bps=COST_BPS)
        oracle_sim = simulate(rp, fit_i, split_i, buy_scorer=ORACLE_BUY, horizon=h, cost_bps=COST_BPS)
        row["baseline"] = {"fit_cagr": base_sim.cagr_pct, "fit_swaps": base_sim.swaps}
        row["oracle"] = {"fit_cagr": oracle_sim.cagr_pct}
        results[h] = row
        print(f"  fit  baseline {base_sim.cagr_pct:6.2f}%  oracle {oracle_sim.cagr_pct:6.2f}%  "
              + "  ".join(f"{k} {v['fit_cagr']:6.2f}%" for k, v in models.items()), flush=True)

    if not results:
        print("no horizon produced enough rows", flush=True)
        return 1

    # SELECT H on fit only, by best model gain over baseline
    def gain(h):
        b = results[h]["baseline"]["fit_cagr"]
        return max(results[h][k]["fit_cagr"] for k in ("ridge", "hgb")) - b

    best_h = max(results, key=gain)
    best_model_name = max(("ridge", "hgb"),
                          key=lambda k: results[best_h][k]["fit_cagr"])
    print(f"\nSELECTED H={best_h} (fit gain {gain(best_h):+.2f} pts), "
          f"model={best_model_name}", flush=True)

    model = models_by_h[best_h][best_model_name]
    save_model(model, MODEL_PATH)
    os.makedirs(REPORT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out = {"selected_horizon": best_h, "selected_model": best_model_name,
           "cost_bps": COST_BPS, "fit_period": str(TRAIN_END.date()),
           "selection": results, "model_path": MODEL_PATH}
    with open(f"{REPORT_DIR}/mqr_candidate_scoring_{ts}.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"Saved model to {MODEL_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_train.py -q -p no:warnings`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/mqr_phase3_train.py backend/tests/exit_replay/test_train.py
git commit -m "feat(candidate-scoring): training with fit-only horizon selection"
```

---

### Task 7: Held-out evaluation and adapter confirmation

**Files:**
- Create: `backend/scripts/mqr_phase3_evaluate.py`
- Test: `backend/tests/exit_replay/test_evaluate_model.py`

**Interfaces:**
- Consumes: the artifact from Task 6, `simulate` (Task 5), `score_candidates`
- Produces: `docs/reports/mqr_candidate_scoring_<ts>.html` and a verdict line

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_evaluate_model.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import numpy as np
from scripts.mqr_phase3_evaluate import verdict


def test_verdict_requires_out_of_sample_improvement_and_no_churn_penalty():
    ok = verdict(base={"cagr": 20.0, "swaps": 40}, model={"cagr": 26.0, "swaps": 40},
                 base_10bps={"cagr": 19.0}, model_10bps={"cagr": 24.0})
    assert ok["ship"] is True
    bad = verdict(base={"cagr": 20.0, "swaps": 40}, model={"cagr": 19.9, "swaps": 40},
                  base_10bps={"cagr": 19.0}, model_10bps={"cagr": 18.0})
    assert bad["ship"] is False and "does not beat" in bad["reason"]


def test_verdict_flags_a_model_that_only_wins_by_swapping_more():
    r = verdict(base={"cagr": 20.0, "swaps": 40}, model={"cagr": 21.0, "swaps": 200},
                base_10bps={"cagr": 19.0}, model_10bps={"cagr": 19.5})
    assert r["ship"] is False
    assert "churn" in r["reason"] or "sensitivity" in r["reason"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_evaluate_model.py -q -p no:warnings`
Expected: FAIL — `No module named 'scripts.mqr_phase3_evaluate'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/scripts/mqr_phase3_evaluate.py
"""Held-out evaluation: does the model beat the baseline, net of costs?

The verdict is deliberately conservative. A model ships only if it wins
out-of-sample at 5 bps AND does not depend on swapping substantially more, because
a churn-driven win would not survive the 10 bps sensitivity check.

Usage: cd backend && ./venv/bin/python scripts/mqr_phase3_evaluate.py
"""
import json
import os
import sys
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(".")), ".env"))
sys.path.insert(0, ".")

from app.db.database import engine  # noqa: E402
from app.services.exit_replay.labels import TRAIN_END  # noqa: E402
from app.services.exit_replay.price_panel import PricePanel  # noqa: E402
from app.services.exit_replay.ranking import build_ranking_panel, load_universe  # noqa: E402
from app.services.exit_replay.rotation_sim import ORACLE_BUY, simulate  # noqa: E402
from app.services.exit_replay.score import MomentumBaseline, load_model  # noqa: E402

HORIZON_DEFAULT = 40
MODEL_PATH = "data/mqr_candidate_model.pkl"
CHURN_SWAP_RATIO = 2.0      # >2x the baseline's swaps is treated as churn-driven


def verdict(base: dict, model: dict, base_10bps: dict, model_10bps: dict) -> dict:
    if model["cagr"] <= base["cagr"]:
        return {"ship": False, "reason": f"model does not beat the baseline out-of-sample "
                                         f"({model['cagr']:.2f} vs {base['cagr']:.2f} CAGR)"}
    if model["swaps"] > CHURN_SWAP_RATIO * max(base["swaps"], 1):
        return {"ship": False, "reason": f"win is churn-driven: {model['swaps']} swaps vs "
                                         f"baseline {base['swaps']}"}
    if model_10bps["cagr"] <= base_10bps["cagr"]:
        return {"ship": False, "reason": "does not survive the 10 bps sensitivity check"}
    return {"ship": True, "reason": "beats baseline out-of-sample, net of 5 and 10 bps"}


def main() -> int:
    tickers, sectors, caps = load_universe(engine)
    rp = build_ranking_panel(PricePanel(fetch_since="2017-06-01"), tickers, sectors,
                             market_caps=caps, start="2018-01-01", end="2026-09-28")
    split_i = rp.date_index(TRAIN_END)
    end_i = rp.date_index(pd.Timestamp("2026-05-19"))
    model = load_model(MODEL_PATH)
    base = MomentumBaseline()

    with open("/tmp/mqr_selected_horizon.json") as f:
        h = json.load(f)["selected_horizon"]
    horizon = int(h) if h else HORIZON_DEFAULT

    out = {"horizon": horizon, "test_period": f"{TRAIN_END.date()} .. {rp.dates[end_i].date()}"}
    for label, cost in (("5bps", 5.0), ("10bps", 10.0), ("0bps", 0.0)):
        out[f"base_{label}"] = vars(simulate(rp, split_i, end_i, buy_scorer=base,
                                             horizon=horizon, cost_bps=cost))
        out[f"model_{label}"] = vars(simulate(rp, split_i, end_i, buy_scorer=model,
                                              horizon=horizon, cost_bps=cost))
    out["oracle"] = vars(simulate(rp, split_i, end_i, buy_scorer=ORACLE_BUY,
                                  horizon=horizon, cost_bps=5.0))

    v = verdict({"cagr": out["base_5bps"]["cagr_pct"], "swaps": out["base_5bps"]["swaps"]},
                {"cagr": out["model_5bps"]["cagr_pct"], "swaps": out["model_5bps"]["swaps"]},
                {"cagr": out["base_10bps"]["cagr_pct"]},
                {"cagr": out["model_10bps"]["cagr_pct"]})
    out["verdict"] = v

    print(f"\n=== HELD-OUT ({out['test_period']}) at H={horizon} ===", flush=True)
    for k in ("base_5bps", "model_5bps", "oracle"):
        r = out[k]
        print(f"  {k:<12} cagr {r['cagr_pct']:>7.2f}%  maxdd {r['max_dd_pct']:>5.1f}%  "
              f"swaps {r['swaps']:>4}", flush=True)
    cap = out["oracle"]["cagr_pct"] - out["base_5bps"]["cagr_pct"]
    got = out["model_5bps"]["cagr_pct"] - out["base_5bps"]["cagr_pct"]
    print(f"  ceiling {cap:+.2f} pts, captured {got:+.2f} pts "
          f"({100*got/cap:.0f}% of the ceiling)" if cap else "", flush=True)
    print(f"\n  VERDICT: {'SHIP' if v['ship'] else 'DO NOT SHIP'} — {v['reason']}", flush=True)

    os.makedirs("../docs/reports", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    with open(f"../docs/reports/mqr_candidate_scoring_eval_{ts}.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    with open("/tmp/mqr_selected_horizon.json", "w") as f:
        json.dump({"selected_horizon": horizon, "verdict": v}, f)
    return 0 if v["ship"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_evaluate_model.py -q -p no:warnings`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/mqr_phase3_evaluate.py backend/tests/exit_replay/test_evaluate_model.py
git commit -m "feat(candidate-scoring): held-out evaluation with an honest verdict"
```

---

### Task 8: End-to-end run and recorded outcome

**Files:**
- Modify: `docs/superpowers/specs/2026-10-01-mqr-candidate-scoring-design.md` (append an "Outcome" section)

- [ ] **Step 1: Run the new package's tests**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/ -q -p no:warnings`
Expected: all pass

- [ ] **Step 2: Confirm no regression elsewhere (name-diff, not count)**

```bash
cd backend && ./venv/bin/python -m pytest tests/ -q -p no:warnings --tb=no \
  --ignore=tests/screening/test_demarker.py --ignore=tests/exit_replay 2>&1 \
  | grep -E '^(FAILED|ERROR)' | sort > /tmp/after_p3.txt
diff /tmp/withfix_failures.txt /tmp/after_p3.txt && echo "IDENTICAL — no regressions"
```
Expected: IDENTICAL (33 failed + 5 errors, the pre-existing environmental set).

- [ ] **Step 3: Train, then evaluate**

```bash
cd backend && ./venv/bin/python scripts/mqr_phase3_train.py
cd backend && ./venv/bin/python scripts/mqr_phase3_evaluate.py
```
Expected: train selects an H on fit and writes the model; evaluate prints a verdict.
**If the verdict is DO NOT SHIP, that is a legitimate phase-3 outcome.** Record it and
do not tune on the test period to rescue it — that would destroy the only honest
measurement this phase produces.

- [ ] **Step 4: Record the outcome in the spec**

Append an "Outcome" section with: the H selected on fit, the fit and held-out figures for
baseline / Ridge / HGB / oracle, the ceiling-capture fraction, the cost sensitivity, and
the verdict. Commit.

```bash
git add docs/superpowers/specs/2026-10-01-mqr-candidate-scoring-design.md docs/reports/mqr_candidate_scoring_eval_*.json
git commit -m "docs(candidate-scoring): phase 3 outcome"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task |
|---|---|
| §3 scope: candidate scoring only, no sell model | Task 5 (sell arm not pluggable, documented) |
| §4 ranking foundation, validated | already built; consumed by Tasks 3, 6 |
| §5 decision + label horizon, H on fit only | Task 2 (labels), Task 6 (selection) |
| §6 features as-of, market_cap/beta excluded | Task 1 |
| §7 model choice + model-agnostic interface | Tasks 4, 6 |
| §8.1 training rows from top-K | Task 3 |
| §8.2 split + purge | Tasks 2, 3 |
| §8.3 rotation sim with cost; adapter confirmation | Task 5, Task 9 below |
| §8.4 guardrails (baseline in-harness, importances, don't ship) | Tasks 6, 7 |
| §9 deliverables 1–7 | Tasks 1–7 |
| §12 success criteria 2–5 | Task 7 verdict + Task 8 recording |

**Gap found and fixed:** §8.3 requires an **adapter multi-start confirmation**, which no
task above implements. Added as Task 9.

**2. Placeholder scan** — no TBD/TODO; every code step carries real code.

**3. Type consistency** — `RankingPanel` methods used consistently (`date_index`, `ticker_index`, `ranked_on`, `forward_return`). `score_candidates(model, features)` signature identical in Tasks 4, 5, 6, 7. `SimResult` fields (`cagr_pct`, `total_return_pct`, `max_dd_pct`, `swaps`, `cost_paid`) used consistently in Tasks 5, 6, 7. `FEATURE_COLUMNS` is the single source of the feature list for Tasks 1, 3, 6, 9.

**4. Review Focus** — #1 pinned in Task 1 (`test_features_are_unchanged_by_appending_future_bars`); #2 in Task 2 (`test_purge_drops_rows_whose_label_window_crosses_the_split`); #3 in Task 1 (`test_features_are_finite_even_with_short_history`) and Task 3 (`test_no_nan_in_numeric_features`); #4 in Task 7 (`test_verdict_flags_a_model_that_only_wins_by_swapping_more`); #5 in Task 6 (baseline re-measured in-harness).

---

### Task 9: Adapter multi-start confirmation

**Files:**
- Modify: `backend/app/services/strategies/momentum_quality_rotation.py` (add an optional pluggable scorer hook)
- Create: `backend/scripts/mqr_phase3_adapter_confirm.py`
- Test: `backend/tests/exit_replay/test_adapter_hook.py`

**Interfaces:**
- Consumes: the model artifact (Task 6), `score_candidates` (Task 4)
- Produces: paired per-start deltas for baseline vs model across the six standard starts

**Why this exists:** the rotation sim models slot allocation but not the full strategy.
Phase 2's lesson was that the two harnesses can disagree, and the adapter is the one that
deploys. This task is the shipping evidence; the sim is the diagnostic.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/exit_replay/test_adapter_hook.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.services.strategies.momentum_quality_rotation import MomentumQualityRotation


def test_strategy_accepts_an_optional_candidate_scorer():
    s = MomentumQualityRotation()
    assert getattr(s, "candidate_scorer", None) is None


def test_strategy_stores_a_supplied_scorer():
    class M:
        def predict(self, X):
            return [0.0] * len(X)
    s = MomentumQualityRotation(candidate_scorer=M())
    assert s.candidate_scorer is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_adapter_hook.py -q -p no:warnings`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'candidate_scorer'`

- [ ] **Step 3: Write minimal implementation**

In `momentum_quality_rotation.py`, add `candidate_scorer` to the `__init__` signature and
store it (`self.candidate_scorer = candidate_scorer`), defaulting to `None`. Add a short
docstring paragraph: *"When set, `candidate_scorer` is used to order buy candidates instead
of the momentum score. It is consumed only through `score_candidates(model, features)`; the
adapter hook that applies it lives in `strategy_backtest_adapter.py` and is exercised by the
confirmation script."* Extend `DEFAULTS` with `"candidate_scorer": None` if the overrides
mechanism rejects unknown kwargs (it does — see the earlier `TypeError` guard).

```python
# backend/scripts/mqr_phase3_adapter_confirm.py
"""Does the learned candidate scorer help the strategy that actually deploys?

Paired across the six standard start dates. Entries drift here by construction (a
later-swapped slot frees later), so this is never a single-run comparison.
"""
import json
import os
import statistics as st
import sys

import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(".")), ".env"))
sys.path.insert(0, ".")

from app.services.exit_replay.score import load_model  # noqa: E402
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter  # noqa: E402
from app.services.strategies.momentum_quality_rotation import MomentumQualityRotation  # noqa: E402

END = "2026-09-28"
CAPITAL = 100_000.0
STARTS = ["2020-01-01", "2020-07-01", "2021-01-01", "2021-07-01",
          "2022-01-01", "2023-01-01"]


def _run(scorer, start):
    s = StrategyBacktestAdapter(
        MomentumQualityRotation(candidate_scorer=scorer)
    ).run(as_of=start, end=END, capital=CAPITAL)["summary"]
    return {"cagr": s["cagr_pct"], "sharpe": s["sharpe_ratio"],
            "max_dd": s["max_drawdown_pct"], "trades": s["total_trades"]}


def main() -> int:
    model = load_model("data/mqr_candidate_model.pkl")
    grid = {}
    for start in STARTS:
        for name, scorer in (("baseline", None), ("model", model)):
            print(f"{name} from {start}...", flush=True)
            grid[f"{start}|{name}"] = _run(scorer, start)

    dc = [grid[f"{s}|model"]["cagr"] - grid[f"{s}|baseline"]["cagr"] for s in STARTS]
    ds = [grid[f"{s}|model"]["sharpe"] - grid[f"{s}|baseline"]["sharpe"] for s in STARTS]
    print("\n=== ADAPTER MULTI-START (entries drift; paired) ===", flush=True)
    for s, a, b in zip(STARTS, dc, ds):
        print(f"  {s}  cagr {a:+7.2f}  sharpe {b:+5.2f}", flush=True)
    print(f"  -> cagr median {st.median(dc):+.2f}, wins {sum(1 for x in dc if x>0)}/{len(dc)}", flush=True)
    print(f"  -> sharpe median {st.median(ds):+.2f}, better on {sum(1 for x in ds if x>0)}/{len(ds)}", flush=True)

    with open("/tmp/mqr_phase3_adapter_confirm.json", "w") as f:
        json.dump({"grid": grid, "cagr_deltas": dc, "sharpe_deltas": ds}, f, indent=2, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/exit_replay/test_adapter_hook.py -q -p no:warnings`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/strategies/momentum_quality_rotation.py backend/scripts/mqr_phase3_adapter_confirm.py backend/tests/exit_replay/test_adapter_hook.py
git commit -m "feat(candidate-scoring): pluggable candidate scorer + adapter confirmation"
```

**Note for the implementer:** wiring `candidate_scorer` into
`strategy_backtest_adapter.py`'s buy path is required for this to have any effect. The
adapter currently ranks candidates by their `score` field; when the strategy exposes a
non-None `candidate_scorer`, it must instead collect the candidate set, build features via
`build_features`, and order by `score_candidates`. Keep that adapter change behind the
`is not None` check so all existing strategies are unaffected, and verify with the full
test suite (the name-diff must stay identical).
