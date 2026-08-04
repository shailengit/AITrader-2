from app.models.deployment import Deployment, DeploymentStatus

def test_deployment_status_enum():
    assert DeploymentStatus.active.value == "active"
    assert DeploymentStatus.paused.value == "paused"
    assert DeploymentStatus.retired.value == "retired"
    assert DeploymentStatus.failed.value == "failed"

def test_deployment_required_columns():
    d = Deployment(
        strategy_path="strategies/test.py",
        status=DeploymentStatus.active,
        params_json={"foo": 1},
        metrics_snapshot={"sharpe": 1.4},
    )
    assert d.strategy_path == "strategies/test.py"
    assert d.status == DeploymentStatus.active
