"""Coach API router: metrics, trades CRUD, strategies, reports."""
from __future__ import annotations
import logging
import uuid
from datetime import date as date_cls, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.journal import JournalTrade, JournalStrategy, JournalCoachReport
from app.services.coach import analytics as A
from app.services.coach.journal import upsert_strategy
from app.services.coach.bundle import build as build_bundle
from app.services.coach.llm import generate_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coach", tags=["coach"])


# ---------- shared deps ----------

def get_session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _period(start: Optional[date_cls], end: Optional[date_cls]) -> tuple[date_cls, date_cls]:
    if end is None:
        end = date_cls.today()
    if start is None:
        start = end - timedelta(days=30)
    return start, end


# ---------- request/response models ----------

class TradeCreate(BaseModel):
    ticker: str
    side: str = Field("long", pattern="^(long|short)$")
    qty: float
    entry_px: float
    entry_at: datetime
    strategy_id: Optional[uuid.UUID] = None
    signal_id: Optional[uuid.UUID] = None
    stop_px: Optional[float] = None
    target_px: Optional[float] = None
    notes: Optional[str] = None


class TradePatch(BaseModel):
    stop_px: Optional[float] = None
    target_px: Optional[float] = None
    notes: Optional[str] = None


class TradeClose(BaseModel):
    exit_px: Optional[float] = None  # if None, use today's close
    exit_at: Optional[datetime] = None


class StrategyCreate(BaseModel):
    kind: str = Field(..., pattern="^(screener|quantgen|markov|manual)$")
    name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None


class StrategyPatch(BaseModel):
    notes: Optional[str] = None
    retired_at: Optional[datetime] = None
    params: Optional[Dict[str, Any]] = None


class ReportRequest(BaseModel):
    period_start: Optional[date_cls] = None
    period_end: Optional[date_cls] = None
    strategy_id: Optional[uuid.UUID] = None
    model: Optional[str] = None
    source: Optional[str] = None


# ---------- metrics ----------

@router.get("/metrics/overview")
def metrics_overview(
    period_start: Optional[date_cls] = None,
    period_end: Optional[date_cls] = None,
    strategy_id: Optional[uuid.UUID] = None,
    strategy_path: Optional[str] = None,
    source: Optional[str] = Query(None, pattern="^(live|backtest)$"),
    session: Session = Depends(get_session),
):
    start, end = _period(period_start, period_end)
    if strategy_path:
        # The Command Center links to /coach?strategy=<path> (a strategy FILE
        # path, e.g. "strategies/golden_cross.py"). Resolve it to the tracked
        # JournalStrategy id so the overview is actually filtered, not just
        # visually. An unresolvable path yields an empty overview.
        from app.services.coach.journal import _resolve_strategy
        row = _resolve_strategy(strategy_path, session)
        if row is None:
            return {
                "empty": True,
                "period": {"start": start.isoformat(), "end": end.isoformat()},
                "kpis": {
                    "total_pnl": 0.0, "win_rate": 0.0, "expectancy": 0.0,
                    "n_trades": 0, "n_open": 0, "max_dd": 0.0, "current_dd": 0.0,
                    "sharpe_proxy": 0.0,
                },
            }
        strategy_id = row.id
    o = A.overview(session, start, end, strategy_id, source)
    # For backtest source, the journaled dollar P&L is a meaningless cross-run
    # sum (each run is its own $100k). Override KPIs with per-run % returns
    # from backtest_analysis.run_summary so the cards show median/best/worst %
    # return instead of a bogus dollar figure.
    if source == "backtest":
        bk = A.backtest_kpis(session, strategy_id, source)
        if bk is not None:
            o["kpis"] = bk
    if o["kpis"]["n_trades"] == 0 and not o["win_rate_by_strategy"]:
        return {"empty": True, "period": o["period"], "kpis": o["kpis"]}
    return o


@router.get("/metrics/mae-mfe")
def metrics_mae_mfe(
    period_start: Optional[date_cls] = None,
    period_end: Optional[date_cls] = None,
    strategy_id: Optional[uuid.UUID] = None,
    session: Session = Depends(get_session),
):
    start, end = _period(period_start, period_end)
    return A.mae_mfe_scatter(session, start, end, strategy_id)


@router.get("/metrics/win-rate-by-strategy")
def metrics_win_rate_by_strategy(
    period_start: Optional[date_cls] = None,
    period_end: Optional[date_cls] = None,
    session: Session = Depends(get_session),
):
    start, end = _period(period_start, period_end)
    return A.win_rate_by_strategy(session, start, end)


# ---------- trades ----------

@router.get("/trades")
def list_trades(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    strategy_id: Optional[uuid.UUID] = None,
    open_only: bool = False,
    session: Session = Depends(get_session),
):
    q = session.query(JournalTrade)
    if strategy_id is not None:
        q = q.filter(JournalTrade.strategy_id == strategy_id)
    if open_only:
        q = q.filter(JournalTrade.exit_at.is_(None))
    q = q.order_by(JournalTrade.entry_at.desc())
    total = q.count()
    rows = q.offset(offset).limit(limit).all()
    return {"total": total, "rows": [t.to_dict() for t in rows]}


@router.post("/trades", status_code=201)
def create_trade(body: TradeCreate, session: Session = Depends(get_session)):
    t = JournalTrade(
        ticker=body.ticker.upper(), side=body.side, qty=body.qty,
        entry_px=body.entry_px, entry_at=body.entry_at,
        strategy_id=body.strategy_id, signal_id=body.signal_id,
        stop_px=body.stop_px, target_px=body.target_px, notes=body.notes,
    )
    session.add(t); session.commit(); session.refresh(t)
    return t.to_dict()


@router.patch("/trades/{trade_id}")
def patch_trade(trade_id: uuid.UUID, body: TradePatch, session: Session = Depends(get_session)):
    t = session.get(JournalTrade, trade_id)
    if t is None:
        raise HTTPException(404, "trade not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    t.updated_at = datetime.utcnow()
    session.commit(); session.refresh(t)
    return t.to_dict()


@router.delete("/trades/{trade_id}", status_code=204)
def delete_trade(trade_id: uuid.UUID, session: Session = Depends(get_session)):
    t = session.get(JournalTrade, trade_id)
    if t is None:
        raise HTTPException(404, "trade not found")
    session.delete(t); session.commit()
    return None


@router.post("/trades/{trade_id}/close")
def close_trade(trade_id: uuid.UUID, body: TradeClose, session: Session = Depends(get_session)):
    from app.services.data_service import DataService
    t = session.get(JournalTrade, trade_id)
    if t is None:
        raise HTTPException(404, "trade not found")
    if t.exit_at is not None:
        raise HTTPException(400, "trade already closed")
    # Default exit price = today's close
    exit_px = body.exit_px
    exit_at = body.exit_at or datetime.utcnow()
    if exit_px is None:
        latest = DataService.get_latest_price(t.ticker, "daily")
        if latest is None:
            raise HTTPException(503, f"no price data for {t.ticker}")
        exit_px = float(latest)
    sign = 1 if t.side == "long" else -1
    t.exit_px = exit_px
    t.exit_at = exit_at
    t.pnl = (exit_px - float(t.entry_px)) * float(t.qty) * sign
    t.pnl_pct = (exit_px - float(t.entry_px)) / float(t.entry_px) * sign
    # MAE/MFE from OHLCV
    try:
        ohlcv = DataService.get_ohlcv_data(t.ticker, t.entry_at.date().isoformat(), exit_at.date().isoformat())
        if ohlcv is not None and not ohlcv.empty:
            low_min = float(ohlcv["Low"].min())
            high_max = float(ohlcv["High"].max())
            t.mae = (low_min - float(t.entry_px)) * sign
            t.mfe = (high_max - float(t.entry_px)) * sign
    except Exception as e:
        logger.warning("MAE/MFE calc failed for trade %s: %s", trade_id, e)
    t.updated_at = datetime.utcnow()
    session.commit(); session.refresh(t)
    return t.to_dict()


# ---------- strategies ----------

@router.get("/strategies")
def list_strategies(session: Session = Depends(get_session)):
    rows = session.query(JournalStrategy).order_by(JournalStrategy.created_at.desc()).all()
    return [r.to_dict() for r in rows]


@router.post("/strategies", status_code=201)
def create_strategy(body: StrategyCreate, session: Session = Depends(get_session)):
    row = upsert_strategy(kind=body.kind, name=body.name, params=body.params, notes=body.notes, session=session)
    if row is None:
        raise HTTPException(500, "failed to upsert strategy")
    session.commit()
    session.refresh(row)
    return row.to_dict()


@router.patch("/strategies/{strategy_id}")
def patch_strategy(strategy_id: uuid.UUID, body: StrategyPatch, session: Session = Depends(get_session)):
    row = session.get(JournalStrategy, strategy_id)
    if row is None:
        raise HTTPException(404, "strategy not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    session.commit(); session.refresh(row)
    return row.to_dict()


# ---------- reports ----------

@router.post("/report")
def post_report(body: ReportRequest, session: Session = Depends(get_session)):
    start, end = _period(body.period_start, body.period_end)
    bundle = build_bundle(session, start, end, body.strategy_id, body.source)
    # If there are no closed trades to analyze, don't ask the LLM to critique an
    # empty dataset (it invents numbers and fails validation). Return a clear
    # "no data" response instead of a confusing 422.
    if bundle["kpis"]["n_trades"] == 0 and not bundle["win_rate_by_strategy"]:
        return {
            "id": None,
            "markdown": None,
            "metrics": bundle["kpis"],
            "model_id": "",
            "duration_ms": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "bundle": bundle,
            "empty": True,
            "message": f"No closed {body.source or 'live'} trades in this period to analyze. Run a backtest or close some positions first.",
        }
    result = generate_report(session, bundle, model=body.model)
    if result.error and result.error.startswith("llm_unavailable"):
        raise HTTPException(503, detail={"error": "llm_unavailable", "bundle": bundle, "details": result.error})
    if result.error == "llm_invented_numbers":
        raise HTTPException(422, detail={"error": "llm_invented_numbers", "bundle": bundle})
    if result.error:
        raise HTTPException(500, detail={"error": result.error})
    return {
        "id": result.report_id,
        "markdown": result.markdown,
        "metrics": result.metrics,
        "model_id": result.model_id,
        "duration_ms": result.duration_ms,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "bundle": bundle,
    }


@router.get("/reports")
def list_reports(limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)):
    rows = (session.query(JournalCoachReport)
            .order_by(JournalCoachReport.generated_at.desc()).limit(limit).all())
    return [{
        "id": str(r.id),
        "generated_at": r.generated_at.isoformat(),
        "period_start": r.period_start.isoformat(),
        "period_end": r.period_end.isoformat(),
        "strategy_id": str(r.strategy_id) if r.strategy_id else None,
        "model_id": r.model_id,
        "duration_ms": r.duration_ms,
    } for r in rows]


@router.get("/reports/{report_id}")
def get_report(report_id: uuid.UUID, session: Session = Depends(get_session)):
    r = session.get(JournalCoachReport, report_id)
    if r is None:
        raise HTTPException(404, "report not found")
    return {
        "id": str(r.id),
        "generated_at": r.generated_at.isoformat(),
        "period_start": r.period_start.isoformat(),
        "period_end": r.period_end.isoformat(),
        "strategy_id": str(r.strategy_id) if r.strategy_id else None,
        "model_id": r.model_id,
        "report_md": r.report_md,
        "metrics": r.metrics,
        "bundle": r.bundle,
        "prompt_tokens": r.prompt_tokens,
        "completion_tokens": r.completion_tokens,
        "duration_ms": r.duration_ms,
    }


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: uuid.UUID, session: Session = Depends(get_session)):
    r = session.get(JournalCoachReport, report_id)
    if r is None:
        raise HTTPException(404, "report not found")
    session.delete(r); session.commit()
    return None


# ---------- backtest analyses (AI learnings from batch per-trade data) ----------

@router.get("/backtest-analyses")
def list_backtest_analyses(
    strategy_name: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
):
    """List AI backtest learnings, newest first, optionally filtered by strategy."""
    from app.models.backtest_analysis import BacktestAnalysis
    q = session.query(BacktestAnalysis)
    if strategy_name:
        q = q.filter(BacktestAnalysis.strategy_name == strategy_name)
    rows = q.order_by(BacktestAnalysis.created_at.desc()).limit(limit).all()
    return [{
        "id": str(r.id),
        "strategy_name": r.strategy_name,
        "strategy_class_path": r.strategy_class_path,
        "batch_id": r.batch_id,
        "report_path": r.report_path,
        "run_summary": r.run_summary,
        "analysis_md": r.analysis_md,
        "suggestions": r.suggestions,
        "model_id": r.model_id,
        "n_runs": r.n_runs,
        "n_completed": r.n_completed,
        "n_trades": r.n_trades,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@router.get("/backtest-analyses/{analysis_id}")
def get_backtest_analysis(analysis_id: uuid.UUID, session: Session = Depends(get_session)):
    from app.models.backtest_analysis import BacktestAnalysis
    r = session.get(BacktestAnalysis, analysis_id)
    if r is None:
        raise HTTPException(404, "analysis not found")
    return {
        "id": str(r.id),
        "strategy_name": r.strategy_name,
        "strategy_class_path": r.strategy_class_path,
        "batch_id": r.batch_id,
        "report_path": r.report_path,
        "run_summary": r.run_summary,
        "analysis_md": r.analysis_md,
        "suggestions": r.suggestions,
        "model_id": r.model_id,
        "n_runs": r.n_runs,
        "n_completed": r.n_completed,
        "n_trades": r.n_trades,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/backtest-analyses/{analysis_id}/runs")
def get_backtest_analysis_runs(analysis_id: uuid.UUID, session: Session = Depends(get_session)):
    """Return per-run %-return equity curves for an analysis's backtest batch.

    Reads each run's authentic per-day portfolio value from
    strategy_experiments.equity_curve (which starts at 100k per run), converts
    to cumulative % return, and returns one series per completed run. This
    matches what Strategy Lab shows — unlike the old cross-run dollar merge,
    which summed position-sized P&L across independent runs into a meaningless
    ±billions figure.
    """
    from app.models.backtest_analysis import BacktestAnalysis
    from app.models.strategy_lab import StrategyExperiment

    r = session.get(BacktestAnalysis, analysis_id)
    if r is None:
        raise HTTPException(404, "analysis not found")
    if not r.batch_id:
        raise HTTPException(404, "no batch_id for this analysis")

    runs = (
        session.query(StrategyExperiment)
        .filter(StrategyExperiment.batch_id == r.batch_id, StrategyExperiment.status == "completed")
        .order_by(StrategyExperiment.run_index.asc())
        .all()
    )
    if not runs:
        # The batch's experiments exist but none carry an equity_curve; return empty.
        return {"strategy_name": r.strategy_name, "runs": []}

    out_runs = []
    for exp in runs:
        ec = exp.equity_curve if exp.equity_curve else []
        # ec is [{date, value, ...}] with value = portfolio value starting at ~100k.
        initial = None
        points = []
        for pt in ec:
            val = pt.get("value")
            if val is None:
                continue
            if initial is None:
                initial = float(val) if float(val) > 0 else 100_000.0
            if initial <= 0:
                continue
            pct = (float(val) / initial - 1.0) * 100.0
            points.append({"date": pt.get("date"), "pct_return": round(pct, 2)})
        out_runs.append({
            "run_index": exp.run_index,
            "start_date": exp.start_date.isoformat() if exp.start_date else None,
            "end_date": exp.end_date.isoformat() if exp.end_date else None,
            "total_return_pct": (exp.kpis or {}).get("total_return_pct"),
            "curve": points,
        })

    return {"strategy_name": r.strategy_name, "runs": out_runs}


@router.get("/backtest-analyses/{analysis_id}/report")
def get_backtest_analysis_report(analysis_id: uuid.UUID, session: Session = Depends(get_session)):
    """Return the HTML report content for an analysis, for in-app rendering.

    The report_path stored on the analysis is a servable /api URL. We resolve
    it to the actual file and return the raw HTML so the frontend can render it
    in an iframe (fetching with the API token avoids the 401 a plain link hits).
    """
    from pathlib import Path
    from app.services.run_viewer_generator import REPORTS_DIR
    from app.models.backtest_analysis import BacktestAnalysis

    r = session.get(BacktestAnalysis, analysis_id)
    if r is None:
        raise HTTPException(404, "analysis not found")
    if not r.report_path:
        raise HTTPException(404, "no report for this analysis")

    # report_path is like /api/strategy-lab/reports/<filename> — take the basename
    # and URL-decode it (spaces are stored as %20) to match the on-disk filename.
    from urllib.parse import unquote
    filename = unquote(Path(r.report_path).name)
    filepath = REPORTS_DIR / filename
    if not filepath.exists() or filepath.suffix.lower() != ".html":
        raise HTTPException(404, "report file not found")
    return Response(content=filepath.read_text(encoding="utf-8"), media_type="text/html")


@router.delete("/backtest-analyses/{analysis_id}", status_code=204)
def delete_backtest_analysis(analysis_id: uuid.UUID, session: Session = Depends(get_session)):
    """Delete a backtest analysis row (and its linked experiment batch).

    Lets the user remove a stale/duplicate experiment from the Coach's backtest
    tab. Deletes the analysis row and, if its batch_id isn't shared by another
    analysis, the linked strategy_experiments rows for that batch too.
    """
    from app.models.backtest_analysis import BacktestAnalysis
    from app.models.strategy_lab import StrategyExperiment

    r = session.get(BacktestAnalysis, analysis_id)
    if r is None:
        raise HTTPException(404, "analysis not found")

    batch_id = r.batch_id
    session.delete(r)
    session.flush()

    # Only delete the experiment batch if no OTHER analysis references it.
    if batch_id:
        still_used = (
            session.query(BacktestAnalysis)
            .filter(BacktestAnalysis.batch_id == batch_id, BacktestAnalysis.id != analysis_id)
            .first()
        )
        if still_used is None:
            session.query(StrategyExperiment).filter(StrategyExperiment.batch_id == batch_id).delete(
                synchronize_session=False
            )
    session.commit()
    return None
