"""Generate the final Phase 5 HTML report for Golden Cross Volume Rotation.

Runs the verified best config (EMA10/EMA200 + vol 1.0x cross-day over 50d avg)
on the FIXED code (2008 warmup) and produces the interactive run-viewer report.
"""
import os, sys, json, warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from app.services.strategies.golden_cross_volume_rotation import GoldenCrossVolumeRotation
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.run_viewer_generator import generate_run_viewer

AS_OF = "2020-01-01"
END = "2026-09-04"
CAPITAL = 100_000.0


def _downsample(equity_curve, max_points=500):
    if len(equity_curve) <= max_points:
        return equity_curve
    n = len(equity_curve)
    step = n / (max_points - 2)
    indices = [0] + [min(int(i * step), n - 1) for i in range(1, max_points - 1)] + [n - 1]
    return [equity_curve[i] for i in sorted(set(indices))]


def main():
    strategy = GoldenCrossVolumeRotation()
    adapter = StrategyBacktestAdapter(strategy)
    result = adapter.run(as_of=AS_OF, end=END, capital=CAPITAL)
    summary = result["summary"]
    equity = _downsample(result.get("daily_equity", []))

    experiments = [{
        "run_index": 1,
        "status": "completed",
        "kpis": summary,
        "equity_curve": equity,
        "start_date": AS_OF,
        "end_date": END,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }]

    params = {
        "Strategy": strategy.get_name(),
        "Period": f"{AS_OF} -> {END}",
        "Capital": CAPITAL,
        "Crossover": "EMA10/EMA200",
        "Volume": "1.0x cross-day over 50d avg",
        "Ranking": "60% angle + 40% market cap",
        "Max holdings": strategy.max_holdings,
        "Hold rank": 10,
        "Min hold days": 10,
        "Hard stop": "10%",
        "Trailing stop": "20%",
        "Take profit": "25%",
        "Time stop": "90d",
        "Sector cap": 2,
        "Vol filter": "<=5%",
        "Bear mode": "cash (0% exposure)",
        "Warmup": "2008 (fixed)",
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
        batch_id="gcvr-final-verified",
    )
    print(f"\nReport: {filepath}", flush=True)
    print(f"\n=== FINAL VERIFIED KPIs ===")
    print(f"  Return:     {summary['total_return_pct']:+.1f}%")
    print(f"  CAGR:       {summary['cagr_pct']:.1f}%")
    print(f"  Alpha/yr:   {summary['alpha_per_year_pct']:+.1f}%")
    print(f"  Sharpe:     {summary['sharpe_ratio']:.2f}")
    print(f"  Max DD:     {summary['max_drawdown_pct']:.1f}%")
    print(f"  Trades:     {summary['total_trades']}")
    print(f"  Win rate:   {summary['win_rate']:.1f}%")
    print(f"  Profit F:   {summary['profit_factor']:.2f}")
    print(f"  Exit reasons: {summary['exit_reasons']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
