"""Run a backtest for SectorScannerTop5Rotation and write its .meta.json sidecar."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure `app` is importable when run as a plain script (cwd is backend/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.strategies.sector_scanner_top5_rotation import SectorScannerTop5Rotation
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter

AS_OF = "2020-01-01"
END = "2026-07-08"
CAPITAL = 100_000.0

META_PATH = Path(__file__).resolve().parent.parent / "app" / "services" / "strategies" / "sector_scanner_top5_rotation.meta.json"


def main() -> int:
    strategy = SectorScannerTop5Rotation()
    adapter = StrategyBacktestAdapter(strategy)
    print(f"Running backtest {AS_OF} -> {END} (capital={CAPITAL})...", flush=True)
    result = adapter.run(as_of=AS_OF, end=END, capital=CAPITAL)
    summary = result["summary"]
    trades = result["trades"]

    meta = {
        "cagr_pct": summary.get("cagr_pct", 0.0),
        "sharpe_ratio": summary.get("sharpe_ratio", 0.0),
        "total_return_pct": summary.get("total_return_pct", 0.0),
        "win_rate": summary.get("win_rate", 0.0),
        "max_drawdown_pct": summary.get("max_drawdown_pct", 0.0),
        "total_trades": len(trades),
        "last_backtest": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    META_PATH.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote {META_PATH}")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
