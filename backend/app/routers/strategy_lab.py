"""AI Strategy Builder router — sessions CRUD + Ollama model list.

Phase 1 scope: no LLM calls, no experiment orchestration, no deploy.
Those land in Phases 2-4. This router establishes the foundation.
"""
import asyncio
import json
import logging
import threading
import uuid
from typing import List, Optional, Any, Dict

from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.strategy_lab import StrategySession
from app.services.deployments_registry import deploy_strategy as registry_deploy
from app.services.strategy_lab_models import list_ollama_models
from app.services.strategy_lab_session import (
    create_session as svc_create_session,
    get_session as svc_get_session,
    list_sessions as svc_list_sessions,
    update_session as svc_update_session,
    delete_session as svc_delete_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategy-lab", tags=["AI Strategy Builder"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Pydantic models ──────────────────────────────────────────────────────

class VariantResponse(BaseModel):
    name: str
    type: str  # "cloud" or "local"
    size_bytes: Optional[int] = None


class ModelResponse(BaseModel):
    id: str
    variants: List[VariantResponse]


class SessionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)
    tags: List[str] = Field(default_factory=list)


class SessionUpdate(BaseModel):
    plan_text: Optional[str] = None
    code_text: Optional[str] = None
    tags: Optional[List[str]] = None
    name: Optional[str] = None


class SessionResponse(BaseModel):
    id: str
    name: str
    prompt: str
    plan_text: Optional[str] = None
    code_text: Optional[str] = None
    model_id: str
    tags: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/models", response_model=List[ModelResponse])
def get_models():
    """List all available Ollama models from the local manifest directory."""
    raw = list_ollama_models()
    return [
        ModelResponse(
            id=m["id"],
            variants=[VariantResponse(**v) for v in m["variants"]],
        )
        for m in raw
    ]


@router.post("/sessions", response_model=SessionResponse, status_code=201)
def post_session(body: SessionCreate, db: Session = Depends(get_db)):
    """Create a new strategy session."""
    sess = svc_create_session(
        db,
        name=body.name,
        prompt=body.prompt,
        model_id=body.model_id,
        tags=body.tags,
    )
    return SessionResponse(**sess.to_dict())


@router.get("/sessions", response_model=List[SessionResponse])
def get_sessions(
    search: Optional[str] = Query(None, description="Free-text search across name/prompt/plan/code"),
    tags: Optional[List[str]] = Query(None, description="Filter by tags (any match)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List sessions, newest updated first."""
    rows = svc_list_sessions(db, search=search, tags=tags, limit=limit, offset=offset)
    return [SessionResponse(**s.to_dict()) for s in rows]


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_one_session(session_id: uuid.UUID, db: Session = Depends(get_db)):
    """Fetch one session by id."""
    sess = svc_get_session(db, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionResponse(**sess.to_dict())


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
def patch_session(
    session_id: uuid.UUID,
    body: SessionUpdate,
    db: Session = Depends(get_db),
):
    """Update mutable fields on a session."""
    update_kwargs = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    sess = svc_update_session(db, session_id, **update_kwargs)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionResponse(**sess.to_dict())


@router.delete("/sessions/{session_id}", status_code=204)
def delete_one_session(session_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete a session and all its child rows (cascade)."""
    if not svc_delete_session(db, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return None


# ── Strategy class endpoints ───────────────────────────────────────────

class StrategyClassItem(BaseModel):
    name: str
    path: str
    description: str = ""
    # File metadata
    created_at: Optional[str] = None
    modified_at: Optional[str] = None
    # Performance KPIs (from meta file)
    cagr_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    total_return_pct: Optional[float] = None
    win_rate: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    total_trades: Optional[int] = None
    last_backtest: Optional[str] = None
    # Deployment status
    deployed: bool = False
    deployed_at: Optional[str] = None


@router.get("/strategy-classes", response_model=List[StrategyClassItem])
def list_strategy_classes():
    """List all available Strategy subclass files in the strategies/ directory.

    Scans backend/app/services/strategies/ for .py files that contain
    Strategy subclasses. Enriches each entry with metadata from a sidecar
    .meta.json file and deployment status from the database.
    """
    import json
    import re
    from datetime import datetime, timezone

    strategies_dir = Path(__file__).resolve().parent.parent / "services" / "strategies"
    if not strategies_dir.exists():
        return []

    # Get deployment status from DB
    deployed_classes: set[str] = set()
    try:
        from app.db.database import SessionLocal
        from app.models.strategy_lab import StrategyDeployment
        db = SessionLocal()
        try:
            active = db.query(StrategyDeployment).filter(
                StrategyDeployment.is_active == True
            ).all()
            for d in active:
                deployed_classes.add(d.class_name)
        finally:
            db.close()
    except Exception:
        pass

    classes = []
    for f in sorted(strategies_dir.glob("*.py")):
        if f.name.startswith("_") or f.name == "__init__.py":
            continue
        try:
            source = f.read_text()
            if "Strategy" not in source:
                continue

            # Extract class name and docstring
            class_match = re.search(r'class\s+(\w+)\s*\(.*Strategy.*\):', source)
            doc_match = re.search(r'"""(.+?)"""', source, re.DOTALL)
            if not class_match:
                continue

            class_name = class_match.group(1)
            description = (doc_match.group(1).strip().split("\n")[0][:150] if doc_match else "")

            # File timestamps
            f_stat = f.stat()
            created_at = datetime.fromtimestamp(f_stat.st_birthtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if hasattr(f_stat, 'st_birthtime') else None
            modified_at = datetime.fromtimestamp(f_stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

            # Read meta file if it exists
            meta_path = f.with_suffix(".meta.json")
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                except (json.JSONDecodeError, OSError):
                    pass

            classes.append(StrategyClassItem(
                name=class_name,
                path=str(f.relative_to(Path(__file__).resolve().parent.parent.parent.parent)),
                description=description,
                created_at=created_at,
                modified_at=modified_at,
                cagr_pct=meta.get("cagr_pct"),
                sharpe_ratio=meta.get("sharpe_ratio"),
                total_return_pct=meta.get("total_return_pct"),
                win_rate=meta.get("win_rate"),
                max_drawdown_pct=meta.get("max_drawdown_pct"),
                total_trades=meta.get("total_trades"),
                last_backtest=meta.get("last_backtest"),
                deployed=class_name in deployed_classes,
                deployed_at=meta.get("deployed_at"),
            ))
        except Exception:
            continue

    return classes


class DeleteStrategyRequest(BaseModel):
    path: str = Field(..., description="Path to the strategy file to delete (e.g. 'backend/app/services/strategies/my_strategy.py')")


@router.post("/strategy-classes/delete", status_code=200)
def delete_strategy_class(body: DeleteStrategyRequest):
    """Delete a strategy file and its meta file from the strategies directory.

    Only deletes files under backend/app/services/strategies/ for safety.
    Does NOT delete files from the standalone strategies/ directory.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    full_path = repo_root / body.path

    # Safety: only allow deleting from backend/app/services/strategies/
    strategies_dir = Path(__file__).resolve().parent.parent / "services" / "strategies"
    try:
        full_path.relative_to(strategies_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Can only delete files in backend/app/services/strategies/")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail=f"Strategy file not found: {full_path}")

    # Delete the .py file
    full_path.unlink()
    # Delete the .meta.json sidecar if it exists
    meta_path = full_path.with_suffix(".meta.json")
    if meta_path.exists():
        meta_path.unlink()

    return {"deleted": str(full_path), "name": full_path.stem}


# ── Experiment endpoints (Phase 3) ────────────────────────────────────────

class ExperimentRequest(BaseModel):
    n_runs: int = Field(10, ge=1, le=500)
    end_date: str = Field(..., description="YYYY-MM-DD, e.g. '2024-12-31'")
    start_date_min: str = Field("2002-01-01", description="Earliest random start date")
    start_date_max: str = Field("2024-01-01", description="Latest random start date")
    fixed_start_dates: Optional[List[str]] = Field(None, description="Exact start dates to reuse from a previous batch (apples-to-apples comparison)")
    model: Optional[str] = None
    # New mode: path to a Strategy subclass file (e.g. "strategies/daily_golden_cross.py")
    strategy_class_path: Optional[str] = Field(None, description="Path to a Strategy subclass file (replaces code_text mode)")


class ExperimentStartResponse(BaseModel):
    batch_id: str


class ExperimentRow(BaseModel):
    id: str
    session_id: str
    batch_id: str
    run_index: int
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    kpis: Optional[Dict[str, Any]] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class BatchStats(BaseModel):
    n_total: int
    n_completed: int
    n_failed: int
    mean_sharpe: Optional[float] = None
    best_sharpe: Optional[float] = None
    best_experiment_id: Optional[str] = None
    top_3: List[Dict[str, Any]] = []
    worst_3: List[Dict[str, Any]] = []


@router.post("/sessions/{session_id}/experiments", response_model=ExperimentStartResponse, status_code=202)
def start_experiments(
    session_id: str,
    body: ExperimentRequest,
    db: Session = Depends(get_db),
):
    """Kick off a batch of N backtest runs with random as_of_date windows.

    Supports two modes:
      - strategy_class_path: path to a Strategy subclass file (new mode)
      - session.code_text: legacy mode using the 4-function template

    In strategy_class_path mode, session_id can be '_' (placeholder) since
    no session lookup is needed.
    """
    from app.services.strategy_lab_orchestrator import run_batch

    if body.strategy_class_path:
        # New mode: use a Strategy subclass file — no session needed
        batch_id = run_batch(
            session_id=session_id,
            n_runs=body.n_runs,
            end_date=body.end_date,
            start_date_min=body.start_date_min,
            start_date_max=body.start_date_max,
            fixed_start_dates=body.fixed_start_dates,
            strategy_class_path=body.strategy_class_path,
        )
        return ExperimentStartResponse(batch_id=batch_id)

    # Legacy mode: requires a valid session
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid session_id format")
    sess = svc_get_session(db, sid)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    if not sess.code_text:
        raise HTTPException(status_code=400, detail="no code_text — generate code first")

    batch_id = run_batch(
        session_id=session_id,
        n_runs=body.n_runs,
        code_text=sess.code_text,
        end_date=body.end_date,
        start_date_min=body.start_date_min,
        start_date_max=body.start_date_max,
        fixed_start_dates=body.fixed_start_dates,
    )
    return ExperimentStartResponse(batch_id=batch_id)


@router.get("/sessions/{session_id}/experiments", response_model=List[ExperimentRow])
def list_session_experiments(
    session_id: str,
    db: Session = Depends(get_db),
):
    """List all experiments for a session (across batches), newest first."""
    from app.services.strategy_lab_experiments import list_experiments
    sid = uuid.UUID(session_id) if session_id != '_' else None
    rows = list_experiments(db, session_id=sid, limit=200)
    return [ExperimentRow(**r.to_dict()) for r in rows]


@router.get("/sessions/{session_id}/batches/{batch_id}/experiments", response_model=List[ExperimentRow])
def list_batch_experiments(
    session_id: str,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """List experiments in a specific batch."""
    from app.services.strategy_lab_experiments import list_experiments
    sid = uuid.UUID(session_id) if session_id != '_' else None
    rows = list_experiments(db, session_id=sid, batch_id=batch_id, limit=500)
    return [ExperimentRow(**r.to_dict()) for r in rows]


@router.get("/sessions/{session_id}/batches/{batch_id}/stats", response_model=BatchStats)
def batch_stats(
    session_id: str,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Summary statistics for a batch (mean Sharpe, top 3, worst 3)."""
    from app.services.strategy_lab_experiments import get_batch_stats
    return BatchStats(**get_batch_stats(db, batch_id))


@router.get("/experiments/{experiment_id}/equity-curve")
def get_equity_curve(
    experiment_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Return the equity curve for a single experiment."""
    from app.models.strategy_lab import StrategyExperiment
    exp = db.get(StrategyExperiment, experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return {"equity_curve": exp.equity_curve or []}


@router.get("/sessions/{session_id}/batches/{batch_id}/events")
async def batch_events(
    session_id: str,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Server-Sent Events stream for a running batch.

    Polls the in-memory batch queue (thread-safe) every 0.5s and yields
    events until the batch is done.
    """
    from fastapi.responses import StreamingResponse
    from app.services.strategy_lab_orchestrator import get_batch, drain_events
    from app.services.strategy_lab_experiments import create_experiment

    # Verify the session exists (skip for placeholder '_')
    if session_id != '_':
        try:
            sid = uuid.UUID(session_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid session_id")
        sess = svc_get_session(db, sid)
        if sess is None:
            raise HTTPException(status_code=404, detail="session not found")

    async def event_generator():
        import time
        try:
            while True:
                # Drain whatever's available right now
                evts = drain_events(batch_id, timeout=0.0)
                for event in evts:
                    if isinstance(event, dict) and event.get("done"):
                        yield f"data: {json.dumps(event)}\n\n"
                        return
                    # Persist this run's result
                    try:
                        exp = create_experiment(
                            db,
                            session_id=session_id,
                            batch_id=uuid.UUID(batch_id),
                            run_index=event["run_index"],
                            start_date=event.get("start_date"),
                            end_date=event.get("end_date"),
                            status=event["status"],
                            kpis=event.get("kpis"),
                            error_message=event.get("error_message"),
                        )
                        yield f"data: {json.dumps({**event, 'id': str(exp.id)})}\n\n"
                    except Exception as persist_err:
                        logger.error("Failed to persist experiment: %s", persist_err)
                        yield f"data: {json.dumps(event)}\n\n"
                # Sleep briefly before next poll
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            logger.info("Client disconnected from batch %s events", batch_id)
            raise

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Deploy endpoints ───────────────────────────────────────────────────

class DeployRequest(BaseModel):
    strategy_class_path: str = Field(..., description="Path to the Strategy subclass file to deploy")
    experiment_id: Optional[uuid.UUID] = None


class DeploymentResponse(BaseModel):
    deployment_id: str
    class_name: str
    class_file_path: str
    is_active: bool
    deployed_at: Optional[str] = None
    rolled_back_at: Optional[str] = None
    experiment_id: Optional[str] = None
    session_id: str


class DeploymentListItem(BaseModel):
    deployment_id: str
    class_name: str
    class_file_path: str
    is_active: bool
    deployed_at: Optional[str] = None
    rolled_back_at: Optional[str] = None
    experiment_id: Optional[str] = None
    session_id: str


@router.post("/sessions/{session_id}/deploy", response_model=DeploymentResponse)
def deploy(
    session_id: str,
    body: DeployRequest,
    db: Session = Depends(get_db),
):
    """Deploy a Strategy subclass to Alpaca paper trading.

    The strategy_class_path points to a Strategy subclass file in the
    repo (e.g. "backend/app/services/strategies/daily_golden_cross.py").
    The deploy flow:
      1. Imports the Strategy subclass
      2. Verifies it has the required methods
      3. Updates alpaca_runner.py to use the new class
      4. Records the deployment
    """
    from app.services.strategy_base import Strategy
    import importlib.util
    import sys

    # session_id can be '_' placeholder for strategy_class_path mode
    if session_id != '_':
        try:
            sid = uuid.UUID(session_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid session_id format")
        sess = svc_get_session(db, sid)
        if sess is None:
            raise HTTPException(status_code=404, detail="session not found")

    # Resolve the strategy file path
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    full_path = repo_root / body.strategy_class_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail=f"Strategy file not found: {full_path}")

    # Import and verify the Strategy subclass
    try:
        spec = importlib.util.spec_from_file_location("_deploy_strategy", str(full_path))
        if spec is None or spec.loader is None:
            raise HTTPException(status_code=422, detail="Could not create import spec")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_deploy_strategy"] = mod
        spec.loader.exec_module(mod)

        strategy_class = None
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy:
                strategy_class = obj
                break

        if strategy_class is None:
            raise HTTPException(status_code=422, detail=f"No Strategy subclass found in {body.strategy_class_path}")

        # Verify required methods
        instance = strategy_class()
        for attr in ("get_name", "get_signals", "should_exit", "max_holdings", "sizing_pcts"):
            if not hasattr(instance, attr):
                raise HTTPException(status_code=422, detail=f"Strategy missing required member: {attr}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to load strategy: {e}")

    # Register the deployment in the deployments registry (replaces the
    # alpaca_runner.py file-rewrite path). The stored strategy_path is the
    # absolute path, loadable by _load_active_strategy_class.
    class_name = strategy_class.__name__
    registry_deploy(
        strategy_path=str(full_path),
        params={},
        metrics_snapshot={},
        db=db,
    )

    # Record deployment
    from app.models.strategy_lab import StrategyDeployment
    from sqlalchemy import text as sa_text

    # Deactivate any active deployment
    active = db.query(StrategyDeployment).filter(StrategyDeployment.is_active == True).first()
    if active is not None:
        active.is_active = False
        active.rolled_back_at = sa_text("now()")

    # Use a random UUID for placeholder '_' session_id
    deploy_session_id = uuid.uuid4() if session_id == '_' else uuid.UUID(session_id)
    deployment = StrategyDeployment(
        session_id=deploy_session_id,
        experiment_id=body.experiment_id,
        class_name=class_name,
        class_file_path=str(full_path),
        is_active=True,
    )
    db.add(deployment)
    db.commit()
    db.refresh(deployment)

    return DeploymentResponse(
        deployment_id=str(deployment.id),
        class_name=class_name,
        class_file_path=str(full_path),
        is_active=True,
        experiment_id=str(body.experiment_id) if body.experiment_id else None,
        session_id=str(session_id),
    )


@router.get("/deployments", response_model=List[DeploymentListItem])
def list_deployments(
    active_only: bool = Query(False, description="Only return currently-active deployments"),
    db: Session = Depends(get_db),
):
    """List all deployments, newest first."""
    from app.models.strategy_lab import StrategyDeployment
    q = db.query(StrategyDeployment)
    if active_only:
        q = q.filter(StrategyDeployment.is_active == True)
    rows = q.order_by(StrategyDeployment.deployed_at.desc()).all()
    return [
        DeploymentListItem(
            deployment_id=str(r.id),
            class_name=r.class_name,
            class_file_path=r.class_file_path,
            is_active=r.is_active,
            deployed_at=r.deployed_at.isoformat() if r.deployed_at else None,
            rolled_back_at=r.rolled_back_at.isoformat() if r.rolled_back_at else None,
            experiment_id=str(r.experiment_id) if r.experiment_id else None,
            session_id=str(r.session_id),
        )
        for r in rows
    ]


@router.post("/deployments/{deployment_id}/rollback")
def rollback_deployment(
    deployment_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Roll back a deployment and restore the previous one."""
    from app.models.strategy_lab import StrategyDeployment
    from sqlalchemy import text as sa_text

    deployment = db.get(StrategyDeployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="deployment not found")
    if not deployment.is_active:
        raise HTTPException(status_code=400, detail="deployment is not active")

    deployment.is_active = False
    deployment.rolled_back_at = sa_text("now()")

    # Restore the previous deployment
    previous = (
        db.query(StrategyDeployment)
        .filter(StrategyDeployment.id != deployment_id)
        .order_by(StrategyDeployment.deployed_at.desc())
        .first()
    )
    if previous is not None:
        previous.is_active = True
        # Update alpaca_runner.py
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        alpaca_runner_path = repo_root / "backend" / "app" / "services" / "alpaca_runner.py"
        if alpaca_runner_path.exists():
            text = alpaca_runner_path.read_text()
            import re
            new_import = f"from app.services.strategies.{Path(previous.class_file_path).stem} import {previous.class_name}"
            text = re.sub(
                r"from app\.services\.strategies\.\w+ import \w+",
                new_import,
                text,
            )
            # Also update the instantiation line
            text = re.sub(
                r"strategy\s*=\s*\w+\(\)",
                f"strategy = {previous.class_name}()",
                text,
            )
            alpaca_runner_path.write_text(text)

    db.commit()
    return {"rolled_back_deployment_id": str(deployment_id), "restored_class_name": previous.class_name if previous else "GoldenCrossStrategy"}


# ── Library endpoints ───────────────────────────────────────────────────────

class LibrarySaveRequest(BaseModel):
    name: str = Field(..., min_length=1)
    change_description: str = Field(default="")
    model: Optional[str] = None


class LibraryEntryResponse(BaseModel):
    version: int
    strategy_name: str
    created_at: str
    change_description: str
    backtest_kpis: Dict[str, Any] = Field(default_factory=dict)
    code: Optional[str] = None
    folder: Optional[str] = None


class LibraryListResponse(BaseModel):
    name: str
    display_name: str
    version_count: int
    latest_version: LibraryEntryResponse
    versions: List[LibraryEntryResponse]


@router.post("/sessions/{session_id}/library/save", response_model=LibraryEntryResponse)
def save_to_library(
    session_id: uuid.UUID,
    body: LibrarySaveRequest,
    db: Session = Depends(get_db),
):
    """Save the current session's code to the strategy library."""
    from app.services.strategy_lab_library import save_strategy
    from app.services.strategy_lab_experiments import list_experiments
    sess = svc_get_session(db, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    if not sess.code_text:
        raise HTTPException(status_code=400, detail="no code_text to save")

    # Get latest KPIs from most recent completed experiment
    exps = list_experiments(db, session_id=session_id, limit=50)
    best_kpis = {}
    for e in exps:
        if e.status == "completed" and e.kpis:
            best_kpis = e.kpis
            break

    meta = save_strategy(
        name=body.name,
        code=sess.code_text,
        prompt=sess.prompt or "",
        plan=sess.plan_text or "",
        kpis=best_kpis,
        change_description=body.change_description,
        model_id=sess.model_id,
        session_id=str(session_id),
    )
    return LibraryEntryResponse(**meta)


@router.get("/library", response_model=List[LibraryListResponse])
def list_library():
    """List all saved strategies with their version history."""
    from app.services.strategy_lab_library import list_strategies
    strategies = list_strategies()
    result = []
    for s in strategies:
        result.append(LibraryListResponse(
            name=s["name"],
            display_name=s["display_name"],
            version_count=s["version_count"],
            latest_version=LibraryEntryResponse(**s["latest_version"]),
            versions=[LibraryEntryResponse(**v) for v in s["versions"]],
        ))
    return result


@router.get("/library/{name}", response_model=LibraryListResponse)
def get_library_entry(name: str):
    """Get full details for a specific strategy."""
    from app.services.strategy_lab_library import get_strategy
    s = get_strategy(name)
    if s is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    return LibraryListResponse(
        name=s["name"],
        display_name=s["display_name"],
        version_count=len(s["versions"]),
        latest_version=LibraryEntryResponse(**s["versions"][-1]),
        versions=[LibraryEntryResponse(**v) for v in s["versions"]],
    )


class LibraryLoadRequest(BaseModel):
    name: str = Field(..., min_length=1)
    version: Optional[int] = None  # None = latest


@router.post("/library/load", response_model=SessionResponse)
def load_from_library(
    body: LibraryLoadRequest,
    db: Session = Depends(get_db),
):
    """Create a new session from a saved library strategy (skips steps 1-2)."""
    from app.services.strategy_lab_library import get_strategy
    from app.services.strategy_lab_session import create_session
    s = get_strategy(body.name)
    if s is None:
        raise HTTPException(status_code=404, detail="strategy not found")

    # Pick the requested version or latest
    versions = s["versions"]
    if body.version:
        versions = [v for v in versions if v.get("version") == body.version]
    if not versions:
        raise HTTPException(status_code=404, detail="version not found")

    entry = versions[-1]
    code = entry.get("code", "")
    if not code:
        raise HTTPException(status_code=400, detail="no code found for this version")

    new_sess = create_session(
        db,
        name=f"{entry.get('strategy_name', body.name)} (library)",
        prompt=entry.get("prompt", "Loaded from library"),
        model_id=entry.get("model_id", "kimi-k2.6:cloud"),
    )
    # Set plan and code
    from app.services.strategy_lab_session import update_session
    update_session(db, new_sess.id, plan_text=entry.get("plan", ""), code_text=code)
    return SessionResponse(**new_sess.to_dict())
