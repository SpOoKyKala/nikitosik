"""
FastAPI main entry point for Self-Healing Dashboard.
Initializes database, starts background monitoring, and provides REST API endpoints.
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware

import config
import database
from services import checker, notifier

# Start telegram bot in background
import os
import httpx

TELEGRAM_TOKEN = config.notif_config.telegram_bot_token
ALLOWED_CHAT_IDS = config.notif_config.telegram_chat_ids
if not isinstance(ALLOWED_CHAT_IDS, list):
    ALLOWED_CHAT_IDS = [5113409595]
TARGET_URL = os.getenv("TARGET_SERVICE_URL", "")


async def telegram_bot_loop():
    """Background telegram bot."""
    print("Starting telegram bot...", flush=True)
    offset = None
    
    async def send_msg(chat_id, text):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": text}
                )
        except:
            pass
    
    while True:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                params = {"timeout": 30}
                if offset: params["offset"] = offset
                
                resp = await client.get(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                    params=params
                )
                
                for update in resp.json().get("result", []):
                    offset = update["update_id"] + 1
                    if "message" in update:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"].get("text", "")
                        
                        if text.startswith("/") and chat_id in ALLOWED_CHAT_IDS:
                            cmd = text.split()[0]
                            if cmd == "/start":
                                await send_msg(chat_id, "Bot OK! /status /kill /startsrv")
                            elif cmd == "/status":
                                await send_msg(chat_id, f"Target: {TARGET_URL[:30]}...")
                            elif cmd == "/kill" and TARGET_URL:
                                try:
                                    await client.post(f"{TARGET_URL}/kill")
                                    await send_msg(chat_id, "KILLED")
                                except:
                                    await send_msg(chat_id, "ERR")
                            elif cmd == "/startsrv" and TARGET_URL:
                                try:
                                    await client.post(f"{TARGET_URL}/restart")
                                    await send_msg(chat_id, "STARTED")
                                except:
                                    await send_msg(chat_id, "ERR")
        except:
            pass
        await asyncio.sleep(2)


# ==============================================================================
# Application Lifecycle
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler - startup and shutdown."""
    notifier.logger.info("Starting Self-Healing Dashboard...")

    database.init_database()
    notifier.logger.info(f"Database initialized: {config.settings.db_path}")

    await checker.start_monitoring()
    notifier.logger.info("Background monitoring started")

    # Start telegram bot in background
    asyncio.create_task(telegram_bot_loop())

    yield

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
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/status")
async def get_status():
    return database.get_dashboard_data()


@app.get("/api/services")
async def get_services():
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
    logs = database.get_recent_logs(limit=limit, service_name=service)
    return {"logs": logs, "count": len(logs)}


@app.get("/api/recovery/history/{service_name}")
async def get_recovery_history(service_name: str, limit: int = Query(default=10, ge=1, le=50)):
    history = database.get_recovery_history(service_name, limit=limit)
    return {"service": service_name, "history": history}


@app.post("/api/monitor/start")
async def start_monitor():
    if not checker.service_checker.running:
        await checker.start_monitoring()
        return {"status": "started", "message": "Monitoring started"}
    return {"status": "running", "message": "Monitoring already running"}


@app.post("/api/monitor/stop")
async def stop_monitor():
    if checker.service_checker.running:
        checker.stop_monitoring()
        return {"status": "stopped", "message": "Monitoring stopped"}
    return {"status": "stopped", "message": "Monitoring not running"}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "self-healing-dashboard",
        "monitoring_active": checker.service_checker.running
    }


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