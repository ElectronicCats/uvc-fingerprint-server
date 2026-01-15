"""Main application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from checador.api import admin, calibration, device, punch, sync, autopunch
from checador.autopunch import AutoPunchWorker
from checador.config import get_config
from checador.database import Database
from checador.sync import SyncWorker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Initialize components
config = get_config()
db = Database(config.database_path)
sync_worker = SyncWorker(config, db)
autopunch_worker = AutoPunchWorker(config, db)

# Set autopunch worker in API module
autopunch.set_autopunch_worker(autopunch_worker)

# FastAPI app
app = FastAPI(title="Checador", version="1.0.0")

# Templates
templates = Jinja2Templates(directory="checador/templates")

# Include routers
app.include_router(admin.router)
app.include_router(calibration.router)
app.include_router(punch.router)
app.include_router(sync.router)
app.include_router(autopunch.router)
app.include_router(device.router)

# Mount static files
app.mount("/static", StaticFiles(directory="checador/static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main kiosk interface."""
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "device_id": config.app.device_id}
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """Admin panel."""
    return templates.TemplateResponse(
        "admin.html",
        {"request": request}
    )


@app.get("/calibration", response_class=HTMLResponse)
async def calibration_page(request: Request):
    """Camera calibration page."""
    return templates.TemplateResponse(
        "calibration.html",
        {"request": request}
    )


@app.on_event("startup")
async def startup():
    """Initialize on startup."""
    logger.info("Starting Checador...")
    
    # Initialize database
    await db.initialize()
    logger.info("Database initialized")
    
    # Start sync worker
    sync_worker.start()
    
    # Start auto-punch monitor
    autopunch_worker.start()
    
    # Enable auto-punch if configured
    if config.autopunch.enabled_on_startup:
        autopunch_worker.enable()
        logger.info("Auto-punch enabled on startup")
    
    logger.info(f"Checador started on {config.app.host}:{config.app.port}")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    logger.info("Shutting down Checador...")
    sync_worker.stop()
    autopunch_worker.stop()


if __name__ == "__main__":
    import uvicorn

    uvicorn_config = {
        "app": app,
        "host": config.app.host,
        "port": config.app.port,
        "log_level": "info",
    }

    if config.app.ssl_enabled:
        uvicorn_config["ssl_keyfile"] = config.app.ssl_keyfile
        uvicorn_config["ssl_certfile"] = config.app.ssl_certfile
        logger.info(f"SSL enabled - serving on https://{config.app.host}:{config.app.port}")

    uvicorn.run(**uvicorn_config)