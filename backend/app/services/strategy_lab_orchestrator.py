"""Orchestrator for batch backtest runs of a single strategy.

For each run in a batch:
  1. Pick a random as_of_date from the configured range
  2. Import the Strategy subclass (from a file path or module path)
  3. Run StrategyBacktestAdapter(strategy).run() with the random as_of
  4. Push a result event to the per-batch queue (and persist to DB)

Supports two modes:
  - `strategy_class_path`: path to a Strategy subclass file (e.g. "strategies/my_strategy.py")
  - `code_text`: raw Python code (legacy mode, for backward compat)

Concurrency: ThreadPoolExecutor with max 4 workers (limits DB pressure).
"""
import importlib.util
import logging
import os
import queue as thread_queue
import random
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@dataclass
class ExperimentEvent:
    """One event in the orchestrator's stream."""
    run_index: int
    status: str  # "running" | "completed" | "failed"
    kpis: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@dataclass
class ExperimentBatch:
    """In-memory state for one running batch."""
    batch_id: str
    session_id: str
    n_runs: int
    end_date: str
    start_date_min: str
    start_date_max: str
    code_text: str = ""
    # New mode: path to a Strategy subclass file (e.g. "strategies/my_strategy.py")
    strategy_class_path: str = ""
    # Optional: exact start dates to reuse (from a previous batch for apples-to-apples comparison)
    fixed_start_dates: Optional[List[str]] = None
    # Thread-safe queue (not asyncio.Queue — we run from worker threads)
    queue: thread_queue.Queue = field(default_factory=thread_queue.Queue)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    is_done: bool = False
    # Set once finalization (report/journal/analysis) has run, so the watchdog
    # and the worker can't both finalize the same batch.
    finalized: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


# In-memory store of running batches (one entry per batch_id)
_RUNNING_BATCHES: Dict[str, ExperimentBatch] = {}

# Watchdog state: batch_ids the recovery watchdog has already finalized.
# A batch in this set is skipped by the worker's own finalization (so a hung
# worker thread that finally returns doesn't create duplicate artifacts /
# duplicate `backtest_analysis` rows). Process-local: after a restart it is
# empty, so a batch orphaned by the previous process is recovered exactly once.
_WATCHDOG_RECOVERED: set = set()
_WATCHDOG_LOCK = threading.Lock()
# A single backtest run must complete within this many seconds, or the batch is
# considered orphaned/stuck. The worker's own per-run budget is 600s
# (`as_completed` timeout), so 30 minutes is a generous 3x buffer — a healthy
# batch never trips it, while a process restart or a hung worker always does.
_STALE_RUN_SECONDS = 30 * 60
_WATCHDOG_STARTED = False


def get_batch(batch_id: str) -> Optional[ExperimentBatch]:
    return _RUNNING_BATCHES.get(batch_id)


def _write_strategy_file(session_id: str, code_text: str) -> Path:
    """Write the LLM-generated strategy code to a temp directory.

    Uses /tmp/strategy_lab_generated/ to avoid triggering uvicorn --reload
    (which watches the project root for file changes). The engine path in
    the generated code is rewritten to an absolute path so the import works
    regardless of where the temp file is written.
    """
    import tempfile
    session_dir = Path(tempfile.gettempdir()) / "strategy_lab_generated" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    strategy_path = session_dir / "strategy.py"
    # Rewrite the relative engine path to an absolute path
    engine_abs = str(ENGINE_PATH)
    code_text = code_text.replace(
        'os.path.join(os.path.dirname(__file__), "..", "..", "engine.py")',
        repr(engine_abs),
    )
    strategy_path.write_text(code_text)
    return strategy_path


def _random_date_in_range(min_date: str, max_date: str) -> str:
    """Pick a random date between min_date and max_date, inclusive."""
    start = datetime.strptime(min_date, "%Y-%m-%d")
    end = datetime.strptime(max_date, "%Y-%m-%d")
    delta_days = (end - start).days
    if delta_days <= 0:
        return min_date
    return (start + timedelta(days=random.randint(0, delta_days))).strftime("%Y-%m-%d")


def _create_running_experiment(
    batch_id: str, db_session_id: uuid.UUID, run_index: int, start_date: Any, end_date: Any,
    strategy_class_path: str = "",
) -> None:
    """Create an experiment row as 'running' BEFORE the backtest runs.

    The signal precompute can take a while, and experiment rows were only
    written after a run completed — so the frontend had nothing to show and
    displayed 'Warming Up'. Creating the row up front lets the frontend show
    the actual run + progress during the precompute.
    """
    try:
        from app.db.database import SessionLocal
        from app.models.strategy_lab import StrategyExperiment, StrategySession
        with SessionLocal() as db:
            if db.get(StrategySession, db_session_id) is None:
                db.add(StrategySession(id=db_session_id, name="(batch)", prompt="", model_id=""))
                db.commit()
            db.add(StrategyExperiment(
                session_id=db_session_id,
                batch_id=uuid.UUID(batch_id),
                strategy_class_path=strategy_class_path or None,
                run_index=run_index,
                start_date=start_date,
                end_date=end_date,
                status="running",
            ))
            db.commit()
    except Exception as e:
        logger.exception("Failed to create running experiment: %s", e)


def _run_one(
    code_text: str,
    db_session_id: uuid.UUID,
    as_of: str,
    end_date: str,
    run_index: int,
    strategy_class_path: str = "",
    batch_id: str = "",
    precomputed_signals: Optional[Dict[str, List[Any]]] = None,
    price_cache: Optional[Dict[str, Dict[str, float]]] = None,
    strategy_instance: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run a single backtest. Returns a dict with status/kpis/error/start_date/end_date.

    Supports two modes:
      - strategy_class_path: path to a Strategy subclass file
      - code_text: raw Python code (legacy mode)

    Runs synchronously (intended to be called from a worker thread).
    """
    started_at = datetime.now().isoformat()

    # Create the experiment row as 'running' before the (potentially slow)
    # precompute so the frontend can show live progress immediately.
    if batch_id:
        _create_running_experiment(batch_id, db_session_id, run_index, as_of, end_date,
                                   strategy_class_path=strategy_class_path)

    if strategy_class_path:
        # New mode: import Strategy subclass directly
        return _run_strategy_class(
            strategy_class_path, as_of, end_date, run_index, started_at,
            precomputed_signals=precomputed_signals,
            price_cache=price_cache,
            strategy_instance=strategy_instance,
        )

    # Legacy mode: write code_text to temp file and run via StrategyEngine
    return _run_code_text(code_text, session_id, as_of, end_date, run_index, started_at)


def _augment_kpis_with_regime(
    kpis: Dict[str, Any], trades: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Add BULL/BEAR regime-split returns to a run's KPIs.

    Uses the process-wide trained SectorRegimeManager — the SAME instance the
    markov router and screener regime filter train (see markov.py). Each
    realized SELL trade's pnl is bucketed by its sector regime on entry_date,
    then expressed as a percent of the run's initial capital so the columns
    read consistently alongside total_return_pct.

    Regime classification is only possible if that manager has already been
    trained. Training 11 Markov+GARCH models per run is far too expensive for
    a streaming backtest batch, so when the manager is untrained (no regime
    scan run yet) we default the split to 0 and surface it as such. Trades
    that classify as UNKNOWN (untrained ETF, missing sector) are skipped.
    """
    try:
        from app.services.markov.regime_model import get_shared_regime_manager
        from app.services.data_service import DataService
    except Exception:
        # Regime stack unavailable — degrade gracefully, never fail the run.
        kpis["bull_return_pct"] = 0.0
        kpis["bear_return_pct"] = 0.0
        return kpis

    rm = get_shared_regime_manager()
    if not rm.models:
        # Manager not trained yet (no Markov scan has run) — can't classify.
        kpis["bull_return_pct"] = 0.0
        kpis["bear_return_pct"] = 0.0
        return kpis

    initial_capital = float(kpis.get("initial_capital") or 0.0) or 100_000.0
    bull_pnl = 0.0
    bear_pnl = 0.0
    # Cache sector lookups to avoid a metadata query per trade.
    sector_cache: Dict[str, str] = {}

    for t in trades:
        if t.get("side") != "SELL":
            continue
        ticker = t.get("ticker", "")
        entry_date = t.get("entry_date")
        pnl = t.get("pnl_dollars") or 0.0
        if not ticker or not entry_date:
            continue
        if ticker not in sector_cache:
            try:
                meta = DataService.get_ticker_metadata(ticker)
                sector_cache[ticker] = (meta or {}).get("sector", "") or ""
            except Exception:
                sector_cache[ticker] = ""
        sector = sector_cache[ticker]
        if not sector:
            continue
        try:
            regime = rm.get_ticker_regime(ticker, sector, entry_date).get("regime")
        except Exception:
            continue
        if regime == "BULL":
            bull_pnl += pnl
        elif regime == "BEAR":
            bear_pnl += pnl

    kpis["bull_return_pct"] = round(bull_pnl / initial_capital * 100, 2)
    kpis["bear_return_pct"] = round(bear_pnl / initial_capital * 100, 2)
    return kpis


def _precompute_for_batch(
    strategy_class_path: str, start_date_min: str, end_date: str
) -> tuple:
    """Compute precompute_signals + price_cache ONCE for the full batch range.

    Runs in a batch share the same end date and only vary the (randomized)
    start date, so the expensive signal precompute can be done a single time
    for the widest range and reused by every run. Returns (signals,
    price_cache, strategy_instance) or (None, None, None) if the strategy
    doesn't support precompute.
    """
    try:
        import pandas as pd
        from app.services.strategy_base import Strategy
        from app.db.database import engine as db_engine
        import importlib.util, sys
        full_path = REPO_ROOT / strategy_class_path
        if not full_path.exists():
            return None, None, None
        spec = importlib.util.spec_from_file_location("_strategy_precompute", str(full_path))
        if spec is None or spec.loader is None:
            return None, None, None
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_strategy_precompute"] = mod
        spec.loader.exec_module(mod)
        strategy_class = None
        for name in dir(mod):
            obj = getattr(mod, name)
            # Only consider classes DEFINED in this module (not imported ones),
            # so a strategy file that subclasses another strategy (e.g. v2
            # variants) resolves to the right class instead of the imported base.
            if (
                isinstance(obj, type)
                and issubclass(obj, Strategy)
                and obj is not Strategy
                and getattr(obj, "__module__", "") == mod.__name__
            ):
                strategy_class = obj
                break
        if strategy_class is None:
            return None, None, None
        strategy = strategy_class()
        with db_engine.connect() as conn:
            spy_dates = pd.read_sql(
                f'SELECT "Date" FROM spy WHERE "Date" >= \'{start_date_min}\' AND "Date" <= \'{end_date}\' ORDER BY "Date"',
                conn,
            )
        all_dates = [str(d)[:10] for d in spy_dates["Date"]]
        if not all_dates:
            return None, None, None
        signals = strategy.precompute_signals(all_dates, db_engine)
        price_cache = strategy.get_precomputed_price_cache()
        # Precompute the holding re-score map once so score_holding() is a fast
        # in-memory lookup during the simulation loop instead of a database
        # query per holding per day (~10k queries/run). This is the main reason
        # batch backtests were ~30x slower than they needed to be.
        if hasattr(strategy, "precompute_scores"):
            try:
                strategy.precompute_scores(all_dates, db_engine)
            except Exception as e:
                logger.warning("precompute_scores failed (falling back to per-day): %s", e)
        logger.info("Batch precompute done for %d dates (reused across runs)", len(all_dates))
        return signals, price_cache, strategy
    except Exception as e:
        logger.warning("Batch precompute failed (will precompute per-run): %s", e)
        return None, None, None


def _run_strategy_class(
    class_path: str,
    as_of: str,
    end_date: str,
    run_index: int,
    started_at: str,
    precomputed_signals: Optional[Dict[str, List[Any]]] = None,
    price_cache: Optional[Dict[str, Dict[str, float]]] = None,
    strategy_instance: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run a backtest using a Strategy subclass file.

    precomputed_signals / price_cache may be passed in (computed once for the
    full batch date range) to skip the expensive per-run precompute.
    strategy_instance may be the precomputed instance (carries its caches).
    """
    from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
    from app.services.strategy_base import Strategy

    try:
        # Resolve the path relative to REPO_ROOT
        full_path = REPO_ROOT / class_path
        if not full_path.exists():
            return {
                "run_index": run_index, "status": "failed",
                "error_message": f"Strategy file not found: {full_path}",
                "started_at": started_at,
                "completed_at": datetime.now().isoformat(),
                "start_date": as_of, "end_date": end_date,
            }

        # Import the module
        spec = importlib.util.spec_from_file_location("_strategy_backtest", str(full_path))
        if spec is None or spec.loader is None:
            return {
                "run_index": run_index, "status": "failed",
                "error_message": f"Could not create import spec for {full_path}",
                "started_at": started_at,
                "completed_at": datetime.now().isoformat(),
                "start_date": as_of, "end_date": end_date,
            }
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_strategy_backtest"] = mod
        spec.loader.exec_module(mod)

        # Find the Strategy subclass
        strategy_class = None
        for name in dir(mod):
            obj = getattr(mod, name)
            # Only consider classes DEFINED in this module (not imported ones),
            # so a strategy file that subclasses another strategy (e.g. v2
            # variants) resolves to the right class instead of the imported base.
            if (
                isinstance(obj, type)
                and issubclass(obj, Strategy)
                and obj is not Strategy
                and getattr(obj, "__module__", "") == mod.__name__
            ):
                strategy_class = obj
                break

        if strategy_class is None:
            return {
                "run_index": run_index, "status": "failed",
                "error_message": f"No Strategy subclass found in {class_path}",
                "started_at": started_at,
                "completed_at": datetime.now().isoformat(),
                "start_date": as_of, "end_date": end_date,
            }

        # Run the backtest (reuse precomputed signals/price cache if provided).
        # Reuse the precomputed strategy instance so its caches (e.g. the
        # should_exit close cache) are available during the simulation.
        strategy = strategy_instance if strategy_instance is not None else strategy_class()
        adapter = StrategyBacktestAdapter(strategy)
        result_data = adapter.run(
            as_of=as_of, end=end_date,
            precomputed_signals=precomputed_signals,
            price_cache=price_cache,
        )
        summary = result_data["summary"]
        # BULL/BEAR regime-split (only computed if the shared Markov manager
        # is already trained; otherwise defaults to 0).
        summary = _augment_kpis_with_regime(summary, result_data.get("trades", []))

        # Downsample equity curve
        equity_curve = result_data.get("daily_equity", [])
        if len(equity_curve) > 500:
            n = len(equity_curve)
            step = n / 498
            # Clamp to n-1: float rounding of 498*(n/498) can land exactly on n.
            indices = [0] + [min(int(i * step), n - 1) for i in range(1, 498)] + [n - 1]
            equity_curve = [equity_curve[i] for i in sorted(set(indices))]

        return {
            "run_index": run_index, "status": "completed",
            "kpis": summary, "equity_curve": equity_curve,
            "trades": result_data.get("trades", []),
            "started_at": started_at,
            "completed_at": datetime.now().isoformat(),
            "start_date": as_of, "end_date": end_date,
        }
    except Exception as e:
        import traceback
        return {
            "run_index": run_index, "status": "failed",
            "error_message": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            "started_at": started_at,
            "completed_at": datetime.now().isoformat(),
            "start_date": as_of, "end_date": end_date,
        }


def _run_code_text(
    code_text: str,
    session_id: str,
    as_of: str,
    end_date: str,
    run_index: int,
    started_at: str,
) -> Dict[str, Any]:
    """Legacy mode: run a single backtest from raw code_text (4-function template)."""
    import importlib.util

    # Write the file
    try:
        strategy_path = _write_strategy_file(session_id, code_text)
    except Exception as e:
        return {
            "run_index": run_index, "status": "failed",
            "error_message": f"Failed to write strategy file: {e}",
            "started_at": started_at,
            "completed_at": datetime.now().isoformat(),
            "start_date": as_of, "end_date": end_date,
        }

    # safe-import via file path
    def _safe_import(path: str):
        spec = importlib.util.spec_from_file_location("_safe_imp_orchestrator", path)
        if spec is None or spec.loader is None:
            return type("R", (), {"error": f"Could not create spec for {path}", "module": None})()
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_safe_imp_orchestrator"] = mod
        try:
            spec.loader.exec_module(mod)
            return type("R", (), {"error": None, "module": mod})()
        except Exception as e:
            sys.modules.pop("_safe_imp_orchestrator", None)
            return type("R", (), {"error": f"{type(e).__name__}: {e}", "module": None})()

    result = _safe_import(str(strategy_path))
    if result.error or result.module is None:
        return {
            "run_index": run_index, "status": "failed",
            "error_message": f"Import error: {result.error}",
            "started_at": started_at,
            "completed_at": datetime.now().isoformat(),
            "start_date": as_of, "end_date": end_date,
        }

    mod = result.module
    try:
        cfg = None
        if hasattr(mod, "build_config") and callable(mod.build_config):
            cfg = mod.build_config(as_of=as_of, end=end_date)
        elif hasattr(mod, "CONFIG") and mod.CONFIG is not None:
            mod.CONFIG.as_of = as_of
            mod.CONFIG.end = end_date
            cfg = mod.CONFIG
        else:
            return {
                "run_index": run_index, "status": "failed",
                "error_message": "Module has no build_config() and no CONFIG",
                "started_at": started_at,
                "completed_at": datetime.now().isoformat(),
                "start_date": as_of, "end_date": end_date,
            }

        ENGINE_PATH = REPO_ROOT / "strategies" / "engine.py"
        engine_spec = importlib.util.spec_from_file_location(
            "engine_for_orchestrator", str(ENGINE_PATH),
        )
        engine_mod = importlib.util.module_from_spec(engine_spec)
        sys.modules["engine_for_orchestrator"] = engine_mod
        engine_spec.loader.exec_module(engine_mod)

        result_data = engine_mod.StrategyEngine(cfg).run()
        summary = result_data["summary"]
        equity_curve = result_data.get("daily_equity", [])
        if len(equity_curve) > 500:
            step = len(equity_curve) / 498
            indices = [0] + [int(i * step) for i in range(1, 498)] + [len(equity_curve) - 1]
            equity_curve = [equity_curve[i] for i in sorted(set(indices))]

        trades = result_data.get("trades", [])
        sell_trades = [t for t in trades if t.get("side") == "SELL"]
        sell_trades_sorted = sorted(sell_trades, key=lambda t: t.get("pnl_dollars", 0), reverse=True)
        summary["top_winners"] = [
            {"ticker": t.get("ticker", ""), "return_pct": t.get("return_pct", 0),
             "pnl_dollars": t.get("pnl_dollars", 0), "exit_reason": t.get("exit_reason", "")}
            for t in sell_trades_sorted[:5]
        ]
        summary["top_losers"] = [
            {"ticker": t.get("ticker", ""), "return_pct": t.get("return_pct", 0),
             "pnl_dollars": t.get("pnl_dollars", 0), "exit_reason": t.get("exit_reason", "")}
            for t in (sell_trades_sorted[-5:] if len(sell_trades_sorted) >= 5 else sell_trades_sorted[::-1])
        ]

        return {
            "run_index": run_index, "status": "completed",
            "kpis": summary, "equity_curve": equity_curve,
            "started_at": started_at,
            "completed_at": datetime.now().isoformat(),
            "start_date": as_of, "end_date": end_date,
        }
    except Exception as e:
        return {
            "run_index": run_index, "status": "failed",
            "error_message": f"{type(e).__name__}: {e}",
            "started_at": started_at,
            "completed_at": datetime.now().isoformat(),
            "start_date": as_of, "end_date": end_date,
        }


def _send_alert_message(text: str) -> None:
    """Push an alert to the user's WhatsApp self-chat (fail-isolated).

    Uses `hermes send` (the established delivery path for the trading stack —
    the same CLI the daily Alpaca portfolio report uses). Never raises: a
    notification failure must not break a batch or the watchdog.
    """
    import shutil
    import subprocess

    target = os.getenv("STRATEGY_LAB_ALERT_TARGET", "whatsapp:197255030173941@lid")
    exe = shutil.which("hermes") or "/Users/shailendrakaushik/.local/bin/hermes"
    try:
        proc = subprocess.run(
            [exe, "send", "--to", target, text],
            capture_output=True, text=True, timeout=30,
        )
        logger.info("Sent strategy-lab alert via %s (rc=%s)", exe, proc.returncode)
    except Exception as e:
        logger.exception("Failed to send strategy-lab alert: %s", e)


def _mark_batch_done(batch: ExperimentBatch) -> None:
    """Flip a batch to done: set is_done, push the sentinel, clean the map.

    Idempotent — the watchdog and the worker both call this.
    """
    with batch.lock:
        if batch.is_done:
            return
        batch.is_done = True
    # Sentinel for SSE consumers (must be `None` — `drain_events` returns on it).
    batch.queue.put(None)
    # Daemon so it never blocks interpreter exit (e.g. in tests/scripts).
    t = threading.Timer(300.0, lambda: _RUNNING_BATCHES.pop(batch.batch_id, None))
    t.daemon = True
    t.start()


def _reconstruct_results(batch_id: str) -> List[Dict[str, Any]]:
    """Rebuild the in-memory `results` list a batch worker would have produced.

    Used by the watchdog to recover a batch orphaned by a backend restart: the
    worker died mid-batch, so its `all_results` are gone, but every completed
    run's kpis/equity_curve/trades were persisted to `strategy_experiments`.
    Returns result dicts in the same shape `_finalize_batch` expects.
    """
    try:
        from app.db.database import SessionLocal
        from app.models.strategy_lab import StrategyExperiment
        results = []
        with SessionLocal() as db:
            rows = db.query(StrategyExperiment).filter(
                StrategyExperiment.batch_id == uuid.UUID(batch_id),
                StrategyExperiment.status == "completed",
            ).order_by(StrategyExperiment.run_index).all()
            for r in rows:
                results.append({
                    "run_index": r.run_index,
                    "status": "completed",
                    "kpis": r.kpis or {},
                    "equity_curve": r.equity_curve or [],
                    "trades": r.trades_summary or [],
                    "start_date": r.start_date.isoformat() if r.start_date else None,
                    "end_date": r.end_date.isoformat() if r.end_date else None,
                })
        return results
    except Exception as e:
        logger.exception("Failed to reconstruct results for batch %s: %s", batch_id, e)
        return []


def _finalize_batch(
    batch: ExperimentBatch,
    results: List[Dict[str, Any]],
    strategy_class_path: str = "",
) -> None:
    """Generate the HTML report, sidecar meta, Coach journal, and AI learnings.

    This is the same finalization the batch worker runs after all runs finish,
    extracted so the watchdog can run it identically for a RECOVERED (orphaned)
    batch. Guarded by `batch.finalized` so the worker and watchdog can't both
    run it for the same batch (which would duplicate the report, journal rows,
    and `backtest_analysis` row).
    """
    with batch.lock:
        if batch.finalized:
            return
        batch.finalized = True

    report_path = None
    try:
        report_path = _generate_batch_report(batch, results)
    except Exception as report_err:
        logger.exception("Failed to generate batch report: %s", report_err)

    if strategy_class_path:
        try:
            _write_sidecar_meta(strategy_class_path, results)
        except Exception as meta_err:
            logger.exception("Failed to write sidecar meta: %s", meta_err)

    if strategy_class_path and report_path:
        try:
            from app.services.coach.strategy_lab_journal import journal_strategy_lab_backtest
            for result in results:
                if result.get("status") == "completed" and result.get("kpis"):
                    journal_strategy_lab_backtest(
                        strategy_class_path,
                        result.get("kpis"),
                        result.get("start_date") or "",
                        result.get("end_date") or "",
                        trades=result.get("trades"),
                        report_path=report_path,
                    )
        except Exception as journal_err:
            logger.exception("Strategy Lab journal hook failed: %s", journal_err)

    if strategy_class_path and report_path:
        try:
            from app.services.coach.backtest_analysis_service import analyze_backtest_batch
            analyze_backtest_batch(
                results, strategy_class_path,
                report_path=report_path, batch_id=batch.batch_id,
            )
        except Exception as analysis_err:
            logger.exception("Backtest analysis hook failed: %s", analysis_err)


def _fail_stale_running(batch: ExperimentBatch, reason: str) -> int:
    """Mark a batch's stale 'running' rows as failed in the DB (watchdog recovery).

    A batch orphaned by a restart (or a worker killed mid-run) leaves its last
    in-flight run(s) stuck on 'running' forever — exactly what happened to
    `daily_golden_cross` (99/100 done, run 100 stuck). This flips those rows to
    'failed' with a clear error so the frontend counts completed+failed == n_runs
    and the batch can finalize. Returns how many rows were marked.
    """
    n = 0
    try:
        from app.db.database import SessionLocal
        from app.models.strategy_lab import StrategyExperiment
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(seconds=_STALE_RUN_SECONDS)
        with SessionLocal() as db:
            rows = db.query(StrategyExperiment).filter(
                StrategyExperiment.batch_id == uuid.UUID(batch.batch_id),
                StrategyExperiment.status == "running",
                StrategyExperiment.started_at < cutoff,
            ).all()
            for r in rows:
                r.status = "failed"
                r.error_message = reason
                r.completed_at = datetime.now()
                n += 1
            db.commit()
    except Exception as e:
        logger.exception("Failed to mark stale running rows for %s: %s", batch.batch_id, e)
    return n


def _watchdog_loop() -> None:
    """Background daemon: recover batches whose runs are stuck on 'running'.

    Every 60s, scan BOTH the in-memory map and the DB for experiment rows stuck
    on 'running' older than `_STALE_RUN_SECONDS` (30 min). A healthy run
    completes in ~20-30s, so a run stuck past 30 minutes means either a backend
    restart (the worker thread is gone) or a genuinely hung worker. In either
    case that batch can never finish on its own — so the watchdog finalizes it
    from the last persisted state, marks the stuck runs failed, and alerts the
    user on WhatsApp. This is the escape logic the user asked for.

    Covering the DB (not just `_RUNNING_BATCHES`) is what lets it also recover
    a batch orphaned by a PREVIOUS process (the map was wiped on restart) —
    exactly the daily_golden_cross 99/100 situation.
    """
    while True:
        try:
            # 1. In-memory batches (a live worker exists for these; recover if
            #    a run wedged past the budget).
            batches = list(_RUNNING_BATCHES.values())
            for batch in batches:
                try:
                    with batch.lock:
                        if batch.is_done or batch.finalized:
                            continue
                    marked = _fail_stale_running(
                        batch,
                        f"Recovered by watchdog: run exceeded {_STALE_RUN_SECONDS // 60} min (worker hung).",
                    )
                    if marked > 0:
                        _recover_batch(batch, marked)
                except Exception as batch_err:
                    logger.exception("Watchdog error for batch %s: %s", batch.batch_id, batch_err)

            # 2. DB-only batches (worker was in a process that died). Find any
            #    batch with stale 'running' rows and recover it.
            try:
                from app.db.database import SessionLocal
                from app.models.strategy_lab import StrategyExperiment
                from datetime import timedelta
                cutoff = datetime.utcnow() - timedelta(seconds=_STALE_RUN_SECONDS)
                with SessionLocal() as db:
                    stale_ids = db.query(
                        StrategyExperiment.batch_id
                    ).filter(
                        StrategyExperiment.status == "running",
                        StrategyExperiment.started_at < cutoff,
                    ).group_by(StrategyExperiment.batch_id).all()
                for (bid,) in stale_ids:
                    bid = str(bid)
                    with _WATCHDOG_LOCK:
                        if bid in _WATCHDOG_RECOVERED:
                            continue
                        _WATCHDOG_RECOVERED.add(bid)
                    try:
                        _recover_db_batch(bid, cutoff)
                    except Exception as be:
                        logger.exception("Watchdog DB-recovery error for batch %s: %s", bid, be)
            except Exception as e:
                logger.exception("Watchdog DB scan failed: %s", e)
        except Exception as e:
            logger.exception("Strategy Lab watchdog error: %s", e)
        import time as _time
        _time.sleep(60)


def _recover_batch(batch: ExperimentBatch, marked: int) -> None:
    """Recover an orphaned IN-MEMORY batch: finalize + alert."""
    results = _reconstruct_results(batch.batch_id)
    _finalize_batch(batch, results, batch.strategy_class_path)
    _mark_batch_done(batch)
    _send_alert_message(
        "⚠️ Strategy Lab batch auto-recovered by watchdog.\n"
        f"Batch {batch.batch_id[:8]} · {batch.strategy_class_path or batch.code_text[:40]}\n"
        f"{len(results)} completed run(s) finalized + {marked} stuck run(s) marked "
        "failed (backend restarted / worker hung)."
    )


def _recover_db_batch(batch_id: str, cutoff) -> None:
    """Recover a DB-only orphaned batch (worker process died)."""
    # Build a shell batch so finalize/report have the fields they need.
    # Restore strategy_class_path (and end_date) from the persisted rows so the
    # report/sidecar/journal/analysis hooks fire correctly.
    try:
        from app.db.database import SessionLocal
        from app.models.strategy_lab import StrategyExperiment
        scp, end = "", ""
        with SessionLocal() as db:
            first = db.query(StrategyExperiment).filter(
                StrategyExperiment.batch_id == uuid.UUID(batch_id),
            ).order_by(StrategyExperiment.run_index).first()
            if first is not None:
                scp = first.strategy_class_path or ""
                end = first.end_date.isoformat() if first.end_date else ""
    except Exception as e:
        logger.exception("Could not read batch %s metadata: %s", batch_id, e)
        scp, end = "", ""

    batch = ExperimentBatch(
        batch_id=batch_id,
        session_id="_",
        n_runs=_infer_n_runs(batch_id),
        end_date=end,
        start_date_min="",
        start_date_max="",
        strategy_class_path=scp,
    )
    marked = _fail_stale_running(batch, "Recovered by watchdog: run exceeded "
                                         f"{_STALE_RUN_SECONDS // 60} min (backend restarted / worker hung).")
    if marked <= 0:
        return
    results = _reconstruct_results(batch_id)
    _finalize_batch(batch, results, scp)
    _send_alert_message(
        "⚠️ Strategy Lab batch auto-recovered by watchdog.\n"
        f"Batch {batch_id[:8]} · {scp or 'unknown strategy'} · {marked} stuck run(s) marked failed\n"
        f"{len(results)} completed run(s) were finalized from persisted data "
        "(backend restarted / worker hung)."
    )


def _infer_n_runs(batch_id: str) -> int:
    try:
        from app.db.database import SessionLocal
        from app.models.strategy_lab import StrategyExperiment
        with SessionLocal() as db:
            return db.query(StrategyExperiment).filter(
                StrategyExperiment.batch_id == uuid.UUID(batch_id),
            ).count()
    except Exception:
        return 0


def _ensure_watchdog() -> None:
    global _WATCHDOG_STARTED
    with _WATCHDOG_LOCK:
        if _WATCHDOG_STARTED:
            return
        _WATCHDOG_STARTED = True
    t = threading.Thread(target=_watchdog_loop, name="strategy-lab-watchdog", daemon=True)
    t.start()
    logger.info("Strategy Lab recovery watchdog started")


def run_batch(
    session_id: str,
    n_runs: int,
    code_text: str = "",
    end_date: str = "",
    start_date_min: str = "",
    start_date_max: str = "",
    fixed_start_dates: Optional[List[str]] = None,
    strategy_class_path: str = "",
) -> str:
    """Start a batch of n_runs backtests in a background thread.

    Supports two modes:
      - strategy_class_path: path to a Strategy subclass file (new mode)
      - code_text: raw Python code (legacy mode)

    If fixed_start_dates is provided (list of YYYY-MM-DD strings), those exact
    dates are used instead of generating random ones. This enables apples-to-apples
    comparison when refining a strategy.

    Returns the batch_id immediately. The actual runs execute in a thread
    pool; each result is persisted to the DB and pushed to the in-memory
    queue (so SSE consumers can stream them).
    """
    batch_id = str(uuid.uuid4())
    batch = ExperimentBatch(
        batch_id=batch_id,
        session_id=session_id,
        n_runs=n_runs,
        end_date=end_date,
        start_date_min=start_date_min,
        start_date_max=start_date_max,
        code_text=code_text,
        strategy_class_path=strategy_class_path,
        fixed_start_dates=fixed_start_dates,
    )
    _RUNNING_BATCHES[batch_id] = batch

    # Start the recovery watchdog (idempotent) so this batch is auto-recovered
    # if it ever gets orphaned by a restart or a hung worker.
    _ensure_watchdog()

    # Resolve session_id for DB storage (use a random UUID for placeholder '_')
    _db_session_id = uuid.UUID(session_id) if session_id != '_' else uuid.uuid4()

    def _persist_event(event: Dict[str, Any]):
        """Persist one run's result to the DB. Called from worker threads."""
        try:
            from app.db.database import SessionLocal
            from app.models.strategy_lab import StrategyExperiment, StrategySession
            with SessionLocal() as db:
                # The placeholder session id "_" maps to a random UUID that does
                # NOT exist in strategy_sessions, so the FK on
                # strategy_experiments.session_id would fail. Ensure a real
                # session row exists first (create a placeholder if needed).
                if db.get(StrategySession, _db_session_id) is None:
                    db.add(StrategySession(
                        id=_db_session_id,
                        name="(batch)",
                        prompt="",
                        model_id="",
                    ))
                    db.commit()
                # Update the experiment row created as 'running' before the
                # precompute (matched by batch_id + run_index). Fall back to
                # creating a new row if it wasn't pre-created.
                exp = db.query(StrategyExperiment).filter(
                    StrategyExperiment.batch_id == uuid.UUID(batch_id),
                    StrategyExperiment.run_index == event["run_index"],
                ).first()
                if exp is None:
                    exp = StrategyExperiment(
                        session_id=_db_session_id,
                        batch_id=uuid.UUID(batch_id),
                        strategy_class_path=strategy_class_path or None,
                        run_index=event["run_index"],
                        start_date=event.get("start_date"),
                        end_date=event.get("end_date"),
                        status=event["status"],
                        kpis=event.get("kpis"),
                        equity_curve=event.get("equity_curve"),
                        trades_summary=event.get("trades"),
                        error_message=event.get("error_message"),
                    )
                    db.add(exp)
                else:
                    exp.status = event["status"]
                    exp.kpis = event.get("kpis")
                    exp.equity_curve = event.get("equity_curve")
                    exp.trades_summary = event.get("trades")
                    exp.error_message = event.get("error_message")
                    exp.completed_at = datetime.now()
                db.commit()
        except Exception as e:
            logger.exception("Failed to persist experiment: %s", e)

    def _worker():
        import traceback as _tb
        all_results: List[Dict[str, Any]] = []
        try:
            with open("/tmp/strategy_lab_worker.log", "a") as _f:
                _f.write(f"Worker started for batch {batch_id}\n")
            # Precompute signals + price cache ONCE for the full batch range
            # (runs share the end date and only vary the start date), so the
            # expensive precompute isn't repeated for every run.
            batch_signals, batch_price_cache, batch_strategy = None, None, None
            if strategy_class_path:
                batch_signals, batch_price_cache, batch_strategy = _precompute_for_batch(
                    strategy_class_path, start_date_min, end_date
                )

            with ThreadPoolExecutor(max_workers=1) as ex:
                futures = []
                for i in range(n_runs):
                    if batch.fixed_start_dates and i < len(batch.fixed_start_dates):
                        as_of = batch.fixed_start_dates[i]
                    else:
                        as_of = _random_date_in_range(start_date_min, start_date_max)
                    fut = ex.submit(
                        _run_one, code_text, _db_session_id, as_of, end_date, i + 1,
                        strategy_class_path, batch_id,
                        batch_signals, batch_price_cache, batch_strategy,
                    )
                    futures.append(fut)

                for fut in as_completed(futures):
                    try:
                        result = fut.result(timeout=600)
                    except TimeoutError:
                        logger.warning("Experiment timed out after 600s")
                        continue
                    except Exception as run_err:
                        logger.exception("Run failed: %s", run_err)
                        continue
                    all_results.append(result)
                    _persist_event(result)
                    batch.queue.put(result)
        except Exception as e:
            logger.exception("Batch %s failed: %s", batch_id, e)
            with open("/tmp/strategy_lab_worker.log", "a") as _f:
                _f.write(f"Batch {batch_id} failed: {e}\n{_tb.format_exc()}\n")
        finally:
            # If the watchdog already recovered this batch (it was orphaned by
            # the backend restarting, then the worker thread came back), skip
            # our own finalization to avoid duplicating report/journal rows.
            try:
                _finalize_batch(batch, all_results, strategy_class_path)
            except Exception as fin_err:
                logger.exception("Finalize failed for batch %s: %s", batch_id, fin_err)
            _mark_batch_done(batch)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return batch_id


def drain_events(batch_id: str, timeout: float = 0.5):
    """Drain all currently-available events from a batch's queue.

    Used by the SSE consumer. Returns a list of events. If the batch is
    done and the queue is empty, returns a list with a single sentinel dict.
    """
    batch = _RUNNING_BATCHES.get(batch_id)
    if batch is None:
        return [{"done": True, "batch_id": batch_id, "error": "batch not found"}]
    events_out = []
    while True:
        try:
            item = batch.queue.get(timeout=timeout)
        except thread_queue.Empty:
            break
        if item is None:
            # sentinel
            events_out.append({"done": True, "batch_id": batch_id, "n_runs": batch.n_runs})
            return events_out
        events_out.append(item)
    # If we got nothing and the batch is done, emit a sentinel
    with batch.lock:
        done = batch.is_done
    if not events_out and done:
        events_out.append({"done": True, "batch_id": batch_id, "n_runs": batch.n_runs})
    return events_out


def is_batch_done(batch_id: str) -> bool:
    batch = _RUNNING_BATCHES.get(batch_id)
    if batch is None:
        return True
    with batch.lock:
        return batch.is_done


def _write_sidecar_meta(strategy_class_path: str, results: List[Dict[str, Any]]) -> None:
    """Write the strategy's `.meta.json` sidecar from a completed batch.

    The Library table (and the Coach badge fallback) read CAGR/Sharpe/Return/
    Win%/Drawdown/Trades from a co-located `<stem>.meta.json` next to the
    strategy file. The batch backtest flow never wrote this sidecar, so
    strategies backtested only via Strategy Lab showed N/A in the Library.
    This aggregates the completed runs' KPIs as medians (a per-run figure for
    every metric, including trade count — runs have randomized start dates and
    so arbitrary lengths, making batch sums meaningless) and writes the
    sidecar. Failure-isolated.
    """
    import json
    from datetime import datetime, timezone

    if not strategy_class_path:
        return
    completed = [r for r in results if r.get("status") == "completed" and r.get("kpis")]
    if not completed:
        return

    def _median(key: str) -> float:
        vals = [float(r["kpis"].get(key) or 0.0) for r in completed]
        vals.sort()
        n = len(vals)
        return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2

    meta = {
        "cagr_pct": round(_median("cagr_pct"), 2),
        "sharpe_ratio": round(_median("sharpe_ratio"), 2),
        "total_return_pct": round(_median("total_return_pct"), 2),
        "win_rate": round(_median("win_rate"), 1),
        "max_drawdown_pct": round(_median("max_drawdown_pct"), 2),
        "total_trades": int(round(_median("total_trades"))),
        "last_backtest": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    try:
        full_path = REPO_ROOT / strategy_class_path
        meta_path = full_path.with_suffix(".meta.json")
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        logger.info("Wrote sidecar meta for %s: %s", strategy_class_path, meta_path)
    except Exception as e:
        logger.exception("Failed to write sidecar meta for %s: %s", strategy_class_path, e)


def _generate_batch_report(batch: ExperimentBatch, results: List[Dict[str, Any]]) -> str:
    """Generate the interactive HTML run-viewer report after a batch completes.

    Extracts strategy parameters from the code_text, generates the report,
    and logs the file path so the user can open it. Returns the report path.
    """
    from app.services.run_viewer_generator import generate_run_viewer

    # Extract strategy name and parameters from code_text
    strategy_name = "Unnamed Strategy"
    strategy_params = {}

    code_text = batch.code_text
    if code_text:
        # Extract STRATEGY_NAME
        import re
        name_match = re.search(r'STRATEGY_NAME\s*=\s*"([^"]+)"', code_text)
        if name_match:
            strategy_name = name_match.group(1)

        # Extract key parameters
        param_patterns = [
            "AS_OF", "END", "CAPITAL", "MAX_HOLDINGS", "MIN_HOLD_DAYS",
            "TRAILING_STOP", "TAKE_PROFIT", "TIME_STOP_DAYS",
            "MAX_SECTOR_COUNT", "BULL_EXPOSURE", "BEAR_EXPOSURE",
            "ANGLE_WEIGHT", "CAP_WEIGHT",
        ]
        for param in param_patterns:
            m = re.search(rf'{param}\s*=\s*([^\n#]+)', code_text)
            if m:
                val = m.group(1).strip().strip('"').strip("'")
                strategy_params[param] = val
    elif batch.strategy_class_path:
        # Strategy-class mode: derive a readable name from the file stem so the
        # report filename is identifiable (not "Unnamed Strategy").
        from pathlib import Path
        stem = Path(batch.strategy_class_path).stem
        strategy_name = stem.replace("_", " ").replace("-", " ").title()

    report_path = generate_run_viewer(
        experiments=results,
        strategy_name=strategy_name,
        strategy_code=code_text,
        strategy_params=strategy_params,
        batch_id=batch.batch_id,
        session_id=batch.session_id,
    )

    # Log the report path prominently with a clickable terminal hyperlink
    # OSC 8 escape sequence for clickable links in modern terminals
    link_esc = f"\033]8;;file://{report_path}\033\\"
    link_close = "\033]8;;\033\\"
    clickable_link = f"{link_esc}📊 {report_path}{link_close}"

    logger.info(
        "Batch report generated: file://%s",
        report_path,
    )
    print(f"\n{'='*70}")
    print(f"  📊 BATCH REPORT GENERATED")
    print(f"  {'='*70}")
    print(f"  Strategy: {strategy_name}")
    print(f"  Runs:     {len(results)} ({sum(1 for r in results if r.get('status')=='completed')} completed)")
    print(f"  Report:   {clickable_link}")
    print(f"  {'='*70}")
    print(f"  💡 Click the link above or open in browser:")
    print(f"     open '{report_path}'")
    print(f"{'='*70}\n")
    return report_path
