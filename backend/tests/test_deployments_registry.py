from app.services.deployments_registry import (
    get_active_deployment,
    deploy_strategy,
    rollback_deployment,
)
from app.models.deployment import Deployment, DeploymentStatus


def test_deploy_strategy_writes_active_row(db_session, sample_strategy_path):
    d = deploy_strategy(
        strategy_path=sample_strategy_path,
        params={"window": 50},
        metrics_snapshot={"sharpe": 1.2},
        db=db_session,
    )
    assert d.status == DeploymentStatus.active
    active = get_active_deployment(db=db_session)
    assert active is not None
    assert active.id == d.id


def test_rollback_marks_previous_retired(db_session, sample_strategy_path):
    d1 = deploy_strategy(sample_strategy_path, {}, {}, db=db_session)
    d2 = deploy_strategy(sample_strategy_path, {}, {}, db=db_session)
    assert get_active_deployment(db=db_session).id == d2.id
    rollback_deployment(d2.id, db=db_session)
    active = get_active_deployment(db=db_session)
    assert active.id == d1.id
    assert active.status == DeploymentStatus.active
