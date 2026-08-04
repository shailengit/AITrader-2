from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models.deployment import Deployment, DeploymentStatus


def get_active_deployment(db: Session) -> Optional[Deployment]:
    return (
        db.query(Deployment)
        .filter(Deployment.status == DeploymentStatus.active)
        .order_by(Deployment.deployed_at.desc())
        .first()
    )


def deploy_strategy(
    strategy_path: str,
    params: Dict[str, Any],
    metrics_snapshot: Dict[str, Any],
    db: Session,
) -> Deployment:
    # Mark any existing active deployment as retired (chain for rollback)
    existing = get_active_deployment(db)
    if existing is not None:
        existing.status = DeploymentStatus.retired

    d = Deployment(
        strategy_path=strategy_path,
        status=DeploymentStatus.active,
        parent_id=existing.id if existing else None,
        params_json=params,
        metrics_snapshot=metrics_snapshot,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def rollback_deployment(deployment_id: str, db: Session) -> Optional[Deployment]:
    """Mark the given deployment as failed and reactivate its parent (if any)."""
    current = db.query(Deployment).filter_by(id=deployment_id).first()
    if current is None:
        return None
    current.status = DeploymentStatus.failed

    if current.parent_id is not None:
        parent = db.query(Deployment).filter_by(id=current.parent_id).first()
        if parent is not None:
            parent.status = DeploymentStatus.active
            db.commit()
            return parent

    db.commit()
    return None
