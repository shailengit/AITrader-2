"""
AI Stock Screener router for TradeCraft API.
Supports two screening modes:
1. Dormant Giant (agnoMultiAgentTrader_3) - Bollinger squeeze + EPS acceleration
2. Quant Strategy (agnoMultiAgentTrader_2) - TA-based with backtesting

Includes real-time SSE streaming of agent logs and progress.
"""

import uuid
import json
import logging
import asyncio
from typing import List, Optional, Dict, Any, Literal
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.services.agno_screener import (
    run_dormant_giant_screener,
    run_dormant_giant_screener_with_ai,
    run_quant_strategy_screener,
    run_quant_strategy_screener_with_ai,
)
from app.services.pdf_generator import generate_screener_report
from app.services.screening.chart_data import get_chart_data
from app.services.screening.ticker_detail import get_ticker_detail
from app.utils.security import get_safe_table_name, sanitize_ticker

logger = logging.getLogger(__name__)

router = APIRouter()

# =============================================================================
# In-memory state
# =============================================================================

scan_status: Dict[str, Dict[str, Any]] = {}
scan_queues: Dict[str, asyncio.Queue] = {}


# =============================================================================
# Models
# =============================================================================

class CustomCompositeDef(BaseModel):
    """User-defined composite metric combining two indicators."""
    name: str
    left_indicator: str
    right_indicator: str
    operation: Literal["add", "subtract", "multiply", "divide", "ratio_pct"]


class ResultColumnRef(BaseModel):
    """A result-row key the frontend expects to be populated.

    The frontend sends the list of columns the results table will display
    (e.g. {'dataKey': 'sma_200', 'params': {'window': 200}}). The worker
    guarantees each requested column has a value in the result row by
    computing it at the requested params (or copying from the
    add_all_ta_features output if it was already produced).
    """
    dataKey: str
    params: Optional[Dict[str, Any]] = None


class ScanRequest(BaseModel):
    """Scan request model."""
    mode: Literal["dormant_giant", "quant_strategy"] = "dormant_giant"
    use_ai: bool = True
    cutoff_date: Optional[str] = None  # For quant_strategy mode backtesting
    prompt: Optional[str] = None  # Custom prompt for AI analysis
    max_results: int = 50
    filters: Optional[Dict[str, Any]] = None
    base_weight: Optional[int] = 60  # 0-100, percent weight for base setup score in quant strategy
    sub_weights: Optional[Dict[str, int]] = None  # Per-sub-score weights: {trend, momentum, volatility, volume}; each >= 0
    include_alignment: Optional[bool] = False  # When true, attach score_minus_return per result row
    angle_weight: Optional[int] = 0  # 0-100, how much crossover angle matters vs binary pass/fail
    custom_composites: Optional[List[CustomCompositeDef]] = None  # User-defined composite metrics
    result_columns: Optional[List[ResultColumnRef]] = None  # Result-row keys the UI will display


class ScanResult(BaseModel):
    """Stock scan result model."""
    ticker: str
    signal: Optional[str] = None
    fundamental_catalyst: Optional[str] = None
    close: Optional[float] = None
    data_date: Optional[str] = None
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    rsi: Optional[float] = None
    macd: Optional[float] = None
    volume: Optional[int] = None
    next_earnings_date: Optional[str] = None
    days_until_earnings: Optional[int] = None
    eps_estimate: Optional[float] = None
    time_of_day: Optional[str] = None


class ScanStatus(BaseModel):
    """Scan status model."""
    scan_id: str
    mode: str
    status: str  # 'pending', 'running', 'completed', 'failed'
    progress: int  # 0-100
    use_ai: bool
    results: Optional[List[Dict]] = None
    ai_report: Optional[str] = None
    error: Optional[str] = None


# =============================================================================
# Backtest Hold Models
# =============================================================================

class BacktestHoldRequest(BaseModel):
    """Buy-and-hold backtest request."""
    tickers: List[str]
    as_of_date: str  # ISO date string, e.g. "2024-01-15"


class TickerBacktestResult(BaseModel):
    """Single ticker backtest result."""
    ticker: str
    buy_price: float
    current_price: float
    return_pct: float
    buy_date: str


class BacktestAggregate(BaseModel):
    """Aggregate statistics across tickers."""
    avg_return_pct: float
    median_return_pct: float
    best: Dict[str, Any]  # {"ticker": str, "return_pct": float}
    worst: Dict[str, Any]
    equal_weight_portfolio_return_pct: float


class BenchmarkResult(BaseModel):
    """SPY benchmark result."""
    ticker: str = "SPY"
    buy_price: float
    current_price: float
    return_pct: float


class BacktestHoldResponse(BaseModel):
    """Buy-and-hold backtest response."""
    as_of_date: str
    as_of_actual: str  # closest trading day on or before as_of_date
    latest_date: str
    days_held: int
    ticker_results: List[TickerBacktestResult]
    aggregate: BacktestAggregate
    benchmark: BenchmarkResult
    alpha_pct: float


# =============================================================================
# Helpers
# =============================================================================

def _create_event(event_type: str, data: Dict[str, Any]) -> str:
    """Format a Server-Sent Event payload."""
    payload = json.dumps({"type": event_type, "data": data})
    return f"data: {payload}\n\n"


def _push_event(scan_id: str, event_type: str, data: Dict[str, Any]):
    """Push an event into the scan's SSE queue if it exists."""
    q = scan_queues.get(scan_id)
    if q is not None:
        try:
            q.put_nowait(_create_event(event_type, data))
        except asyncio.QueueFull:
            pass


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/modes")
async def get_screener_modes():
    """Get available screening modes with descriptions."""
    return {
        "modes": [
            {
                "id": "dormant_giant",
                "name": "Dormant Giant Screener",
                "description": "Identifies stocks with Bollinger Band squeeze, OBV hidden accumulation, or resistance breakouts. Verifies with EPS acceleration as catalyst.",
                "use_ai_options": [True, False],
                "supports_backtesting": False,
                "agents": ["Technical Specialist", "Fundamental Specialist", "Risk Manager"]
            },
            {
                "id": "quant_strategy",
                "name": "Quant Strategy Screener",
                "description": "Technical analysis screening with fundamental health verification, risk assessment, and optional historical backtesting.",
                "use_ai_options": [True, False],
                "supports_backtesting": True,
                "agents": ["Technical Specialist", "Fundamental Specialist", "Risk Manager", "Performance Analyst"]
            }
        ]
    }


@router.post("/scan", response_model=Dict[str, Any])
async def run_scan(request: ScanRequest, background_tasks: BackgroundTasks):
    """
    Run stock screening scan.

    Modes:
    - dormant_giant: Bollinger squeeze + EPS acceleration detection
    - quant_strategy: TA-based with fundamental health and optional backtesting

    Set use_ai=True to get AI-generated analysis report from multi-agent team.
    """
    scan_id = str(uuid.uuid4())

    # Initialize status
    scan_status[scan_id] = {
        "mode": request.mode,
        "status": "pending",
        "progress": 0,
        "use_ai": request.use_ai,
        "results": None,
        "ai_report": None,
        "error": None,
        "logs": []
    }

    # Create SSE queue for this scan
    scan_queues[scan_id] = asyncio.Queue(maxsize=500)

    # Run scan in background
    background_tasks.add_task(run_screening_task, scan_id, request)

    return {
        "scan_id": scan_id,
        "mode": request.mode,
        "use_ai": request.use_ai,
        "status": "pending",
        "message": f"Scan started in {request.mode} mode. Stream /api/screener/stream/{scan_id} for real-time updates."
    }


@router.get("/stream/{scan_id}")
async def stream_scan(scan_id: str):
    """
    Server-Sent Events endpoint for real-time scan progress and agent logs.

    Streams events:
    - log: { agent, message, type, color }
    - progress: { progress }
    - status: { status, error? }
    """
    if scan_id not in scan_status:
        raise HTTPException(status_code=404, detail="Scan ID not found")

    q = scan_queues.get(scan_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Scan queue not found")

    async def event_generator():
        # Send initial state
        yield _create_event("status", {"status": scan_status[scan_id]["status"], "progress": scan_status[scan_id]["progress"]})

        while True:
            # Drain any queued events first (handles fast scans where queue filled before connect)
            drained = False
            while not q.empty():
                try:
                    event = q.get_nowait()
                    yield event
                    drained = True
                except asyncio.QueueEmpty:
                    break

            # After draining, if scan is done, send final status and exit
            if scan_status[scan_id]["status"] in ("completed", "failed"):
                yield _create_event("status", {"status": scan_status[scan_id]["status"], "progress": scan_status[scan_id]["progress"]})
                break

            # If we drained events, loop again immediately to check status
            if drained:
                await asyncio.sleep(0.1)
                continue

            try:
                event = await asyncio.wait_for(q.get(), timeout=5.0)
                yield event
            except asyncio.TimeoutError:
                # Send keep-alive heartbeat
                yield ":heartbeat\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/status/{scan_id}")
async def get_scan_status(scan_id: str):
    """Get status of a running or completed scan (polling fallback)."""
    if scan_id not in scan_status:
        raise HTTPException(status_code=404, detail="Scan ID not found")

    status = scan_status[scan_id]
    logs = status.get("logs", [])

    # Convert legacy string logs to structured format
    structured_logs = []
    for log in logs:
        if isinstance(log, dict):
            structured_logs.append(log)
        else:
            structured_logs.append({
                "agent": "System",
                "message": str(log),
                "type": "system",
                "color": "gray"
            })

    return {
        "scan_id": scan_id,
        "mode": status.get("mode", "unknown"),
        "status": status["status"],
        "progress": status["progress"],
        "use_ai": status.get("use_ai", False),
        "results_count": len(status["results"]) if status.get("results") else 0,
        "has_ai_report": status.get("ai_report") is not None,
        "error": status.get("error"),
        "logs": structured_logs
    }


@router.get("/results/{scan_id}")
async def get_scan_results(scan_id: str):
    """Get final results of a completed scan."""
    if scan_id not in scan_status:
        raise HTTPException(status_code=404, detail="Scan ID not found")

    status = scan_status[scan_id]

    if status["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Scan not completed. Current status: {status['status']}"
        )

    return {
        "scan_id": scan_id,
        "mode": status.get("mode", "unknown"),
        "status": "completed",
        "use_ai": status.get("use_ai", False),
        "results_count": len(status["results"]) if status.get("results") else 0,
        "results": status["results"],
        "ai_report": status.get("ai_report")
    }


@router.get("/ai-report/{scan_id}")
async def get_ai_report(scan_id: str):
    """Get the AI-generated analysis report for a completed scan."""
    if scan_id not in scan_status:
        raise HTTPException(status_code=404, detail="Scan ID not found")

    status = scan_status[scan_id]

    if status["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Scan not completed. Current status: {status['status']}"
        )

    if not status.get("ai_report"):
        raise HTTPException(
            status_code=404,
            detail="No AI report available. This scan was run without AI analysis (use_ai=False)."
        )

    return {
        "scan_id": scan_id,
        "mode": status.get("mode"),
        "ai_report": status["ai_report"]
    }


@router.get("/report/{scan_id}")
async def download_report(scan_id: str):
    """
    Download a professional PDF report for a completed scan.
    """
    if scan_id not in scan_status:
        raise HTTPException(status_code=404, detail="Scan ID not found")

    status = scan_status[scan_id]

    if status["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Scan not completed. Current status: {status['status']}"
        )

    results = status.get("results") or []
    ai_report = status.get("ai_report")
    mode = status.get("mode", "unknown")
    use_ai = status.get("use_ai", False)

    # Build summary text
    summary = status.get("summary", f"Found {len(results)} stocks.")

    # Build stats
    stats = {
        "technical_candidates": status.get("technical_candidates", len(results)),
        "verified_candidates": status.get("verified_candidates", len(results)),
        "results_count": len(results)
    }

    try:
        pdf_bytes = generate_screener_report(
            mode=mode,
            use_ai=use_ai,
            results=results,
            summary=summary,
            ai_report=ai_report,
            stats=stats
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("PDF generation failed for scan %s: %s", scan_id, e)
        raise HTTPException(
            status_code=500,
            detail=f"PDF generation failed: {str(e)}"
        ) from e

    safe_mode = mode.replace("_", "-")
    filename = f"tradecraft-screener-{safe_mode}-{scan_id[:8]}.pdf"

    from fastapi.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.delete("/scan/{scan_id}")
async def delete_scan(scan_id: str):
    """Delete a scan from memory."""
    if scan_id not in scan_status:
        raise HTTPException(status_code=404, detail="Scan ID not found")

    # Clean up queue
    if scan_id in scan_queues:
        del scan_queues[scan_id]
    del scan_status[scan_id]
    return {"message": f"Scan {scan_id} deleted"}


@router.get("/health")
async def screener_health():
    """Health check for screener service."""
    return {
        "status": "healthy",
        "active_scans": len(scan_status),
        "modes_available": ["dormant_giant", "quant_strategy"]
    }


# =============================================================================
# Chart Data Endpoint
# =============================================================================

@router.get("/chart-data/{ticker}")
async def chart_data(
    ticker: str,
    indicators: str = "",
    days: int = 250,
    overrides: str = "",
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """
    Fetch OHLCV bars for a single ticker, with the requested indicator time
    series embedded per-bar. Powers the per-row Chart button in the Custom
    Screener — the scan result row carries current snapshot values, but the
    chart needs the historical series so the user can visually inspect the
    indicator at and around the as-of-date.

    Query params:
        ticker:     Ticker symbol (will be sanitized).
        indicators: Comma-separated backend column names (e.g. "ema_20,sma_200").
                    Each must exist in INDICATOR_REGISTRY or be auto-produced
                    by add_all_ta_features. Unknown columns are silently
                    dropped (the chart simply shows no overlay for them).
        days:       Calendar days of history (default 250). Lower than ~200
                    will produce unusable SMA/EMA 200 values. There is no
                    hard upper bound; pass a very large value (e.g. 10000)
                    to fetch the full history for a long-listed ticker.
                    Ignored when both `start` and `end` are provided.
        overrides:  Optional JSON object mapping column → custom params for
                    indicators that need non-default parameters. Example:
                    `overrides={"ema_20":{"window":200}}` requests a 200-
                    period EMA rooted at the `ema_20` indicator. Each
                    (column, params) pair gets a unique payload key in the
                    output (`<column>__<sig>`) so the frontend can render
                    both side by side.
        start:      Optional ISO date (YYYY-MM-DD) for the lower bound.
                    When both `start` and `end` are provided, the SQL uses
                    `WHERE "Date" BETWEEN :start AND :end`. When only
                    `start` is provided, the upper bound is `start + days`
                    calendar days (or the latest available date, whichever
                    is earlier).
        end:        Optional ISO date (YYYY-MM-DD) for the upper bound.
                    Symmetric to `start`.

    Returns: List of {time, open, high, low, close, volume, indicators: {...}}
    bars ordered oldest-first. Empty list when the ticker has no data. The
    `indicators` dict is keyed by `<column>` for default-param requests and
    `<column>__<sig>` for override requests, so callers must look up by
    the same key they requested.
    """
    try:
        safe = sanitize_ticker(ticker)
        if not safe:
            raise HTTPException(status_code=400, detail="Invalid ticker symbol")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    indicator_list = [c.strip() for c in indicators.split(",") if c.strip()]

    overrides_map: Dict[str, Dict[str, Any]] = {}
    if overrides:
        try:
            parsed = json.loads(overrides)
            if not isinstance(parsed, dict):
                raise ValueError("overrides must be a JSON object")
            for col, params in parsed.items():
                if not isinstance(params, dict):
                    continue
                # Coerce numeric values to int where possible — query params
                # arrive as strings otherwise.
                cleaned: Dict[str, Any] = {}
                for k, v in params.items():
                    if isinstance(v, (int, float)):
                        cleaned[k] = int(v) if float(v).is_integer() else v
                    elif isinstance(v, str):
                        try:
                            cleaned[k] = int(v)
                        except ValueError:
                            try:
                                cleaned[k] = float(v)
                            except ValueError:
                                cleaned[k] = v
                    else:
                        cleaned[k] = v
                overrides_map[col] = cleaned
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid overrides JSON: {exc}"
            ) from exc

    # Validate start/end formats early so the route returns a clean 400
    # before the service runs any SQL.
    from datetime import datetime as _dt
    if start:
        try:
            _dt.strptime(start, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid start date: {start!r}; expected YYYY-MM-DD",
            )
    if end:
        try:
            _dt.strptime(end, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid end date: {end!r}; expected YYYY-MM-DD",
            )

    bars = await run_in_threadpool(
        get_chart_data, ticker, indicator_list, days, overrides_map, start, end
    )
    return bars or []


# =============================================================================
# Backtest Hold Endpoint
# =============================================================================

@router.post("/backtest-hold", response_model=BacktestHoldResponse)
async def backtest_hold(request: BacktestHoldRequest):
    """
    Buy-and-hold backtest from as_of_date to latest available date.

    Synchronous, stateless -- no scan_id needed.
    For each ticker, finds the closest trading day on or before as_of_date,
    records the buy price, then compares against the latest available close.
    Includes SPY benchmark and alpha calculation.
    """
    from datetime import datetime, date

    # 1. Validate inputs
    if not request.tickers:
        raise HTTPException(status_code=400, detail="tickers required")

    as_of = datetime.strptime(request.as_of_date, "%Y-%m-%d").date()
    if as_of > date.today():
        raise HTTPException(status_code=400, detail="as_of_date must be on or before today")

    # 2. Get latest available date from database
    from app.db import database
    from sqlalchemy import text

    with database.engine.connect() as conn:
        latest_result = conn.execute(text('SELECT MAX("Date") FROM aapl'))
        latest_date = latest_result.scalar()

    if latest_date is None:
        raise HTTPException(status_code=500, detail="Could not determine latest trading date")

    # 3. For each ticker, get buy price and current price
    from app.utils.security import get_safe_table_name

    ticker_results = []
    for ticker in request.tickers:
        try:
            safe_table = get_safe_table_name(ticker)
        except ValueError:
            continue  # Skip invalid tickers

        with database.engine.connect() as conn:
            # Buy price: closest trading day on or before as_of_date
            buy_query = text(
                f'SELECT "Date", "Close" FROM "{safe_table}" WHERE "Date" <= :as_of ORDER BY "Date" DESC LIMIT 1'
            )
            buy_result = conn.execute(buy_query, {"as_of": request.as_of_date}).fetchone()

            # Current price: latest available
            current_query = text(f'SELECT "Date", "Close" FROM "{safe_table}" ORDER BY "Date" DESC LIMIT 1')
            current_result = conn.execute(current_query).fetchone()

        if buy_result is None or current_result is None:
            continue

        buy_price = float(buy_result[1])
        current_price = float(current_result[1])
        buy_date = str(buy_result[0])[:10]  # Trim time component if present

        if buy_price > 0:
            return_pct = round((current_price - buy_price) / buy_price * 100, 2)
        else:
            return_pct = 0.0

        ticker_results.append({
            "ticker": ticker.upper(),
            "buy_price": round(buy_price, 2),
            "current_price": round(current_price, 2),
            "return_pct": return_pct,
            "buy_date": buy_date,
        })

    # 4. Compute aggregate stats
    if ticker_results:
        returns = [r["return_pct"] for r in ticker_results]
        avg_return = round(sum(returns) / len(returns), 2)
        sorted_returns = sorted(ticker_results, key=lambda r: r["return_pct"], reverse=True)
        median_return = round(sorted(returns)[len(returns) // 2], 2)
        best = {"ticker": sorted_returns[0]["ticker"], "return_pct": sorted_returns[0]["return_pct"]}
        worst = {"ticker": sorted_returns[-1]["ticker"], "return_pct": sorted_returns[-1]["return_pct"]}
        portfolio_return = round(sum(returns) / len(returns), 2)  # Equal-weighted
    else:
        avg_return = 0.0
        median_return = 0.0
        best = {"ticker": "", "return_pct": 0.0}
        worst = {"ticker": "", "return_pct": 0.0}
        portfolio_return = 0.0

    # 5. SPY benchmark (table may not exist in all databases)
    try:
        with database.engine.connect() as conn:
            # Try uppercase first (PostgreSQL convention in this DB), then lowercase
            spy_buy = None
            spy_current = None
            for spy_table in ('"SPY"', '"spy"'):
                try:
                    spy_buy = conn.execute(
                        text(f'SELECT "Date", "Close" FROM {spy_table} WHERE "Date" <= :as_of ORDER BY "Date" DESC LIMIT 1'),
                        {"as_of": request.as_of_date}
                    ).fetchone()
                    if spy_buy:
                        break
                except Exception:
                    # A missing table aborts the current transaction in psycopg2;
                    # rollback so the next try can run in a fresh transaction.
                    conn.rollback()
                    continue
            for spy_table in ('"SPY"', '"spy"'):
                try:
                    spy_current = conn.execute(
                        text(f'SELECT "Date", "Close" FROM {spy_table} ORDER BY "Date" DESC LIMIT 1')
                    ).fetchone()
                    if spy_current:
                        break
                except Exception:
                    conn.rollback()
                    continue

        if spy_buy and spy_current and float(spy_buy[1]) > 0:
            spy_return = round((float(spy_current[1]) - float(spy_buy[1])) / float(spy_buy[1]) * 100, 2)
        else:
            spy_return = 0.0
    except Exception:
        logger.warning("SPY table not available, skipping benchmark")
        spy_return = 0.0
        spy_buy = None
        spy_current = None

    # 6. Alpha
    alpha = round(portfolio_return - spy_return, 2)

    # 7. Days held
    as_of_actual = ticker_results[0]["buy_date"] if ticker_results else request.as_of_date
    latest_date_dt = latest_date.date() if isinstance(latest_date, datetime) else latest_date
    as_of_actual_dt = datetime.strptime(as_of_actual, "%Y-%m-%d").date()
    days_held = (latest_date_dt - as_of_actual_dt).days if ticker_results else 0

    return BacktestHoldResponse(
        as_of_date=request.as_of_date,
        as_of_actual=as_of_actual,
        latest_date=str(latest_date),
        days_held=days_held,
        ticker_results=[TickerBacktestResult(**r) for r in ticker_results],
        aggregate=BacktestAggregate(
            avg_return_pct=avg_return,
            median_return_pct=median_return,
            best=best,
            worst=worst,
            equal_weight_portfolio_return_pct=portfolio_return,
        ),
        benchmark=BenchmarkResult(
            ticker="SPY",
            buy_price=round(float(spy_buy[1]), 2) if spy_buy else 0.0,
            current_price=round(float(spy_current[1]), 2) if spy_current else 0.0,
            return_pct=spy_return,
        ),
        alpha_pct=alpha,
    )


# =============================================================================
# Screener-driven exit backtest (POST /api/screener/backtest-exit)
# =============================================================================

from app.services.backtest.schemas import (  # noqa: E402  (placed here so file-local imports stay grouped)
    BacktestExitRequest,
    BacktestExitResponse,
    DEFAULT_TOTAL_CAPITAL,
)


@router.post("/backtest-exit", response_model=BacktestExitResponse)
def backtest_exit(req: BacktestExitRequest) -> BacktestExitResponse:
    """Run a screener at an as-of date, pick top N, simulate each position
    independently with the user-configured exit rules, and return the
    per-trade ledger, summary stats, equity curve, and SPY alpha.
    """
    from app.services.backtest.orchestrator import run_backtest
    return run_backtest(req)


# =============================================================================
# Background task
# =============================================================================

async def run_screening_task(scan_id: str, request: ScanRequest):
    """Background task to run the screening workflow with real-time event streaming."""

    def update_progress(p: int):
        scan_status[scan_id]["progress"] = p
        _push_event(scan_id, "progress", {"progress": p})

    def update_logs(message: str):
        scan_status[scan_id]["logs"].append(message)
        _push_event(scan_id, "log", {"agent": "System", "message": message, "type": "system", "color": "gray"})

    def update_agent_log(agent: str, message: str, log_type: str = "system", color: str = "gray"):
        entry = {"agent": agent, "message": message, "type": log_type, "color": color}
        scan_status[scan_id]["logs"].append(entry)
        _push_event(scan_id, "log", entry)

    try:
        scan_status[scan_id]["status"] = "running"
        scan_status[scan_id]["progress"] = 0
        _push_event(scan_id, "status", {"status": "running", "progress": 0})
        update_agent_log("System", f"Starting scan {scan_id} in {request.mode} mode")

        mode = request.mode
        use_ai = request.use_ai
        logs_buffer: List[Dict[str, Any]] = []

        if mode == "dormant_giant":
            if use_ai:
                result = await run_in_threadpool(
                    lambda: run_dormant_giant_screener_with_ai(
                        prompt=request.prompt,
                        progress_callback=update_progress,
                        log_callback=update_logs,
                        filters=request.filters,
                        logs_buffer=logs_buffer,
                        agent_log_callback=update_agent_log,
                        cutoff_date=request.cutoff_date
                    )
                )
            else:
                result = await run_in_threadpool(
                    lambda: run_dormant_giant_screener(
                        prompt=request.prompt,
                        progress_callback=update_progress,
                        log_callback=update_logs,
                        filters=request.filters,
                        cutoff_date=request.cutoff_date
                    )
                )

        elif mode == "quant_strategy":
            if use_ai:
                result = await run_in_threadpool(
                    lambda: run_quant_strategy_screener_with_ai(
                        prompt=request.prompt or "Find me candidates for a high-growth breakout. Technically, they should be in a Volatility Squeeze (volatility_bbw). Fundamentally, they must have positive QoQ revenue growth.",
                        cutoff_date=request.cutoff_date,
                        logs_buffer=logs_buffer,
                        progress_callback=update_progress,
                        agent_log_callback=update_agent_log,
                        filters=request.filters,
                        base_weight=request.base_weight,
                        sub_weights=request.sub_weights,
                        include_alignment=request.include_alignment,
                        angle_weight=request.angle_weight,
                    )
                )
            else:
                result = await run_in_threadpool(
                    lambda: run_quant_strategy_screener(
                        prompt=request.prompt or "Find me candidates for a high-growth breakout. Technically, they should be in a Volatility Squeeze (volatility_bbw). Fundamentally, they must have positive QoQ revenue growth.",
                        cutoff_date=request.cutoff_date,
                        progress_callback=update_progress,
                        log_callback=update_logs,
                        filters=request.filters,
                        base_weight=request.base_weight,
                        sub_weights=request.sub_weights,
                        include_alignment=request.include_alignment,
                        angle_weight=request.angle_weight,
                        result_columns=[c.model_dump(exclude_none=True) for c in (request.result_columns or [])],
                    )
                )
        else:
            raise ValueError(f"Unknown mode: {mode}")

        # Merge any logs from result into logs_buffer
        if result and "logs" in result and isinstance(result["logs"], list):
            logs_buffer.extend(result["logs"])
            for entry in result["logs"]:
                if isinstance(entry, dict):
                    _push_event(scan_id, "log", entry)

        # Limit results
        if "results" in result and isinstance(result["results"], list):
            result["results"] = result["results"][:request.max_results]

        # --- Coach journal hook (failure-isolated) ---
        try:
            from app.services.coach.journal import upsert_strategy, record_strategy_run, record_signal
            strat = upsert_strategy(kind="screener", name=f"screener:{request.mode}")
            if strat is not None:
                from datetime import datetime as _dt
                _hits = result.get("results", []) or []
                run = record_strategy_run(
                    strategy_id=strat.id,
                    started_at=_dt.utcnow(),
                    result_summary={"n_hits": len(_hits), "scan_id": scan_id, "mode": request.mode},
                    as_of_date=getattr(request, "cutoff_date", None),
                )
                if run is not None:
                    _asof = getattr(request, "cutoff_date", None) or _dt.utcnow().date()
                    for hit in _hits:
                        if isinstance(hit, dict):
                            _tk = hit.get("ticker")
                        else:
                            _tk = getattr(hit, "ticker", None)
                        if not _tk:
                            continue
                        record_signal(
                            run_id=run.id, ticker=_tk, signal_type="entry", as_of_date=_asof,
                            signal_strength=(hit.get("score") if isinstance(hit, dict) else getattr(hit, "score", None)),
                            payload=(hit if isinstance(hit, dict) else (hit.to_dict() if hasattr(hit, "to_dict") else {})),
                        )
        except Exception as _e:
            logger.warning("Coach screener hook failed: %s", _e)

        update_progress(100)
        scan_status[scan_id]["status"] = "completed"
        scan_status[scan_id]["progress"] = 100
        scan_status[scan_id]["results"] = result.get("results", [])
        scan_status[scan_id]["ai_report"] = result.get("ai_report")
        scan_status[scan_id]["summary"] = result.get("summary", "")
        scan_status[scan_id]["technical_candidates"] = result.get("technical_candidates", 0)
        scan_status[scan_id]["verified_candidates"] = result.get("verified_candidates", 0)

        _push_event(scan_id, "status", {"status": "completed", "progress": 100})
        update_agent_log("System", f"Scan complete. {len(result.get('results', []))} stocks found.")

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Scan %s failed: %s", scan_id, e)
        scan_status[scan_id]["status"] = "failed"
        scan_status[scan_id]["error"] = str(e)
        _push_event(scan_id, "status", {"status": "failed", "error": str(e)})
        update_agent_log("System", f"Scan failed: {str(e)}", log_type="error", color="red")

    finally:
        # Close the queue gracefully after a short delay
        await asyncio.sleep(2.0)
        if scan_id in scan_queues:
            del scan_queues[scan_id]


# =============================================================================
# Ticker Detail Endpoint (powers TickerDetailDrawer in the Custom Screener)
# =============================================================================

@router.get("/ticker/{ticker}")
async def ticker_detail(
    ticker: str,
    as_of_date: str = "",
):
    """
    Return the full TickerDetail payload for one ticker — fundamentals,
    indicator snapshot, and next earnings event. Powers the on-demand row
    click in the Custom Screener results table.

    Query params:
        ticker:     Ticker symbol (sanitized).
        as_of_date: YYYY-MM-DD cutoff (optional). If absent, the most recent
                    bar date is used.

    Returns: TickerDetail dict (see app.services.screening.ticker_detail).

    Errors:
        400 VALIDATION_ERROR — malformed ticker string.
        404 DATA_NOT_FOUND   — no data for this ticker on the as-of date.
    """
    try:
        safe = sanitize_ticker(ticker)
        if not safe:
            raise HTTPException(status_code=400, detail="Invalid ticker symbol")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    from app.exceptions import DataNotFoundError  # local import: keeps top tidy
    from app.services.screening import ticker_detail as _td_module  # late-bound for tests

    try:
        return await run_in_threadpool(
            _td_module.get_ticker_detail, safe, as_of_date or None
        )
    except DataNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc) or "No data for ticker",
        ) from exc


@router.get("/pegy/{ticker}")
async def pegy_detail(ticker: str):
    """Return PEGY (P/E / (Earnings Growth % + Dividend Yield %)) for one ticker.

    Query params:
        ticker: Ticker symbol.

    Returns: {ticker, close, eps, pe, earnings_growth_pct, dividend_yield_pct, pegy}
    """
    from app.services.pegy import compute_pegy
    return compute_pegy(ticker)
