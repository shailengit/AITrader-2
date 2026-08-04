"""
TradeCraft - Unified Trading Application Backend
FastAPI application combining Sector Rotation, Stock Screener, and QuantGen.
"""

import os
import logging
from pathlib import Path

from dotenv import load_dotenv

# Load .env — check backend/ first, then project root
_env_backend = Path(__file__).resolve().parent.parent / ".env"
_env_root = _env_backend.parent / ".env"
for p in (_env_backend, _env_root):
    if p.exists():
        load_dotenv(dotenv_path=p, override=True)
        logging.info("Loaded environment from: %s", p)
        break
else:
    logging.warning("No .env file found at %s or %s", _env_backend, _env_root)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.db import database
from app.dependencies import register_exception_handlers
from app.services.structured_logging import configure_logging
from app.services.rate_limiter import add_rate_limit_middleware

# Configure structured logging
configure_logging()
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="TradeCraft API",
    description="Unified Trading Application - Sector Rotation, AI Screener, and QuantGen",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS configuration from environment
_DEFAULT_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
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
from app.routers import hypotheses, coach_strategy

# Include routers
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(sectors.router, prefix="/api", tags=["Sector Rotation"])
app.include_router(screener.router, prefix="/api/screener", tags=["AI Screener"])
app.include_router(quantgen.router, prefix="/api", tags=["QuantGen"])
app.include_router(earnings.router, prefix="/api", tags=["Earnings"])
app.include_router(markov.router, prefix="/api", tags=["Markov Chain Trader"])
app.include_router(coach.router, prefix="/api", tags=["Trade Coach"])
app.include_router(coach_strategy.router, prefix="/api", tags=["Coach"])
app.include_router(strategy_lab.router, prefix="/api", tags=["AI Strategy Builder"])
app.include_router(terminal.router, prefix="/api", tags=["Terminal"])
app.include_router(hypotheses.router, prefix="/api", tags=["Hypotheses"])


# Root endpoint
@app.get("/")
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
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
