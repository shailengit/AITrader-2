"""
TradeCraft - Unified Trading Application Backend
FastAPI application combining Sector Rotation, Stock Screener, and QuantGen.
"""

import os
import logging
from pathlib import Path

from dotenv import load_dotenv

# Load .env — single source of truth is the repo-root .env.
# (Fall back to backend/.env only if the root one is missing.)
_env_root = Path(__file__).resolve().parent.parent.parent / ".env"
_env_backend = Path(__file__).resolve().parent.parent / ".env"
for p in (_env_root, _env_backend):
    if p.exists():
        load_dotenv(dotenv_path=p, override=True)
        logging.info("Loaded environment from: %s", p)
        break
else:
    logging.warning("No .env file found at %s or %s", _env_root, _env_backend)

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.db import database
from app.dependencies import register_exception_handlers, require_api_auth
from app.services.structured_logging import configure_logging
from app.services.rate_limiter import add_rate_limit_middleware

# Configure structured logging
configure_logging()
logger = logging.getLogger(__name__)

# Create FastAPI app
# Interactive docs are off by default (they leak API surface). Set
# ENABLE_DOCS=true in the root .env to turn them on for local debugging.
_ENABLE_DOCS = os.getenv("ENABLE_DOCS", "false").lower() in ("1", "true", "yes")
app = FastAPI(
    title="TradeCraft API",
    description="Unified Trading Application - Sector Rotation, AI Screener, and QuantGen",
    version="1.0.0",
    docs_url="/docs" if _ENABLE_DOCS else None,
    redoc_url="/redoc" if _ENABLE_DOCS else None,
    openapi_url="/openapi.json" if _ENABLE_DOCS else None,
)

# CORS configuration from environment
# FRONTEND_PORT lets you run this app on a different port (e.g. alongside
# AITrader-1) without editing code — set FRONTEND_PORT=5175 and start the
# frontend with VITE_PORT=5175.
_FRONTEND_PORT = os.getenv("FRONTEND_PORT", "5173")
_DEFAULT_ORIGINS = [
    "http://localhost:3000",
    f"http://localhost:{_FRONTEND_PORT}",
    "http://localhost:5174",
    "http://127.0.0.1:3000",
    f"http://127.0.0.1:{_FRONTEND_PORT}",
    "http://127.0.0.1:5174",
]

_cors_env = os.getenv("CORS_ORIGINS")
if _cors_env:
    ALLOWED_ORIGINS = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]
    logger.info("Loaded CORS origins from environment: %s", ALLOWED_ORIGINS)
else:
    ALLOWED_ORIGINS = _DEFAULT_ORIGINS
    logger.info("Using default CORS origins (set CORS_ORIGINS env var for production)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    max_age=86400,
)


register_exception_handlers(app)
add_rate_limit_middleware(app)

# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.on_event("startup")
async def startup_event():
    """Check database connection on startup and ensure schema is up to date."""
    connected = database.test_connection()
    database.set_db_connected(connected)
    if connected:
        logger.info("Database connected: %s:%s/%s", database.DB_HOST, database.DB_PORT, database.DB_NAME)
        database.create_earnings_calendar_table()
    else:
        logger.warning("Database connection failed - some features will use fallback data")


# Import routers
from app.routers import sectors, screener, quantgen, health, earnings, markov, coach, strategy_lab, terminal
from app.routers import hypotheses, coach_strategy, alpaca

# Include routers. Health stays open (harmless, needed by load checks).
# Everything else requires the API token. The terminal router is protected
# inside terminal.py (its WebSocket validates the token as a query param).
_AUTH = [Depends(require_api_auth)]
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(sectors.router, prefix="/api", tags=["Sector Rotation"], dependencies=_AUTH)
app.include_router(screener.router, prefix="/api/screener", tags=["AI Screener"], dependencies=_AUTH)
app.include_router(quantgen.router, prefix="/api", tags=["QuantGen"], dependencies=_AUTH)
app.include_router(earnings.router, prefix="/api", tags=["Earnings"], dependencies=_AUTH)
app.include_router(markov.router, prefix="/api", tags=["Markov Chain Trader"], dependencies=_AUTH)
app.include_router(coach.router, prefix="/api", tags=["Trade Coach"], dependencies=_AUTH)
app.include_router(coach_strategy.router, prefix="/api", tags=["Coach"], dependencies=_AUTH)
app.include_router(strategy_lab.router, prefix="/api", tags=["AI Strategy Builder"], dependencies=_AUTH)
app.include_router(terminal.router, prefix="/api", tags=["Terminal"])
app.include_router(hypotheses.router, prefix="/api", tags=["Hypotheses"], dependencies=_AUTH)
app.include_router(alpaca.router, prefix="/api", tags=["Alpaca"], dependencies=_AUTH)


# Root endpoint (requires the API token; leaks no internal details)
@app.get("/", dependencies=[Depends(require_api_auth)])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "TradeCraft API",
        "version": "1.0.0",
        "description": "Unified Trading Application",
        "endpoints": {
            "health": "/api/health",
            "sectors": "/api/sectors",
            "stocks": "/api/stocks/{sector}",
            "top_momentum_leaders": "/api/top-momentum-leaders",
            "screener": "/api/screener/scan",
            "earnings_calendar": "/api/earnings/calendar",
            "earnings_next": "/api/earnings/next/{ticker}",
            "generate": "/api/generate",
            "run": "/api/run",
            "optimize": "/api/optimize",
            "strategies": "/api/strategies",
        },
        "database": {
            "connected": database.db_connected,
            "host": database.DB_HOST,
            "port": database.DB_PORT,
            "name": database.DB_NAME
        }
    }


if __name__ == "__main__":
    import uvicorn
    # PORT lets you run this backend on a different port (e.g. alongside
    # AITrader-1, which uses 8001). Default is 8000.
    _port = int(os.getenv("PORT", "8000"))
    # Bind to loopback by default so the API is not reachable from the LAN.
    # Set HOST=0.0.0.0 in the root .env only if you intentionally want it
    # reachable from other devices on your network (and keep the API token).
    _host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run(
        "app.main:app",
        host=_host,
        port=_port,
        reload=True,
        log_level="info"
    )
