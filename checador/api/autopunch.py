"""Auto-punch API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from checador.api.admin import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autopunch", tags=["autopunch"])

# Will be set by main.py
autopunch_worker = None


def set_autopunch_worker(worker):
    """Set autopunch worker instance."""
    global autopunch_worker
    autopunch_worker = worker


class AutoPunchStatusResponse(BaseModel):
    running: bool
    enabled: bool
    cooldown_seconds: int
    last_punch: float


@router.get("/status", response_model=AutoPunchStatusResponse)
async def get_status():
    """Get auto-punch status."""
    if not autopunch_worker:
        raise HTTPException(status_code=500, detail="Auto-punch not initialized")
    
    status = autopunch_worker.get_status()
    return AutoPunchStatusResponse(**status)


@router.post("/enable")
async def enable_autopunch(token: str):
    """Enable auto-punch mode."""
    if not verify_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    if not autopunch_worker:
        raise HTTPException(status_code=500, detail="Auto-punch not initialized")
    
    autopunch_worker.enable()
    logger.info("Auto-punch enabled via API")
    
    return {"success": True, "message": "Auto-punch enabled"}


@router.post("/disable")
async def disable_autopunch(token: str):
    """Disable auto-punch mode."""
    if not verify_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    if not autopunch_worker:
        raise HTTPException(status_code=500, detail="Auto-punch not initialized")
    
    autopunch_worker.disable()
    logger.info("Auto-punch disabled via API")
    
    return {"success": True, "message": "Auto-punch disabled"}