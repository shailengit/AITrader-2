"""Export a strategy's latest experiment batch to Obsidian notes.

One note per run (KPIs, exit-reason table, holding-period stats, top winners and
losers, full trade table) plus a batch index linking them all. Everything comes
from `strategy_experiments.trades_summary`, which stores the complete buy/sell
history per run.

Usage:
    cd backend && ./venv/bin/python scripts/export_experiments_obsidian.py \
        --strategy momentum_quality_rotation_v1

    # a specific batch, or specific runs
    ... --strategy momentum_quality_rotation_v1 --batch <batch_id> --runs 31,7

Default vault: $OBSIDIAN_VAULT_PATH, else ~/Documents/Obsidian Vault.
Writes to <vault>/TradeCraft Experiments/<Strategy>/<batch date>/.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

from app.db.database import SessionLocal  # noqa: E402
from app.models.strategy_lab import StrategyExperiment  # noqa: E402
from app.services import brain_service as B  # noqa: E402
from app.services.experiment_export import export_runs, safe_name  # noqa: E402

DEFAULT_VAULT = Path(os.environ.get("OBSIDIAN_VAULT_PATH",
                                    Path.home() / "Documents" / "Obsidian Vault"))


def _query(db, strategy: str):
    from sqlalchemy import or_
    stem = Path(strategy).stem
    return (db.query(StrategyExperiment)
            .filter(StrategyExperiment.status == "completed")
            .filter(or_(StrategyExperiment.strategy_class_path == strategy,
                        StrategyExperiment.strategy_class_path.like(f"%/{stem}.py")))
            .all())


def _detail(exp) -> dict:
    k = exp.kpis or {}
    d = B._run_trade_detail(exp, include_trades=True, max_trades=10 ** 9)
    d.update({
        "sharpe_ratio": k.get("sharpe_ratio"),
        "max_drawdown_pct": k.get("max_drawdown_pct"),
        "total_trades": k.get("total_trades"),
        "win_rate": k.get("win_rate"),
    })
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True,
                    help="strategy class path or module stem, e.g. momentum_quality_rotation_v1")
    ap.add_argument("--batch", default=None, help="batch id (default: latest)")
    ap.add_argument("--runs", default=None, help="comma-separated run indices")
    ap.add_argument("--vault", default=str(DEFAULT_VAULT))
    ap.add_argument("--folder", default="TradeCraft Experiments")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        exps = _query(db, args.strategy)
        if not exps:
            print(f"no completed experiments found for {args.strategy!r}")
            return 1

        batch_id = args.batch
        if not batch_id:
            latest = max(exps, key=lambda e: e.completed_at or e.started_at)
            batch_id = str(latest.batch_id)
        selected = [e for e in exps if str(e.batch_id) == str(batch_id)]

        if args.runs:
            wanted = {int(x) for x in args.runs.split(",") if x.strip()}
            selected = [e for e in selected if e.run_index in wanted]

        if not selected:
            print(f"no runs matched (batch={batch_id} runs={args.runs})")
            return 1

        selected.sort(key=lambda e: e.run_index)
        strategy_name = (B.strategy_name_from_path(selected[0].strategy_class_path)
                          or Path(args.strategy).stem)
        batch_date = max((e.completed_at or e.started_at) for e in selected).strftime("%Y-%m-%d")

        out_dir = (Path(args.vault).expanduser() / args.folder
                   / safe_name(strategy_name) / batch_date)
        details = [_detail(e) for e in selected]
        written = export_runs(details, strategy_name, batch_date, out_dir)

        print(f"{strategy_name} — batch {batch_id} — {len(selected)} runs")
        print(f"vault note folder: {out_dir}")
        print(f"wrote {len(written)} files "
              f"({len(written) - 1} run notes + 00 Index.md)")
        runs = [d["run_index"] for d in details]
        print(f"runs: {runs[:10]}{' …' if len(runs) > 10 else ''}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
