"""
FastAPI dependencies and exception handlers for TradeCraft.
"""

import logging
from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.exceptions import (
    TradeCraftError,
    DatabaseError,
    SecurityError,
    ValidationError,
    LLMError,
    StrategyExecutionError,
    OptimizationError,
    DataNotFoundError,
)

logger = logging.getLogger(__name__)


def register_exception_handlers(app):
    """Register all custom exception handlers on the FastAPI app."""

    @app.exception_handler(TradeCraftError)
    async def handle_tradecraft_error(request: Request, exc: TradeCraftError):
        logger.warning(
            "TradeCraft error [%s]: %s - Details: %s",
            exc.code, exc.message, exc.details
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            }
        )

    @app.exception_handler(DatabaseError)
    async def handle_database_error(request: Request, exc: DatabaseError):
        logger.error("Database error: %s", exc.message, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": exc.code,
                    "message": "Database service temporarily unavailable. Please try again.",
                    "details": exc.details,
                }
            }
        )

    @app.exception_handler(SecurityError)
    async def handle_security_error(request: Request, exc: SecurityError):
        logger.warning("Security violation: %s", exc.message)
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            }
        )

    @app.exception_handler(ValidationError)
    async def handle_validation_error(request: Request, exc: ValidationError):
        logger.info("Validation error: %s", exc.message)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            }
        )

    @app.exception_handler(LLMError)
    async def handle_llm_error(request: Request, exc: LLMError):
        logger.error("LLM error: %s", exc.message)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": exc.code,
                    "message": "AI service temporarily unavailable. Please try again later.",
                    "details": exc.details,
                }
            }
        )

    @app.exception_handler(StrategyExecutionError)
    async def handle_strategy_error(request: Request, exc: StrategyExecutionError):
        logger.error("Strategy execution error: %s", exc.message)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            }
        )

    @app.exception_handler(OptimizationError)
    async def handle_optimization_error(request: Request, exc: OptimizationError):
        logger.error("Optimization error: %s", exc.message)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            }
        )

    @app.exception_handler(DataNotFoundError)
    async def handle_not_found_error(request: Request, exc: DataNotFoundError):
        logger.info("Data not found: %s", exc.message)
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            }
        )


import secrets
import os
from fastapi import HTTPException
from fastapi.security.utils import get_authorization_scheme_param


def _expected_token() -> str:
    """Return the configured API auth token (fail-closed if unset)."""
    token = os.getenv("API_AUTH_TOKEN", "").strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="API_AUTH_TOKEN is not configured in the root .env. "
                   "Set it to enable access to this API.",
        )
    return token


def _token_is_valid(provided: str) -> bool:
    expected = _expected_token()
    return bool(provided) and secrets.compare_digest(provided, expected)


def require_api_auth(request: "Request"):
    """Require a valid API token on the request.

    Accepts the token either as an ``X-API-Token`` header or as a
    ``Bearer`` token in the ``Authorization`` header. Comparison is
    constant-time to avoid timing side channels. Denies when the token is
    absent, wrong, or not configured (fail-closed).
    """
    provided = request.headers.get("X-API-Token", "")
    if not provided:
        auth = request.headers.get("Authorization", "")
        _, param = get_authorization_scheme_param(auth)
        provided = param or ""
    if not _token_is_valid(provided):
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing API token")
    return True


def require_ws_token(token: str) -> bool:
    """Validate a token passed to a WebSocket (query param) connection."""
    if not _token_is_valid(token):
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing API token")
    return True
