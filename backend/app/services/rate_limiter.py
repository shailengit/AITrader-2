"""
Simple in-memory rate limiter for TradeCraft API.
Uses token bucket algorithm per client IP.
"""

import time
import logging
from typing import Dict, Optional, Callable
from fastapi import Request, HTTPException, status

logger = logging.getLogger(__name__)

# In-memory store: {client_ip: {"tokens": float, "last_update": float}}
_rate_limit_store: Dict[str, Dict[str, float]] = {}

# Configuration
DEFAULT_RATE = 60  # requests per minute
DEFAULT_BURST = 10  # burst capacity


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(client_ip: str, rate: float = DEFAULT_RATE, burst: float = DEFAULT_BURST) -> bool:
    """Check if client_ip is within rate limit using token bucket."""
    now = time.time()
    window = 60.0  # per minute
    
    record = _rate_limit_store.get(client_ip)
    if record is None:
        _rate_limit_store[client_ip] = {"tokens": burst - 1, "last_update": now}
        return True
    
    # Replenish tokens based on time elapsed
    elapsed = now - record["last_update"]
    record["tokens"] = min(burst, record["tokens"] + elapsed * rate / window)
    record["last_update"] = now
    
    if record["tokens"] >= 1:
        record["tokens"] -= 1
        return True
    
    return False


def rate_limit_dependency(rate: float = DEFAULT_RATE, burst: float = DEFAULT_BURST):
    """Create a FastAPI dependency for rate limiting."""
    def _limit(request: Request):
        client_ip = _get_client_ip(request)
        if not _check_rate_limit(client_ip, rate, burst):
            logger.warning("Rate limit exceeded for %s", client_ip)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please slow down.",
                headers={"Retry-After": "60"}
            )
    return _limit


def add_rate_limit_middleware(app, rate: float = DEFAULT_RATE, burst: float = DEFAULT_BURST):
    """Add rate limiting middleware to FastAPI app."""
    from fastapi import Request
    from starlette.middleware.base import BaseHTTPMiddleware
    
    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Skip rate limiting for docs/static endpoints
            if request.url.path in ("/docs", "/redoc", "/openapi.json", "/", "/api/health"):
                return await call_next(request)

            client_ip = _get_client_ip(request)
            # Skip rate limiting for local development clients — the app's own
            # frontend (Markov JIT training, coach summaries, strategy classes)
            # legitimately bursts past the token bucket on page load.
            if client_ip in ("127.0.0.1", "::1", "localhost"):
                return await call_next(request)

            if not _check_rate_limit(client_ip, rate, burst):
                logger.warning("Rate limit exceeded for %s", client_ip)
                from starlette.responses import JSONResponse
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"error": "Rate limit exceeded. Please slow down."},
                    headers={"Retry-After": "60"}
                )
            
            return await call_next(request)
    
    app.add_middleware(RateLimitMiddleware)
