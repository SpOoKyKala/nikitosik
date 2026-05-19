"""
FastAPI main entry point for Self-Healing Dashboard.
Initializes database, starts background monitoring, and provides REST API endpoints.
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware

import config
import database
from services import checker, notifier


# ==============================================================================
# Application Lifecycle
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler - startup and shutdown."""
    # Startup
    notifier.logger.info("Starting Self-Healing Dashboard...")

    # Initialize database
    database.init_database()
    notifier.logger.info(f"Database initialized: {config.settings.db_path}")

    # Start background monitoring
    await checker.start_monitoring()
    notifier.logger.info("Background monitoring started")

    yield

    # Shutdown
    notifier.logger.info("Shutting down...")
    checker.stop_monitoring()
    database.db.close()
    notifier.logger.info("Shutdown complete")


# ==============================================================================
# FastAPI App Initialization
# ==============================================================================

app = FastAPI(
    title="Self-Healing Dashboard",
    description="Service monitoring and automatic recovery system",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# API Endpoints
# ==============================================================================

@app.get("/")
async def root():
    """Serve the main dashboard HTML."""
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/status")
async def get_status():
    """Get current status of all monitored services."""
    return database.get_dashboard_data()


@app.get("/api/services")
async def get_services():
    """Get list of configured services and their current status."""
    services_data = []
    for name, svc_config in config.SERVICES.items():
        status = database.get_service_status(name)
        services_data.append({
            "name": name,
            "host": svc_config.host,
            "port": svc_config.port,
            "check_url": svc_config.check_url,
            "recovery_type": svc_config.recovery_type,
            "enabled": svc_config.enabled,
            "is_up": status.get("is_up", False) if status else False,
            "consecutive_failures": status.get("consecutive_failures", 0) if status else 0,
        })
    return {"services": services_data}


@app.get("/api/logs")
async def get_logs(
    limit: int = Query(default=20, ge=1, le=100),
    service: Optional[str] = None
):
    """Get recent event logs."""
    logs = database.get_recent_logs(limit=limit, service_name=service)
    return {"logs": logs, "count": len(logs)}


@app.get("/api/recovery/history/{service_name}")
async def get_recovery_history(service_name: str, limit: int = Query(default=10, ge=1, le=50)):
    """Get recovery attempt history for a service."""
    history = database.get_recovery_history(service_name, limit=limit)
    return {"service": service_name, "history": history}


@app.post("/api/monitor/start")
async def start_monitor():
    """Manually start the monitoring loop."""
    if not checker.service_checker.running:
        await checker.start_monitoring()
        return {"status": "started", "message": "Monitoring started"}
    return {"status": "running", "message": "Monitoring already running"}


@app.post("/api/monitor/stop")
async def stop_monitor():
    """Manually stop the monitoring loop."""
    if checker.service_checker.running:
        checker.stop_monitoring()
        return {"status": "stopped", "message": "Monitoring stopped"}
    return {"status": "stopped", "message": "Monitoring not running"}


# ==============================================================================
# Health Check Endpoint
# ==============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint for the dashboard itself."""
    return {
        "status": "healthy",
        "service": "self-healing-dashboard",
        "monitoring_active": checker.service_checker.running
    }


# ==============================================================================
# Run Server
# ==============================================================================

if __name__ == "__main__":
    import uvicorn

    notifier.logger.info(f"Starting server on {config.settings.host}:{config.settings.port}")

    uvicorn.run(
        "main:app",
        host=config.settings.host,
        port=config.settings.port,
        reload=False,
        log_level="info"
    )