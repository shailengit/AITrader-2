"""Coach API router: metrics, trades CRUD, strategies, reports."""
from __future__ import annotations
import logging
import uuid
from datetime import date as date_cls, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
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


# ---------- metrics ----------

@router.get("/metrics/overview")
def metrics_overview(
    period_start: Optional[date_cls] = None,
    period_end: Optional[date_cls] = None,
    strategy_id: Optional[uuid.UUID] = None,
    strategy_path: Optional[str] = None,
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
    o = A.overview(session, start, end, strategy_id)
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
    bundle = build_bundle(session, start, end, body.strategy_id)
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
