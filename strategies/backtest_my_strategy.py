"""Quick backtest for GoldenCrossRotationV2 via the adapter."""
import random, sys, os, time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")

from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.golden_cross_rotation_v2 import GoldenCrossRotationV2


def run_backtest(as_of: str, end: str, capital: float = 100_000):
    """Run a single backtest window. Returns summary KPIs."""
    adapter = StrategyBacktestAdapter(GoldenCrossRotationV2())
    result = adapter.run(as_of=as_of, end=end, capital=capital)
    return result["summary"]


# ── Main ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    end = "2026-07-31"

    # Single test run first
    print("\n=== Single test run: 2020-01-01 to 2024-01-01 ===")
    s = run_backtest("2020-01-01", "2024-01-01")
    for k, v in s.items():
        if isinstance(v, (int, float)):
            print(f"  {k}: {v}")

    # Then do 10 random runs
    start_base = datetime(2010, 1, 1)
    start_range = (datetime(2020, 12, 31) - start_base).days

    results = []
    for i in range(10):
        as_of = (start_base + timedelta(days=random.randint(0, start_range))).strftime("%Y-%m-%d")
        print(f"\nRun {i+1}/10: as_of={as_of}  end={end}")
        t0 = time.time()
        try:
            s = run_backtest(as_of, end)
            elapsed = time.time() - t0
            s["start"] = as_of
            s["run"] = i + 1
            results.append(s)
            print(f"  [{elapsed:.0f}s] ret={s['total_return_pct']:+.1f}%  sharpe={s['sharpe_ratio']:.2f}  trades={s['total_trades']}  win={s['win_rate']:.1f}%")
        except Exception as e:
            import traceback
            print(f"  FAILED: {e}")
            traceback.print_exc()

    print("\n" + "=" * 110)
    print(f"{'Run':>4}  {'Start':>12}  {'Return':>8}  {'Alpha':>8}  {'Sharpe':>7}  {'MaxDD':>7}  {'Win%':>6}  {'Trades':>6}  {'Profit':>7}")
    print("-" * 110)
    for r in results:
        print(f"{r['run']:>4}  {r['start']:>12}  {r['total_return_pct']:>+7.1f}%  {r['alpha_pct']:>+7.1f}%  {r['sharpe_ratio']:>7.2f}  {r['max_drawdown_pct']:>6.1f}%  {r['win_rate']:>5.1f}%  {r['total_trades']:>6}  {r['profit_factor']:>7.2f}")

    if results:
        avg_ret = sum(r["total_return_pct"] for r in results) / len(results)
        avg_sharpe = sum(r["sharpe_ratio"] for r in results) / len(results)
        avg_win = sum(r["win_rate"] for r in results) / len(results)
        avg_trades = sum(r["total_trades"] for r in results) / len(results)
        print("-" * 110)
        print(f"{'AVG':>4}  {'':>12}  {avg_ret:>+7.1f}%  {'':>8}  {avg_sharpe:>7.2f}  {'':>7}  {avg_win:>5.1f}%  {avg_trades:>6.0f}")
    print("=" * 110)
