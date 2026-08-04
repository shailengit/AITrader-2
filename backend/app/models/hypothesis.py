import uuid
from sqlalchemy import Column, String, Text, DateTime, Enum as SAEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.db.database import Base


class HypothesisSource(str, enum.Enum):
    sectors = "sectors"
    screener = "screener"
    markov = "markov"
    coach = "coach"
    manual = "manual"


class HypothesisStatus(str, enum.Enum):
    open = "open"
    generated = "generated"
    archived = "archived"


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(SAEnum(HypothesisSource, name="hypothesis_source"), nullable=False)
    ticker = Column(String, nullable=True)
    sector = Column(String, nullable=True)
    regime = Column(String, nullable=True)
    conviction = Column(String, nullable=True)  # store as text to avoid float rounding
    why = Column(Text, nullable=False)
    context = Column(JSONB, nullable=True)
    status = Column(SAEnum(HypothesisStatus, name="hypothesis_status"),
                    nullable=False, default=HypothesisStatus.open)
    source_meta = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    generated_strategy_id = Column(UUID(as_uuid=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Hypothesis {self.id} {self.source} {self.status}>"
