"""Low-run test: enrich GCVR trades with per-ticker XGBoost predictions.

For each run, every BUY/SELL trade is enriched with the ticker's XGBoost
BUY/HOLD/SELL prediction + conviction, computed from the ticker's OWN features
using data only up to the trade date (NO SPY for market regime).

Per-run aggregates (the "regime proxy" from XGBoost breadth):
  - pct_buy_signal:  % of BUY trades where XGBoost said BUY
  - mean_buy_conv:   mean conviction of BUY-signal trades
  - pct_hold_signal: % of BUY trades where XGBoost said HOLD
  - pct_sell_signal: % of BUY trades where XGBoost said SELL
  - mean_conv_all:   mean conviction across all BUY trades

These are correlated with run performance to see if XGBoost breadth at
buy-time predicts outcomes.

Run with a LOW number of runs first to validate the workflow.
"""
import os, sys, json, random, warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from app.db.database import engine as db_engine
from app.services.strategies.golden_cross_volume_rotation import GoldenCrossVolumeRotation
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.markov.pattern_recognizer import XGBoostRecognizer
from app.services.markov.feature_engineering import compute_ticker_features

START_MIN = "2018-01-01"   # only 2018+ so every run has full data (post-fix)
START_MAX = "2024-01-01"
END = "2026-09-04"
N_RUNS = 100                 # full batch for statistical significance
CAPITAL = 100_000.0
SEED = 42
FEAT_LOOKBACK_YEARS = 1     # 1y of features up to trade date (matches XGBoost training)


def _random_date(min_date, max_date):
    start = datetime.strptime(min_date, "%Y-%m-%d")
    end = datetime.strptime(max_date, "%Y-%m-%d")
    delta = (end - start).days
    return (start + timedelta(days=random.randint(0, delta))).strftime("%Y-%m-%d")


# Cache: (ticker, date) -> prediction dict
_pred_cache = {}
_rec_cache = {}

def _xgb_predict(ticker, date):
    """XGBoost prediction for a ticker using features up to `date`."""
    key = (ticker.upper(), date)
    if key in _pred_cache:
        return _pred_cache[key]
    rec = _rec_cache.get(ticker.upper())
    if rec is None:
        rec = XGBoostRecognizer(ticker.upper())
        if not rec.load():
            _pred_cache[key] = None
            return None
        _rec_cache[ticker.upper()] = rec
    start = (datetime.strptime(date, "%Y-%m-%d")
             - timedelta(days=int(365.25 * FEAT_LOOKBACK_YEARS + 35))).strftime("%Y-%m-%d")
    feat = compute_ticker_features(ticker.upper(), start, date, min_rows=1)
    if feat is None or feat['features'].empty:
        _pred_cache[key] = None
        return None
    pred = rec.predict(feat['features'].iloc[-1])
    _pred_cache[key] = pred
    return pred


def main():
    random.seed(SEED)
    strategy = GoldenCrossVolumeRotation()

    # Full calendar
    import pandas as pd
    with db_engine.connect() as conn:
        spy = pd.read_sql(f'SELECT "Date" FROM spy WHERE "Date">=\'{START_MIN}\' AND "Date"<=\'{END}\' ORDER BY "Date"', conn)
    full_dates = [str(d)[:10] for d in spy["Date"]]

    # Precompute once
    print("Precomputing signals...", flush=True)
    full_signals = strategy.precompute_signals(full_dates, db_engine)
    price_cache = strategy.get_precomputed_price_cache()

    start_dates = [_random_date(START_MIN, START_MAX) for _ in range(N_RUNS)]
    adapter = StrategyBacktestAdapter(strategy)
    runs = []

    for i, start in enumerate(start_dates):
        run_dates = [d for d in full_dates if d >= start]
        run_signals = {d: full_signals[d] for d in run_dates if d in full_signals}
        result = adapter.run(as_of=start, end=END, capital=CAPITAL,
                             precomputed_signals=run_signals, price_cache=price_cache)
        summary = result["summary"]
        trades = result["trades"]

        # Enrich BUY trades with XGBoost prediction at buy date
        buy_preds = []
        for t in trades:
            if t["side"] != "BUY":
                continue
            pred = _xgb_predict(t["ticker"], t["entry_date"])
            if pred is not None:
                buy_preds.append({"ticker": t["ticker"], "date": t["entry_date"],
                                  "signal": pred["signal"], "conviction": pred["conviction"]})

        n = len(buy_preds)
        pct_buy = 100 * sum(1 for p in buy_preds if p["signal"] == "BUY") / n if n else 0
        pct_hold = 100 * sum(1 for p in buy_preds if p["signal"] == "HOLD") / n if n else 0
        pct_sell = 100 * sum(1 for p in buy_preds if p["signal"] == "SELL") / n if n else 0
        buy_conv = [p["conviction"] for p in buy_preds if p["signal"] == "BUY"]
        mean_buy_conv = sum(buy_conv) / len(buy_conv) if buy_conv else 0
        mean_conv_all = sum(p["conviction"] for p in buy_preds) / n if n else 0

        runs.append({
            "start_date": start,
            "return_pct": summary["total_return_pct"],
            "cagr_pct": summary["cagr_pct"],
            "alpha_pct": summary["alpha_pct"],
            "sharpe": summary["sharpe_ratio"],
            "n_buys": n,
            "pct_buy_signal": round(pct_buy, 1),
            "pct_hold_signal": round(pct_hold, 1),
            "pct_sell_signal": round(pct_sell, 1),
            "mean_buy_conv": round(mean_buy_conv, 3),
            "mean_conv_all": round(mean_conv_all, 3),
        })
        print(f"  run {i+1}/{N_RUNS} start={start} ret={summary['total_return_pct']:.1f}% "
              f"n_buys={n} pct_buy={pct_buy:.0f}% conv={mean_conv_all:.2f}", flush=True)

    print("\n=== RUNS ===")
    for r in runs:
        print(r)

    # Correlation: pct_buy_signal vs return
    if len(runs) >= 3:
        import math
        def corr(xs, ys):
            n = len(xs); mx = sum(xs)/n; my = sum(ys)/n
            num = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
            den = math.sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
            return num/den if den else 0
        print("\n=== CORRELATIONS ===")
        print(f"corr(pct_buy_signal, return): {corr([r['pct_buy_signal'] for r in runs], [r['return_pct'] for r in runs]):.3f}")
        print(f"corr(mean_conv_all, return):  {corr([r['mean_conv_all'] for r in runs], [r['return_pct'] for r in runs]):.3f}")

    with open("/tmp/gcvr_xgb_test.json", "w") as f:
        json.dump(runs, f, indent=2)
    print("\nSaved to /tmp/gcvr_xgb_test.json")


if __name__ == "__main__":
    main()
