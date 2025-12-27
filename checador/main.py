"""FastAPI application entry point."""

import logging
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from checador.api import admin, calibration, punch, sync
from checador.config import get_config
from checador.database import Database
from checador.sync import SyncWorker

from checador.autopunch import AutoPunchWorker
from checador.api import admin, calibration, punch, sync, autopunch

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Checador",
    description="Fingerprint Time Clock System",
    version="1.0.0"
)

# Get config
config = get_config()

# Initialize database
db = Database(config.database_path)

# Initialize sync worker
sync_worker = SyncWorker(config, db)
sync.set_sync_worker(sync_worker)

# Initialize auto-punch worker
autopunch_worker = AutoPunchWorker(config, db)
autopunch.set_autopunch_worker(autopunch_worker)

# Setup templates
template_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(template_dir))

# Include routers
app.include_router(admin.router)
app.include_router(punch.router)
app.include_router(sync.router)
app.include_router(calibration.router)
app.include_router(c.router)


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
    
    logger.info(f"Checador started on {config.app.host}:{config.app.port}")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    logger.info("Shutting down Checador...")
    sync_worker.stop()
    autopunch_worker.stop()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main kiosk interface."""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "device_id": config.app.device_id
    })


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """Admin interface."""
    return templates.TemplateResponse("admin.html", {
        "request": request
    })


@app.get("/calibration", response_class=HTMLResponse)
async def calibration_page(request: Request):
    """Camera calibration interface."""
    return templates.TemplateResponse("calibration.html", {
        "request": request
    })


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "device_id": config.app.device_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "checador.main:app",
        host=config.app.host,
        port=config.app.port,
        log_level="info"
    )