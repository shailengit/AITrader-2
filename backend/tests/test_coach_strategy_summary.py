from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.services.deployments_registry import deploy_strategy
from app.models.journal import JournalStrategy, JournalTrade

client = TestClient(app)


def test_summary_for_unknown_strategy_returns_backtested_fallback():
    r = client.get("/api/coach/strategy/strategies/unknown.py/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["strategy_path"] == "strategies/unknown.py"
    assert body["is_deployed"] is False
    assert body["n_live_trades"] == 0


def test_summary_for_deployed_strategy_returns_live_data(db_session):
    """End-to-end: seed an active deployment + journal strategy + a winning fill,
    then assert the summary surfaces live data (not the backtested fallback)."""
    from app.models.deployment import Deployment, DeploymentStatus

    strategy_path = "strategies/_test_dummy.py"
    stem = "_test_dummy"

    # 1. Active deployment for this strategy path.
    deploy_strategy(strategy_path=strategy_path, params={}, metrics_snapshot={}, db=db_session)

    # 2. JournalStrategy keyed by file stem (matches the endpoint's mapping).
    strategy = JournalStrategy(kind="quantgen", name=stem, params={})
    db_session.add(strategy)
    db_session.commit()
    db_session.refresh(strategy)

    # 3. A couple of live fills with positive P&L.
    fills = [
        JournalTrade(
            strategy_id=strategy.id, ticker="AAPL", side="long", qty=10,
            entry_px=100.0, exit_px=150.0, pnl=500.0, pnl_pct=0.5,
            entry_at=datetime.utcnow(), exit_at=datetime.utcnow(),
            regime_at_entry="BULL", regime_at_exit="BULL",
        ),
        JournalTrade(
            strategy_id=strategy.id, ticker="MSFT", side="long", qty=10,
            entry_px=200.0, exit_px=180.0, pnl=-200.0, pnl_pct=-0.1,
            entry_at=datetime.utcnow(), exit_at=datetime.utcnow(),
            regime_at_entry="BEAR", regime_at_exit="BEAR",
        ),
    ]
    db_session.add_all(fills)
    db_session.commit()

    r = client.get(f"/api/coach/strategy/{strategy_path}/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["strategy_path"] == strategy_path
    assert body["is_deployed"] is True
    assert body["deployed_at"] is not None
    assert body["n_live_trades"] >= 1
    assert body["live_pnl"] > 0  # 500 - 200 = 300
    assert body["current_regime"] in ("BULL", "BEAR")
    assert "BULL" in body["regime_attribution"]
    assert body["backtested"] == {}  # live path, not the backtested fallback

    # Cleanup journal rows the test created (conftest only cleans deployments).
    db_session.execute(
        text("DELETE FROM journal_trade WHERE strategy_id = :sid"), {"sid": str(strategy.id)}
    )
    db_session.execute(
        text("DELETE FROM journal_strategy WHERE id = :sid"), {"sid": str(strategy.id)}
    )
    db_session.commit()
