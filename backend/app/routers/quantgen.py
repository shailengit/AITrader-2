"""
QuantGen Strategy Builder router for TradeCraft API.
Provides AI-powered strategy generation, execution, and optimization.
Ported from QuantGen FastAPI backend with database integration.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.llm_engine import (
    generate_strategy_code,
    chat_about_code,
    is_llm_available,
    get_model_name
)
from app.services.executor import execute_strategy
from app.services.optimization_runner import run_optimization
from app.services.validators import (
    validate_api_request,
    BaseValidationError,
    SecurityValidationError,
    sanitize_filename,
    validate_file_path,
    StrategyValidator
)
from app.services.vbt_helpers import get_indicator_list
from app.services.code_verifier import CodeVerifier
from app.services.lessons_learned import LessonsLearnedStore
from app.db.database import engine
from sqlalchemy import text
from app.services.fundamentals_service import get_ticker_fundamentals
from app.services.research_agents import run_research_agents
from app.services.indicator_registry import get_indicator_catalog, get_indicator_categories

logger = logging.getLogger(__name__)

STRATEGY_CATALOG_DIR = Path(__file__).resolve().parent.parent.parent / "strategies" / "catalog"

router = APIRouter()


def _extract_error_details_from_result(result: dict, code: str) -> dict:
    """Extract structured error details from an executor result."""
    import re

    error_str = result.get("error", "Unknown error")
    traceback_str = result.get("traceback", "")
    stdout = result.get("output", "")

    # Extract line number from traceback
    line_match = re.search(r'File "<string>".*line (\d+)', traceback_str)
    if not line_match:
        line_match = re.search(r"line (\d+)", traceback_str)
    line_num = int(line_match.group(1)) if line_match else None
    line_content = None
    if line_num:
        lines = code.split("\n")
        if 0 <= line_num - 1 < len(lines):
            line_content = lines[line_num - 1]

    # Classify error type
    category = "execution"
    error_lower = error_str.lower()
    if "syntax" in error_lower or "invalid syntax" in error_lower:
        category = "syntax"
    elif "validation" in error_lower:
        category = "validation"
    elif "security" in error_lower or "forbidden" in error_lower:
        category = "security"
    elif "timeout" in error_lower:
        category = "timeout"

    # Try to classify with lessons store
    try:
        lessons_store = LessonsLearnedStore()
        error_type = lessons_store.classify_error(error_str) or "UNKNOWN"
        lesson = lessons_store.find_match(error_str)
        suggestion = (
            lesson["fix_description"]
            if lesson
            else _get_default_suggestion(error_type, error_str, line_content)
        )
        related_lesson = lesson["id"] if lesson else None
    except Exception:  # pylint: disable=broad-exception-caught
        error_type = "UNKNOWN"
        suggestion = _get_default_suggestion("UNKNOWN", error_str, line_content)
        related_lesson = None

    return {
        "type": error_type,
        "category": category,
        "message": error_str,
        "line": line_num,
        "line_content": line_content,
        "traceback": traceback_str,
        "stdout": stdout,
        "suggestion": suggestion,
        "related_lesson": related_lesson,
    }


def _get_default_suggestion(error_type: str, error_message: str, _line_content: Optional[str]) -> str:
    """Generate a default suggestion based on error type."""
    suggestions = {
        "VBT_COMPARISON_OPERATOR": (
            "Replace comparison operators (>, <, &, |) with VBT methods: "
            "ma_above(), ma_below(), rsi_below(), vbt.And(), vbt.Or()"
        ),
        "MISSING_PF_OBJECT": (
            "Ensure code ends with: pf = vbt.Portfolio.from_signals(...)"
        ),
        "SYNTAX_ERROR": (
            "Check for missing parentheses, quotes, or indentation issues."
        ),
        "DATA_LOADING": (
            "Use DataService.get_ohlcv_data(ticker, start, end) to load data."
        ),
        "PORTFOLIO_EMPTY": (
            "Portfolio has no trades. Check that entries/exits have True values."
        ),
        "MISSING_PARAMETERS": (
            "Add a '# Parameters' section at the top with tunable numeric variables."
        ),
        "IMPORT_ERROR": (
            "Only standard libraries + pandas/numpy/vectorbt are allowed."
        ),
    }
    return suggestions.get(
        error_type,
        f"Review the error and fix the code. Error: {error_message[:100]}",
    )


class GenerateRequest(BaseModel):
    """Request model for strategy generation."""
    prompt: str
    tickers: List[str]
    start_date: str
    end_date: str


class RunRequest(BaseModel):
    """Request model for strategy execution."""
    code: str
    use_database: bool = True
    tickers: Optional[List[str]] = None


class OptimizeRequest(BaseModel):
    """Request model for strategy optimization."""
    code: str
    strategy_params: Dict[str, Any]
    config: Dict[str, Any]
    tickers: Optional[List[str]] = None


class TrueWFORequest(BaseModel):
    """Request model for True Walk-Forward Optimization."""
    code: str
    strategy_params: Dict[str, Any]
    config: Dict[str, Any]
    tickers: Optional[List[str]] = None


class ChatRequest(BaseModel):
    """Request model for code chat."""
    code: str
    messages: List[Dict[str, str]]


class StrategyModel(BaseModel):
    """Model for saving/loading strategies."""
    name: str
    code: str



def _json_safe(value):
    """Recursively coerce non-finite floats (inf/-inf/nan) to None so the
    response never fails JSON serialization with 'Out of range float values
    are not JSON compliant'."""
    if isinstance(value, float):
        import math
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


@router.get("/ticker-info/{ticker}")
async def get_ticker_info(ticker: str):
    """
    Get fundamentals and metadata for a ticker.
    Returns quarterly financials with YoY/QoQ growth rates,
    metadata from stock_metadata, and latest price.
    """
    try:
        logger.info("Fetching ticker info for %s", ticker.upper())
        data = get_ticker_fundamentals(ticker)
        return {
            "success": True,
            "data": data,
            "message": f"Fundamentals loaded for {ticker.upper()}"
        }
    except Exception as e:
        logger.error("Error fetching ticker info for %s: %s", ticker.upper(), e)
        return {
            "success": False,
            "error": str(e),
            "data": None
        }


@router.get("/research/{ticker}")
async def get_ticker_research(ticker: str, mode: str = "simulated"):
    """
    Get research intelligence for a ticker.
    Spawns 4 research agents and returns a compiled document.

    Query params:
        mode: 'simulated' (default) or 'live'
    """
    try:
        logger.info("Fetching research for %s (mode=%s)", ticker.upper(), mode)
        data = run_research_agents(ticker, mode=mode)
        return {
            "success": True,
            "data": data,
            "message": f"Research compiled for {ticker.upper()}"
        }
    except Exception as e:
        logger.error("Error fetching research for %s: %s", ticker.upper(), e)
        return {
            "success": False,
            "error": str(e),
            "data": None
        }


@router.get("/health")
async def quantgen_health():
    """Health check for QuantGen module."""
    return {
        "status": "healthy",
        "module": "quantgen",
        "llm_model": get_model_name() if is_llm_available() else None,
        "features": {
            "strategy_generation": is_llm_available(),
            "backtesting": True,
            "optimization": True,
            "database_integration": True
        }
    }


@router.post("/generate")
async def generate_strategy(request: GenerateRequest):
    """
    Generate trading strategy code using AI.
    Uses database (PostgreSQL) for historical data instead of yfinance.
    """
    try:
        logger.info("Generating strategy for tickers: %s", request.tickers)

        if not is_llm_available():
            return {
                "success": False,
                "error": {
                    "type": "ConfigurationError",
                    "message": "Local LLM not available. Ensure the model server is running on port 11434 with kimi-k2.5:cloud model."
                },
                "data": None
            }

        # Validate input
        try:
            validated = validate_api_request('generate', {
                'prompt': request.prompt,
                'tickers': request.tickers,
                'start_date': request.start_date,
                'end_date': request.end_date
            })
        except BaseValidationError as e:
            return {
                "success": False,
                "error": {
                    "type": "ValidationError",
                    "message": e.message,
                    "field": e.field
                },
                "data": None
            }

        # Generate code
        code, error_msg = generate_strategy_code(
            validated.prompt,
            validated.tickers,
            validated.start_date,
            validated.end_date
        )

        if code is None:
            logger.error("Strategy generation failed: %s", error_msg)
            return {
                "success": False,
                "error": {
                    "type": "GenerationError",
                    "message": f"LLM Generation failed: {error_msg}",
                    "details": "Check backend logs and API Key configuration"
                },
                "data": {
                    "code": f"# Generation failed.\n# Error: {error_msg}",
                    "output": ""
                }
            }

        # Verify and auto-fix the generated code using CodeVerifier
        verifier = CodeVerifier()
        verification = verifier.verify_and_fix(
            code,
            tickers=request.tickers,
            max_attempts=3,
            record_lessons=True
        )

        if verification.success:
            msg = "Strategy generated and validated successfully"
            if verification.fix_attempts > 0:
                msg = f"Strategy generated and auto-fixed after {verification.fix_attempts} attempt(s)"
            return {
                "success": True,
                "data": {
                    "code": verification.code,
                    "output": verification.output,
                    "fix_attempts": verification.fix_attempts,
                    "lessons_applied": verification.lessons_applied,
                    "execution_time": verification.execution_time,
                },
                "message": msg
            }

        # Failed after all attempts - return structured error details
        error_details = None
        if verification.error_details:
            error_details = {
                "type": verification.error_details.type,
                "category": verification.error_details.category,
                "message": verification.error_details.message,
                "line": verification.error_details.line,
                "line_content": verification.error_details.line_content,
                "traceback": verification.error_details.traceback,
                "stdout": verification.error_details.stdout,
                "suggestion": verification.error_details.suggestion,
                "related_lesson": verification.error_details.related_lesson,
            }

        logger.error(
            "Strategy generation failed after %d attempts. Error: %s",
            verification.fix_attempts,
            verification.error_details.message if verification.error_details else "Unknown"
        )
        return {
            "success": False,
            "error": {
                "type": "GenerationError",
                "message": f"Failed after {verification.fix_attempts} attempts",
                "details": error_details,
            },
            "data": {
                "code": verification.code,
                "output": verification.output,
                "fix_attempts": verification.fix_attempts,
            }
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Strategy generation failed: %s", e)
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/run")
async def run_strategy_endpoint(request: RunRequest):
    """
    Execute a trading strategy.
    If use_database is True, fetches data from PostgreSQL instead of yfinance.
    """
    try:
        logger.info("Running strategy (length: %d chars)", len(request.code))

        # Validate input
        try:
            validated = validate_api_request('run', {'code': request.code})
        except BaseValidationError as e:
            return {
                "success": False,
                "error": {
                    "type": "ValidationError",
                    "message": e.message,
                    "field": e.field
                },
                "data": None
            }

        # Execute strategy with enhanced error extraction
        result = execute_strategy(validated.code, request.tickers)

        if result["success"]:
            logger.info("Strategy executed successfully")
            # --- Coach journal hook (failure-isolated) ---
            try:
                from app.services.coach.journal import upsert_strategy, record_strategy_run, record_signal
                _strat_name = f"quantgen:run:{','.join(request.tickers or ['default'])}"
                strat = upsert_strategy(kind="quantgen", name=_strat_name, params={"tickers": request.tickers})
                if strat is not None:
                    from datetime import datetime as _dt
                    _trades = (result.get("trades") or [])
                    _stats = result.get("stats") or {}
                    run = record_strategy_run(
                        strategy_id=strat.id,
                        started_at=_dt.utcnow(),
                        result_summary={"n_trades": len(_trades), "stats": _stats, "source": "quantgen.run"},
                    )
                    if run is not None:
                        for _t in _trades[:50]:
                            if not isinstance(_t, dict): continue
                            _tk = _t.get("ticker") or (request.tickers[0] if request.tickers else None)
                            if not _tk: continue
                            record_signal(
                                run_id=run.id, ticker=_tk,
                                signal_type=(_t.get("side") or "entry"),
                                as_of_date=_dt.utcnow().date(),
                                signal_strength=_t.get("pnl"),
                                payload=_t,
                            )
            except Exception as _e:
                logger.warning("Coach quantgen /run hook failed: %s", _e)
            return {
                "success": True,
                "data": _json_safe({
                    "output": result.get("output", ""),
                    "stats": result.get("stats", {}),
                    "equity": result.get("equity", []),
                    "ohlcv": result.get("ohlcv", []),
                    "drawdown": result.get("drawdown", {}),
                    "benchmark_drawdown": result.get("benchmark_drawdown", {}),
                    "trades": result.get("trades", []),
                    "indicators": result.get("indicators", [])
                }),
                "message": "Strategy executed successfully"
            }
        else:
            error_str = result.get("error", "Unknown error")
            logger.error("Strategy execution failed: %s", error_str)

            # Extract structured error details
            error_details = _extract_error_details_from_result(result, validated.code)

            return {
                "success": False,
                "error": {
                    "type": "ExecutionError",
                    "message": "Strategy execution failed",
                    "details": error_details
                },
                "data": {
                    "output": result.get("output", "")
                }
            }

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Strategy execution failed: %s", e)
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/optimize")
async def optimize_strategy_endpoint(request: OptimizeRequest):
    """
    Run parameter optimization on a strategy.
    Uses walk-forward optimization by default.
    """
    try:
        logger.info("Starting optimization with params: %s", request.strategy_params)

        # Validate input
        try:
            validated = validate_api_request('optimize', {
                'code': request.code,
                'strategy_params': request.strategy_params,
                'config': request.config
            })
        except BaseValidationError as e:
            return {
                "success": False,
                "error": {
                    "type": "ValidationError",
                    "message": e.message,
                    "field": e.field
                },
                "data": None
            }

        # Run optimization
        result = run_optimization(
            validated.code,
            validated.strategy_params,
            validated.config,
            request.tickers
        )

        # Check if there was an error (look anywhere in output, not just start)
        output_text = result.get("output", "")
        if "Optimization Error" in output_text:
            logger.error("Optimization failed: %s", output_text)
            return {
                "success": False,
                "error": {
                    "type": "OptimizationError",
                    "message": "Optimization failed",
                    "details": output_text
                },
                "data": result
            }

        logger.info("Optimization completed successfully")
        # --- Coach journal hook (failure-isolated) ---
        try:
            from app.services.coach.journal import upsert_strategy, record_strategy_run
            _mode = (validated.config or {}).get("mode", "walk_forward")
            _strat_name = f"quantgen:{_mode}:{','.join(request.tickers or ['default'])}"
            strat = upsert_strategy(kind="quantgen", name=_strat_name, params={"tickers": request.tickers, "mode": _mode})
            if strat is not None:
                from datetime import datetime as _dt
                record_strategy_run(
                    strategy_id=strat.id,
                    started_at=_dt.utcnow(),
                    result_summary={
                        "source": f"quantgen.{_mode}",
                        "tickers": request.tickers,
                        "params": validated.strategy_params,
                    },
                )
        except Exception as _e:
            logger.warning("Coach quantgen /optimize hook failed: %s", _e)
        return {
            "success": True,
            "data": result,
            "message": "Optimization completed successfully"
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        import traceback
        logger.error("Optimization failed: %s", e)
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "details": traceback.format_exc()
        }


@router.post("/true-wfo")
async def run_true_wfo(request: TrueWFORequest):
    """
    DEPRECATED: Use /optimize endpoint with mode='true_wfo' instead.

    This endpoint is maintained for backward compatibility but routes
    to the same code as /optimize with mode='true_wfo'.

    For each rolling window:
    1. Optimize parameters on training data
    2. Get signal from training window's last day for the NEXT day
    3. Trade only on that next day (first day of test window)
    4. Maintain portfolio state across windows
    """
    logger.warning("DEPRECATED: /true-wfo endpoint is deprecated. Use /optimize with mode='true_wfo' instead.")

    # Convert TrueWFORequest to OptimizeRequest format and call optimize endpoint
    opt_request = OptimizeRequest(
        code=request.code,
        strategy_params=request.strategy_params,
        config={**request.config, "mode": "true_wfo"},
        tickers=request.tickers
    )

    # Route to optimize endpoint
    return await optimize_strategy_endpoint(opt_request)


@router.post("/chat")
async def chat_about_code_endpoint(request: ChatRequest):
    """
    Chat about strategy code with AI.
    Maintains conversation context for iterative refinement.
    """
    try:
        logger.info("Chat request (code length: %d chars, messages: %d)", len(request.code), len(request.messages))

        if not is_llm_available():
            return {
                "success": False,
                "error": {
                    "type": "ConfigurationError",
                    "message": "Local LLM not available. Ensure the model server is running on port 11434 with kimi-k2.5:cloud model."
                },
                "data": None
            }

        # Call the chat function
        response, error_msg = chat_about_code(
            code=request.code,
            messages=request.messages
        )

        if error_msg:
            logger.error("Chat error: %s", error_msg)
            return {
                "success": False,
                "error": {
                    "type": "ChatError",
                    "message": error_msg
                },
                "data": {
                    "response": None
                }
            }

        logger.info("Chat response generated successfully")
        return {
            "success": True,
            "data": {
                "response": response
            }
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Chat failed: %s", e)
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/strategies")
async def list_strategies():
    """List all saved strategies."""
    try:
        import glob

        strategies_dir = "../strategies"
        if not os.path.exists(strategies_dir):
            os.makedirs(strategies_dir)

        files = glob.glob(os.path.join(strategies_dir, "*.py"))
        strategy_names = [os.path.basename(f) for f in files]

        return {
            "success": True,
            "data": {
                "strategies": strategy_names,
                "count": len(strategy_names)
            },
            "message": f"Found {len(strategy_names)} strategies"
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error listing strategies: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/strategies")
async def save_strategy(strategy: StrategyModel):
    """Save a strategy to file."""
    try:
        # Validate the strategy code before saving
        validation = StrategyValidator.validate_strategy_code(strategy.code)
        if not validation["valid"]:
            return {
                "success": False,
                "error": {
                    "type": "ValidationError",
                    "message": "Strategy code validation failed",
                    "details": validation["errors"]
                }
            }

        # Sanitize filename
        safe_name = sanitize_filename(strategy.name)

        strategies_dir = "../strategies"
        if not os.path.exists(strategies_dir):
            os.makedirs(strategies_dir)

        # Additional path validation
        path = os.path.join(strategies_dir, safe_name)
        if not validate_file_path(path, strategies_dir):
            raise SecurityValidationError("Invalid file path")

        # Save with backup if exists
        import shutil
        backup_path = None
        if os.path.exists(path):
            backup_path = f"{path}.backup"
            shutil.copy2(path, backup_path)
            logger.info("Created backup: %s", backup_path)

        with open(path, "w", encoding="utf-8") as f:
            f.write(strategy.code)

        logger.info("Strategy saved: %s", safe_name)

        return {
            "success": True,
            "data": {
                "path": path,
                "filename": safe_name,
                "backup_created": backup_path is not None
            },
            "message": f"Strategy '{safe_name}' saved successfully"
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error saving strategy: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/strategies/{name}")
async def get_strategy(name: str):
    """Get a saved strategy by name."""
    try:
        safe_name = sanitize_filename(name)
        strategies_dir = "../strategies"
        path = os.path.join(strategies_dir, safe_name)

        # Path validation
        if not validate_file_path(path, strategies_dir):
            raise SecurityValidationError("Invalid file path")

        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Strategy not found")

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        logger.info("Strategy loaded: %s", safe_name)

        return {
            "success": True,
            "data": {
                "name": name,
                "code": content,
                "filename": safe_name,
                "size": len(content)
            },
            "message": f"Strategy '{name}' loaded successfully"
        }

    except HTTPException:
        raise
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error loading strategy: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/strategies/{name}")
async def delete_strategy(name: str):
    """Delete a saved strategy."""
    try:
        safe_name = sanitize_filename(name)
        strategies_dir = "../strategies"
        path = os.path.join(strategies_dir, safe_name)

        # Path validation
        if not validate_file_path(path, strategies_dir):
            raise SecurityValidationError("Invalid file path")

        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Strategy not found")

        # Create backup before deletion
        import shutil
        backup_path = f"{path}.deleted"
        shutil.copy2(path, backup_path)
        os.remove(path)

        logger.info("Strategy deleted: %s (backup: %s)", safe_name, backup_path)

        return {
            "success": True,
            "data": {
                "filename": safe_name,
                "backup_path": backup_path
            },
            "message": f"Strategy '{name}' deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error deleting strategy: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/indicators")
async def list_indicators():
    """List available technical indicators."""
    try:
        indicators = get_indicator_list()
        return {
            "success": True,
            "data": {
                "indicators": indicators,
                "count": len(indicators)
            },
            "message": f"Found {len(indicators)} indicators"
        }
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error listing indicators: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/indicators/catalog")
async def list_indicator_catalog(
    category: Optional[str] = Query(None, description="Filter by category: momentum, trend, volatility, volume"),
    search: Optional[str] = Query(None, description="Search by name or description"),
):
    """
    List all available indicators with metadata from all sources.
    Sources: ta library, VectorBT, pandas-ta.
    """
    try:
        indicators = get_indicator_catalog(category=category, search=search)
        categories = get_indicator_categories()

        # Build a source count summary
        from collections import Counter
        source_counts = Counter(i["source"] for i in indicators)

        return {
            "success": True,
            "data": {
                "indicators": indicators,
                "count": len(indicators),
                "categories": categories,
                "source_counts": dict(source_counts),
            },
            "message": f"Found {len(indicators)} indicators"
        }
    except Exception as e:
        logger.error("Error listing indicator catalog: %s", e)
        return {
            "success": False,
            "error": str(e),
            "data": {"indicators": [], "count": 0}
        }


@router.get("/strategy-catalog")
async def list_strategy_catalog():
    """
    List all built-in strategies from the catalog, grouped by category.
    """
    try:
        catalog_dir = STRATEGY_CATALOG_DIR
        if not catalog_dir.exists():
            return {
                "success": True,
                "data": {"categories": [], "strategies": [], "count": 0},
                "message": "No strategies in catalog"
            }

        strategies = []
        for category_dir in sorted(catalog_dir.iterdir()):
            if not category_dir.is_dir():
                continue
            for json_file in sorted(category_dir.glob("*.json")):
                with open(json_file) as f:
                    meta = json.load(f)
                strategies.append(meta)

        # Group by category
        categories = {}
        for s in strategies:
            cat = s.get("category", "other")
            if cat not in categories:
                categories[cat] = []
            # Return metadata without the full code
            categories[cat].append({k: v for k, v in s.items() if k != "code"})

        return {
            "success": True,
            "data": {
                "categories": list(categories.keys()),
                "strategies_by_category": categories,
                "count": len(strategies),
            },
            "message": f"Found {len(strategies)} strategies"
        }
    except Exception as e:
        logger.error("Error listing strategy catalog: %s", e)
        return {"success": False, "error": str(e)}


@router.get("/strategy-catalog/{slug}")
async def get_strategy_code(slug: str):
    """
    Get a specific strategy's Python code and metadata.
    """
    try:
        catalog_dir = STRATEGY_CATALOG_DIR
        for json_file in catalog_dir.rglob(f"{slug}.json"):
            py_file = json_file.with_suffix(".py")
            if not py_file.exists():
                return {"success": False, "error": "Strategy code file not found"}

            with open(json_file) as f:
                metadata = json.load(f)
            with open(py_file) as f:
                code = f.read()

            return {
                "success": True,
                "data": {
                    "metadata": metadata,
                    "code": code,
                },
                "message": f"Loaded strategy: {metadata.get('name', slug)}"
            }

        return {"success": False, "error": f"Strategy '{slug}' not found"}
    except Exception as e:
        logger.error("Error loading strategy %s: %s", slug, e)
        return {"success": False, "error": str(e)}


@router.get("/latest-date")
async def get_latest_date():
    """Return the latest available trading date in the database."""
    try:
        # Query aapl table as a reliable S&P 1500 constituent
        query = text('SELECT MAX("Date") as latest_date FROM aapl')
        with engine.connect() as conn:
            result = conn.execute(query).fetchone()

        if result and result[0]:
            latest = str(result[0])
            # Ensure YYYY-MM-DD format
            if len(latest) > 10:
                latest = latest[:10]
            return {
                "success": True,
                "data": {"latest_date": latest},
                "message": f"Latest available date: {latest}"
            }
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Could not fetch latest date from DB: %s", e)

    # Fallback to today if DB is unavailable
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "success": True,
        "data": {"latest_date": today},
        "message": f"Database unavailable, fallback to today: {today}"
    }
