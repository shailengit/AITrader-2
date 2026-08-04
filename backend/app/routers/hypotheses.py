from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.db.database import SessionLocal
from app.services.hypothesis_service import (
    create_hypothesis,
    list_hypotheses,
    mark_generated,
    archive_hypothesis,
)

router = APIRouter(prefix="/hypotheses", tags=["Hypotheses"])


class CreateHypothesisRequest(BaseModel):
    source: str
    why: str
    ticker: Optional[str] = None
    sector: Optional[str] = None
    regime: Optional[str] = None
    conviction: Optional[float] = None
    context: Optional[dict] = None
    source_meta: Optional[dict] = None


@router.post("", status_code=201)
def create(req: CreateHypothesisRequest):
    db = SessionLocal()
    try:
        h = create_hypothesis(
            source=req.source, why=req.why,
            ticker=req.ticker, sector=req.sector,
            regime=req.regime, conviction=req.conviction,
            context=req.context, source_meta=req.source_meta,
            db=db,
        )
        return {
            "id": str(h.id),
            "source": h.source.value,
            "why": h.why,
            "status": h.status.value,
            "created_at": h.created_at.isoformat(),
            "ticker": h.ticker,
            "sector": h.sector,
            "regime": h.regime,
        }
    finally:
        db.close()


@router.get("")
def list_(status: Optional[str] = Query(None), source: Optional[str] = Query(None),
          limit: int = Query(50, le=200)):
    db = SessionLocal()
    try:
        rows = list_hypotheses(status=status, source=source, limit=limit, db=db)
        return [{
            "id": str(h.id),
            "source": h.source.value,
            "why": h.why,
            "status": h.status.value,
            "created_at": h.created_at.isoformat(),
            "ticker": h.ticker,
            "sector": h.sector,
            "regime": h.regime,
            "generated_strategy_id": str(h.generated_strategy_id) if h.generated_strategy_id else None,
        } for h in rows]
    finally:
        db.close()


class UpdateRequest(BaseModel):
    status: Optional[str] = None
    generated_strategy_id: Optional[str] = None


@router.patch("/{hypothesis_id}")
def update(hypothesis_id: str, req: UpdateRequest):
    db = SessionLocal()
    try:
        if req.status == "generated" and req.generated_strategy_id:
            h = mark_generated(hypothesis_id, req.generated_strategy_id, db)
        elif req.status == "archived":
            h = archive_hypothesis(hypothesis_id, db)
        else:
            raise HTTPException(400, "unsupported status transition")
        if h is None:
            raise HTTPException(404)
        return {"id": str(h.id), "status": h.status.value}
    finally:
        db.close()
