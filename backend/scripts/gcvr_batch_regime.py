"""Run Golden Cross Volume Rotation N times with random start dates and
generate an interactive HTML run-viewer report (strategy-crafter Phase 5 format).

For each run, the SPY JumpModel regime (BULL/BEAR + bull_probability) at the
start date is computed and attached to the run, so the report can show how
start-date market regime affects strategy performance.

The universe is precomputed ONCE for the full range and reused across all runs
(only the start date varies), so N runs cost ~1 precompute + N cheap sims.
"""
import json
import random
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

# Ensure `app` is importable when run as a plain script (cwd is backend/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from app.db.database import engine as db_engine
from app.services.strategies.golden_cross_volume_rotation import GoldenCrossVolumeRotation
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.run_viewer_generator import generate_run_viewer
from app.services.markov.regime_model import JumpModel
from app.services.markov.feature_engineering import compute_etf_features

START_MIN = "2010-01-01"
START_MAX = "2024-01-01"   # cap so every run has >= ~2.5y of data
END = "2026-09-04"
N_RUNS = 100
CAPITAL = 100_000.0
SEED = 42
REGIME_LOOKBACK_YEARS = 3   # train JumpModel on 3y of SPY data up to start date


def _random_date(min_date: str, max_date: str) -> str:
    start = datetime.strptime(min_date, "%Y-%m-%d")
    end = datetime.strptime(max_date, "%Y-%m-%d")
    delta_days = (end - start).days
    return (start + timedelta(days=random.randint(0, delta_days))).strftime("%Y-%m-%d")


def _downsample(equity_curve, max_points: int = 500):
    if len(equity_curve) <= max_points:
        return equity_curve
    n = len(equity_curve)
    step = n / (max_points - 2)
    indices = [0] + [min(int(i * step), n - 1) for i in range(1, max_points - 1)] + [n - 1]
    return [equity_curve[i] for i in sorted(set(indices))]


def _spy_regime_at(start_date: str) -> dict:
    """Train a SPY JumpModel on REGIME_LOOKBACK_YEARS of data up to start_date
    and return the regime state at start_date."""
    start = (datetime.strptime(start_date, "%Y-%m-%d")
             - timedelta(days=int(365.25 * REGIME_LOOKBACK_YEARS + 35))).strftime("%Y-%m-%d")
    feats = compute_etf_features("SPY", start, start_date)
    if feats is None or len(feats) < 60:
        return {"regime": "UNKNOWN", "bull_probability": 0.5, "vol_regime": "UNKNOWN"}
    model = JumpModel("SPY")
    if not model.train(feats):
        return {"regime": "UNKNOWN", "bull_probability": 0.5, "vol_regime": "UNKNOWN"}
    r = model.get_regime(start_date)
    return {
        "regime": r["regime"],
        "bull_probability": r["bull_probability"],
        "vol_regime": r["vol_regime"],
    }


def main() -> int:
    random.seed(SEED)
    strategy = GoldenCrossVolumeRotation()

    # ── 1. Full trading calendar from SPY ───────────────────────────────
    with db_engine.connect() as conn:
        spy_dates = pd.read_sql(
            f'SELECT "Date" FROM spy '
            f'WHERE "Date" >= \'{START_MIN}\' AND "Date" <= \'{END}\' '
            f'ORDER BY "Date"',
            conn,
        )
    full_dates = [str(d)[:10] for d in spy_dates["Date"]]
    print(f"Full calendar: {len(full_dates)} trading days ({START_MIN} -> {END})", flush=True)

    # ── 2. Precompute signals + price cache ONCE ────────────────────────
    print("Precomputing signals for full range (one-time)...", flush=True)
    full_signals = strategy.precompute_signals(full_dates, db_engine)
    price_cache = strategy.get_precomputed_price_cache()
    n_dates_with = sum(1 for v in full_signals.values() if v)
    print(f"Precomputed: {n_dates_with}/{len(full_dates)} dates have candidates", flush=True)

    # ── 3. Run N backtests with random start dates ──────────────────────
    start_dates = [_random_date(START_MIN, START_MAX) for _ in range(N_RUNS)]
    experiments = []
    adapter = StrategyBacktestAdapter(strategy)

    for i, start in enumerate(start_dates):
        run_dates = [d for d in full_dates if d >= start]
        run_signals = {d: full_signals[d] for d in run_dates if d in full_signals}
        try:
            result = adapter.run(
                as_of=start,
                end=END,
                capital=CAPITAL,
                precomputed_signals=run_signals,
                price_cache=price_cache,
            )
            summary = result["summary"]
            equity = _downsample(result.get("daily_equity", []))
            regime = _spy_regime_at(start)
            experiments.append({
                "run_index": i + 1,
                "status": "completed",
                "kpis": summary,
                "equity_curve": equity,
                "start_date": start,
                "end_date": END,
                "regime": regime,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            print(f"  run {i+1:3d}/{N_RUNS} start={start} regime={regime['regime']} "
                  f"ret={summary.get('total_return_pct', 0):8.1f}% "
                  f"cagr={summary.get('cagr_pct', 0):6.1f}% "
                  f"trades={summary.get('total_trades', 0):4d}", flush=True)
        except Exception as e:
            import traceback
            experiments.append({
                "run_index": i + 1,
                "status": "failed",
                "error_message": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                "start_date": start,
                "end_date": END,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            print(f"  run {i+1:3d}/{N_RUNS} start={start} FAILED: {e}", flush=True)

    # ── 4. Generate HTML report ────────────────────────────────────────
    n_ok = sum(1 for e in experiments if e["status"] == "completed")
    print(f"\nCompleted {n_ok}/{N_RUNS} runs. Generating report...", flush=True)

    params = {
        "Strategy": strategy.get_name(),
        "Runs": N_RUNS,
        "Start range": f"{START_MIN} .. {START_MAX} (random)",
        "End": END,
        "Capital": CAPITAL,
        "Crossover": "EMA10/EMA200",
        "Volume": "1.0x cross-day over 50d avg",
        "Max holdings": strategy.max_holdings,
        "Hold rank": 10,
        "Min hold days": 10,
        "Hard stop": "10%",
        "Trailing stop": "20%",
        "Take profit": "25%",
        "Time stop": "90d",
        "Sector cap": 2,
        "Vol filter": "<=5%",
        "Regime": "SPY JumpModel at start date",
        "Seed": SEED,
    }
    strategy_src = (
        Path(__file__).resolve().parent.parent
        / "app" / "services" / "strategies" / "golden_cross_volume_rotation.py"
    ).read_text()
    filepath = generate_run_viewer(
        experiments,
        strategy_name=strategy.get_name(),
        strategy_code=strategy_src,
        strategy_params=params,
        batch_id="gcvr-100runs-regime",
    )
    print(f"\nReport: {filepath}", flush=True)

    # ── 5. Save regime-vs-performance analysis ──────────────────────────
    analysis = []
    for e in experiments:
        if e["status"] != "completed":
            continue
        k = e["kpis"]
        analysis.append({
            "start_date": e["start_date"],
            "regime": e["regime"]["regime"],
            "bull_probability": e["regime"]["bull_probability"],
            "vol_regime": e["regime"]["vol_regime"],
            "return_pct": k.get("total_return_pct", 0),
            "cagr_pct": k.get("cagr_pct", 0),
            "alpha_pct": k.get("alpha_pct", 0),
            "sharpe": k.get("sharpe_ratio", 0),
            "max_dd_pct": k.get("max_drawdown_pct", 0),
            "trades": k.get("total_trades", 0),
        })
    with open("/tmp/gcvr_regime_analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    print("Regime analysis saved to /tmp/gcvr_regime_analysis.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
