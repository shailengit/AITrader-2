"""
Health check router for TradeCraft API.
"""

from datetime import datetime
from fastapi import APIRouter

from app.db import database

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Health check endpoint with database status.
    Returns detailed health information for monitoring.
    """
    connected = database.test_connection()
    database.set_db_connected(connected)
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "api": "running",
            "database": {
                "connected": connected,
                "host": database.DB_HOST,
                "port": database.DB_PORT,
                "name": database.DB_NAME
            }
        }
    }


@router.get("/db-status")
async def database_status():
    """
    Database connection status endpoint for frontend polling.
    """
    connected = database.test_connection()
    database.set_db_connected(connected)
    return {
        "connected": connected,
        "status": "connected" if connected else "disconnected"
    }