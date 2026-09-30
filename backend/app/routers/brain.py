"""Trading Brain API router: chat, strategy stats, insights.

The Brain answers questions about a strategy's accumulated backtest experiment
data (per-strategy or global), detects patterns, and persists chat history.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services import brain_service as B

router = APIRouter(prefix="/brain", tags=["Trading Brain"])


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    strategy_class_path: Optional[str] = None
    run_ids: Optional[List[str]] = None
    compare_strategy: Optional[str] = None
    model: Optional[str] = None


@router.post("/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    """Answer a question using the accumulated experiment data."""
    if not body.question.strip():
        raise HTTPException(400, "question is required")
    result = B.chat(
        db,
        question=body.question.strip(),
        strategy_class_path=body.strategy_class_path,
        run_ids=body.run_ids,
        compare_strategy=body.compare_strategy,
        model=body.model,
    )
    if result.get("error") == "llm_unavailable":
        raise HTTPException(503, detail={"error": "llm_unavailable", "message": "LLM client unavailable"})
    if result.get("error"):
        raise HTTPException(500, detail={"error": result["error"]})
    return result


@router.get("/chat")
def get_chat(
    strategy_class_path: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List chat history for a strategy (or global if no strategy)."""
    return B.list_chat(db, strategy_class_path, limit)


@router.get("/strategies")
def list_strategies(db: Session = Depends(get_db)):
    """List all strategies that have experiments, with accumulated stats."""
    return B.list_strategies_with_stats(db)


@router.get("/strategy/{strategy_class_path:path}")
def get_strategy_brain(strategy_class_path: str, db: Session = Depends(get_db)):
    """Get a strategy's brain (insights, stats, best/worst run)."""
    brain = B.get_brain(db, strategy_class_path)
    if brain is None:
        # Not analyzed yet — return the raw stats bundle so the UI still works.
        bundle = B.build_strategy_bundle(db, strategy_class_path)
        return {"strategy_name": bundle["strategy_name"], "analyzed": False,
                "n_runs": bundle["n_runs"], "n_trades": bundle["n_trades"],
                "runs": bundle["runs"], "aggregate": bundle["aggregate"]}
    return brain


@router.post("/strategy/{strategy_class_path:path}/analyze")
def analyze_strategy(strategy_class_path: str, db: Session = Depends(get_db)):
    """Aggregate all accumulated data for a strategy and detect patterns."""
    return B.analyze_strategy(db, strategy_class_path)
