import uuid
from sqlalchemy import Column, String, DateTime, Enum as SAEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime
import enum

from app.db.database import Base


class DeploymentStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    retired = "retired"
    failed = "failed"


class Deployment(Base):
    __tablename__ = "deployments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_path = Column(String, nullable=False)
    deployed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(SAEnum(DeploymentStatus, name="deployment_status"),
                    nullable=False, default=DeploymentStatus.active)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("deployments.id"), nullable=True)
    params_json = Column(JSONB, nullable=True)
    metrics_snapshot = Column(JSONB, nullable=True)
