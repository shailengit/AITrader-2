from typing import Optional, List
import uuid
from sqlalchemy.orm import Session

from app.models.hypothesis import Hypothesis, HypothesisSource, HypothesisStatus


def create_hypothesis(
    source: str,
    why: str,
    ticker: Optional[str] = None,
    sector: Optional[str] = None,
    regime: Optional[str] = None,
    conviction: Optional[float] = None,
    context: Optional[dict] = None,
    source_meta: Optional[dict] = None,
    db: Session = None,
) -> Hypothesis:
    h = Hypothesis(
        source=HypothesisSource(source),
        why=why,
        ticker=ticker,
        sector=sector,
        regime=regime,
        conviction=str(conviction) if conviction is not None else None,
        context=context,
        source_meta=source_meta,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def list_hypotheses(
    status: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
    db: Session = None,
) -> List[Hypothesis]:
    q = db.query(Hypothesis)
    if status:
        q = q.filter(Hypothesis.status == HypothesisStatus(status))
    if source:
        q = q.filter(Hypothesis.source == HypothesisSource(source))
    return q.order_by(Hypothesis.created_at.desc()).limit(limit).all()


def mark_generated(hypothesis_id, strategy_id: str, db: Session) -> Optional[Hypothesis]:
    h = db.query(Hypothesis).filter_by(id=hypothesis_id).first()
    if h is None:
        return None
    h.status = HypothesisStatus.generated
    h.generated_strategy_id = uuid.UUID(strategy_id) if isinstance(strategy_id, str) else strategy_id
    db.commit()
    db.refresh(h)
    return h


def archive_hypothesis(hypothesis_id, db: Session) -> Optional[Hypothesis]:
    h = db.query(Hypothesis).filter_by(id=hypothesis_id).first()
    if h is None:
        return None
    h.status = HypothesisStatus.archived
    db.commit()
    db.refresh(h)
    return h
