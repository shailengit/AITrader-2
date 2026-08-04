"""Markov Chain Trader API router."""
import logging
import threading
import time
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, date
from fastapi import APIRouter
from pydantic import BaseModel

from app.db.database import SECTOR_ETFS
from app.services.markov.regime_model import SectorRegimeManager, get_shared_regime_manager
from app.services.markov.signal_generator import SignalGenerator
from app.services.markov.feature_engineering import DEFAULT_BUY_THRESHOLD
from app.services.markov.trainer import MarkovTrainer
from app.services.data_service import DataService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/markov", tags=["markov"])

# Global instances
_regime_manager: Optional[SectorRegimeManager] = None
_signal_generator: Optional[SignalGenerator] = None
_trainer: Optional[MarkovTrainer] = None
_retraining = threading.Event()

# Retrain progress tracking
_retrain_progress: Dict[str, Any] = {
    "running": False,
    "progress_pct": 0.0,
    "current_ticker": "",
    "current_action": "",
    "tickers_completed": 0,
    "tickers_total": 0,
    "elapsed_seconds": 0.0,
    "estimated_remaining_seconds": 0.0,
    "started_at": None,
    "model": "",
}
_retrain_progress_lock = threading.Lock()

# Scan progress tracking
_scan_progress: Dict[str, Any] = {
    "running": False,
    "progress_pct": 0.0,
    "current_ticker": "",
    "current_action": "",
    "tickers_completed": 0,
    "tickers_total": 0,
    "elapsed_seconds": 0.0,
    "estimated_remaining_seconds": 0.0,
    "started_at": None,
}
_scan_progress_lock = threading.Lock()


def _get_managers():
    global _regime_manager, _signal_generator, _trainer
    if _regime_manager is None:
        # Use the process-wide shared manager so the screener's regime filter
        # reads the SAME trained state that `train_all` populates here.
        _regime_manager = get_shared_regime_manager()
    if _signal_generator is None:
        _signal_generator = SignalGenerator(_regime_manager)
    if _trainer is None:
        _trainer = MarkovTrainer()
    return _regime_manager, _signal_generator, _trainer


def _models_trained() -> int:
    """Count how many XGBoost model files exist on disk."""
    from pathlib import Path
    model_dir = Path(__file__).resolve().parents[2] / "models" / "markov"
    if not model_dir.exists():
        return 0
    return len(list(model_dir.glob("xgb_*.pkl")))


def _update_scan_progress(
    pct: float,
    ticker: str = "",
    action: str = "",
    completed: int = 0,
    total: int = 0,
    elapsed: float = 0.0,
    eta: float = 0.0,
):
    """Thread-safe update of scan progress."""
    global _scan_progress
    with _scan_progress_lock:
        _scan_progress["running"] = True
        _scan_progress["progress_pct"] = pct
        if ticker:
            _scan_progress["current_ticker"] = ticker
        if action:
            _scan_progress["current_action"] = action
        if completed:
            _scan_progress["tickers_completed"] = completed
        if total:
            _scan_progress["tickers_total"] = total
        if elapsed:
            _scan_progress["elapsed_seconds"] = elapsed
        if eta:
            _scan_progress["estimated_remaining_seconds"] = eta


def _reset_scan_progress():
    """Reset scan progress to idle."""
    global _scan_progress
    with _scan_progress_lock:
        _scan_progress["running"] = False
        _scan_progress["progress_pct"] = 0.0
        _scan_progress["current_ticker"] = ""
        _scan_progress["current_action"] = ""
        _scan_progress["tickers_completed"] = 0
        _scan_progress["tickers_total"] = 0
        _scan_progress["elapsed_seconds"] = 0.0
        _scan_progress["estimated_remaining_seconds"] = 0.0
        _scan_progress["started_at"] = None


def _update_retrain_progress(
    pct: float,
    ticker: str = "",
    action: str = "",
    completed: int = 0,
    total: int = 0,
    elapsed: float = 0.0,
    eta: float = 0.0,
):
    """Thread-safe update of retrain progress."""
    global _retrain_progress
    with _retrain_progress_lock:
        _retrain_progress["running"] = True
        _retrain_progress["progress_pct"] = pct
        if ticker:
            _retrain_progress["current_ticker"] = ticker
        if action:
            _retrain_progress["current_action"] = action
        if completed:
            _retrain_progress["tickers_completed"] = completed
        if total:
            _retrain_progress["tickers_total"] = total
        if elapsed:
            _retrain_progress["elapsed_seconds"] = elapsed
        if eta:
            _retrain_progress["estimated_remaining_seconds"] = eta


def _reset_retrain_progress():
    """Reset retrain progress to idle."""
    global _retrain_progress
    with _retrain_progress_lock:
        _retrain_progress["running"] = False
        _retrain_progress["progress_pct"] = 0.0
        _retrain_progress["current_ticker"] = ""
        _retrain_progress["current_action"] = ""
        _retrain_progress["tickers_completed"] = 0
        _retrain_progress["tickers_total"] = 0
        _retrain_progress["elapsed_seconds"] = 0.0
        _retrain_progress["estimated_remaining_seconds"] = 0.0
        _retrain_progress["started_at"] = None
        _retrain_progress["model"] = ""


def _end_date() -> str:
    """Return the latest available trading day as YYYY-MM-DD."""
    return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')


class ScanRequest(BaseModel):
    tickers: Optional[List[str]] = None  # None = all available
    model: str = "xgboost"
    threshold: float = DEFAULT_BUY_THRESHOLD
    min_conviction: float = 0.6
    max_results: int = 50
    end_date: Optional[str] = None  # YYYY-MM-DD; None = today


class RetrainRequest(BaseModel):
    model: str = "xgboost"  # 'xgboost', 'lstm', or 'all'
    threshold: float = DEFAULT_BUY_THRESHOLD  # BUY/SELL threshold for label generation
    max_tickers: int = 500  # Max tickers to train (matches scan max_results)


@router.get("/status")
async def markov_status():
    """Return model health and cache freshness."""
    rm, sg, tr = _get_managers()
    return {
        "status": "ok",
        "etf_count": len(SECTOR_ETFS),
        "trained_etfs": sum(1 for m in rm.models.values() if m.is_trained),
        "last_updated": rm.last_updated,
        "cached_models": _models_trained(),
        "retraining": _retraining.is_set(),
    }


@router.get("/scan-status")
async def scan_status():
    """Return current scan progress for real-time frontend feedback.

    Auto-detects stale scans: if 'running' has been True for >5 minutes
    without any ticker progress, the backend process likely crashed
    (e.g. from a SIGSEGV in PyTorch LSTM kernels).  The caller should
    treat this as an error rather than hanging indefinitely.
    """
    with _scan_progress_lock:
        stale = False
        if _scan_progress["running"] and _scan_progress["started_at"] is not None:
            elapsed = time.time() - _scan_progress["started_at"]
            if elapsed > 300 and _scan_progress["tickers_completed"] == 0:
                stale = True
        result = dict(_scan_progress)
        result["stale"] = stale
        return result


@router.get("/retrain-status")
async def retrain_status():
    """Return current retrain progress for real-time frontend feedback."""
    with _retrain_progress_lock:
        stale = False
        if _retrain_progress["running"] and _retrain_progress["started_at"] is not None:
            elapsed = time.time() - _retrain_progress["started_at"]
            if elapsed > 600 and _retrain_progress["tickers_completed"] == 0:
                stale = True
        result = dict(_retrain_progress)
        result["stale"] = stale
        return result


@router.post("/scan")
async def scan_tickers(request: ScanRequest):
    """Scan tickers and return ranked convergent signals."""
    import asyncio
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _do_scan, request)
    return result


def _do_scan(request: ScanRequest):
    """Synchronous scan — runs in a thread executor to avoid blocking the event loop."""
    rm, sg, tr = _get_managers()

    end = request.end_date if request.end_date else _end_date()
    _reset_scan_progress()
    _scan_progress["started_at"] = time.time()

    # Train regimes if not done yet, or if end_date changed
    if rm.last_updated is None or (request.end_date and rm.last_updated != request.end_date):
        _update_scan_progress(0, action="Training regime models...")
        start_3y = (datetime.now() - timedelta(days=int(365.25 * 3 + 35))).strftime('%Y-%m-%d')
        rm.train_all(start_3y, end)

    # Build ticker list
    _update_scan_progress(0, action="Building ticker list...")
    if request.tickers is not None and len(request.tickers) > 0:
        ticker_list = []
        for t in request.tickers:
            meta = DataService.get_ticker_metadata(t)
            sector = meta['sector'] if meta else 'Unknown'
            ticker_list.append({'ticker': t.upper(), 'sector': sector})
    else:
        all_tickers = DataService.get_available_tickers()
        ticker_list = []
        for t in all_tickers:
            meta = DataService.get_ticker_metadata(t)
            sector = meta['sector'] if meta else 'Unknown'
            ticker_list.append({'ticker': t, 'sector': sector})

    def _progress(pct, ticker, action, completed, total, elapsed, eta):
        _update_scan_progress(pct, ticker, action, completed, total, elapsed, eta)

    result = sg.scan_tickers(
        ticker_list,
        model=request.model,
        threshold=request.threshold,
        min_conviction=request.min_conviction,
        max_results=request.max_results,
        max_tickers=request.max_results,
        end_date=end,
        progress_callback=_progress,
    )

    result['sector_status'] = rm.get_all_regimes()
    result['cached_models'] = _models_trained()
    result['retraining'] = _retraining.is_set()
    _reset_scan_progress()

    # --- Coach journal hook (failure-isolated) ---
    try:
        from app.services.coach.journal import upsert_strategy, record_strategy_run, record_signal
        strat = upsert_strategy(kind="markov", name=f"markov:daily_scan:{request.model}")
        if strat is not None:
            from datetime import datetime as _dt
            _signals = (result.get("signals") or [])
            run = record_strategy_run(
                strategy_id=strat.id,
                started_at=_dt.utcnow(),
                result_summary={"n_signals": len(_signals), "model": request.model, "end_date": end},
                as_of_date=_dt.fromisoformat(end).date() if isinstance(end, str) else None,
            )
            if run is not None:
                _asof = _dt.fromisoformat(end).date() if isinstance(end, str) else _dt.utcnow().date()
                for _s in _signals[:50]:
                    if not isinstance(_s, dict): continue
                    _tk = _s.get("ticker")
                    if not _tk: continue
                    record_signal(
                        run_id=run.id, ticker=_tk,
                        signal_type=_s.get("action", "hold"),
                        as_of_date=_asof,
                        signal_strength=_s.get("conviction"),
                        payload=_s,
                    )
    except Exception as _e:
        logger.warning("Coach markov /scan hook failed: %s", _e)

    return result


@router.post("/retrain")
async def retrain_models(request: RetrainRequest):
    """Force retrain models on a background thread."""
    rm, sg, tr = _get_managers()

    if _retraining.is_set():
        return {"status": "retraining_already_in_progress"}

    end = _end_date()
    start_3y = (datetime.now() - timedelta(days=int(365.25 * 3 + 35))).strftime('%Y-%m-%d')

    _retraining.set()

    def _run():
        try:
            threading.current_thread().name = "markov-retrain"
            started = time.time()
            _reset_retrain_progress()
            _retrain_progress["started_at"] = started
            _retrain_progress["running"] = True
            _retrain_progress["model"] = request.model

            # Progress callback for trainer
            def _progress(completed: int, total: int, ticker: str):
                pct = (completed / total * 100) if total > 0 else 0
                elapsed = time.time() - started
                eta = (elapsed / completed * (total - completed)) if completed > 0 else 0
                label = "XGBoost" if _retrain_progress["model"] in ("xgboost", "all") else "LSTM"
                _update_retrain_progress(
                    pct=pct,
                    ticker=ticker,
                    action=f"Training {label} model...",
                    completed=completed,
                    total=total,
                    elapsed=elapsed,
                    eta=eta,
                )

            logger.info("Background retrain: training regimes...")
            _update_retrain_progress(0, action="Training regime models...")
            rm.train_all(start_3y, end)

            if request.model in ("xgboost", "all"):
                all_tickers = DataService.get_available_tickers()
                n_tickers = min(request.max_tickers, len(all_tickers))
                logger.info(f"Background retrain: training XGBoost for {n_tickers} tickers...")
                _update_retrain_progress(0, ticker="", action=f"Training XGBoost for {n_tickers} tickers...")
                tr.train_xgboost(
                    all_tickers[:n_tickers],
                    buy_threshold=request.threshold,
                    sell_threshold=-request.threshold,
                    progress_callback=_progress,
                )

            if request.model in ("lstm", "all") and date.today().month in (1, 4, 7, 10):
                all_tickers = DataService.get_available_tickers()
                n_tickers = min(request.max_tickers, len(all_tickers))
                logger.info(f"Background retrain: training LSTM for {n_tickers} tickers...")
                _update_retrain_progress(0, ticker="", action=f"Training LSTM for {n_tickers} tickers...")
                tr.train_lstm(
                    all_tickers[:n_tickers],
                    buy_threshold=request.threshold,
                    sell_threshold=-request.threshold,
                    progress_callback=_progress,
                )

            logger.info("Background retrain complete.")
        except Exception as e:
            logger.error(f"Background retrain failed: {e}", exc_info=True)
        finally:
            _retraining.clear()
            _reset_retrain_progress()
            # --- Coach journal hook (failure-isolated) ---
            try:
                from app.services.coach.journal import upsert_strategy, record_strategy_run
                _duration = time.time() - started
                strat = upsert_strategy(kind="markov", name=f"markov:retrain:{request.model}")
                if strat is not None:
                    from datetime import datetime as _dt
                    record_strategy_run(
                        strategy_id=strat.id,
                        started_at=_dt.utcnow(),
                        result_summary={"source": "markov.retrain", "model": request.model, "duration_s": _duration},
                    )
            except Exception as _e:
                logger.warning("Coach markov /retrain hook failed: %s", _e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return {
        "status": "retraining_started",
        "model": request.model,
        "note": "Models are training in the background. Check /api/markov/status to monitor progress.",
    }


@router.get("/regimes")
async def get_regimes():
    """Get current regime state for all sector ETFs."""
    rm, _, _ = _get_managers()
    return {"sector_status": rm.get_all_regimes()}