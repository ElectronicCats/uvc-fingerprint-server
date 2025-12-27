"""Auto-punch API endpoints."""

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from checador.api.admin import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autopunch", tags=["autopunch"])

# Will be set by main.py
autopunch_worker = None

# Store last punch result for UI feedback
last_punch_result = {
    "timestamp": 0,
    "success": False,
    "message": "",
    "user_name": "",
    "punch_type": "",
    "match_score": 0
}


def set_autopunch_worker(worker):
    """Set autopunch worker instance."""
    global autopunch_worker
    autopunch_worker = worker


def update_last_punch_result(success: bool, message: str, user_name: str = "", punch_type: str = "", match_score: int = 0):
    """Update last punch result for UI polling."""
    global last_punch_result
    last_punch_result = {
        "timestamp": time.time(),
        "success": success,
        "message": message,
        "user_name": user_name,
        "punch_type": punch_type,
        "match_score": match_score
    }


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


@router.get("/last-result")
async def get_last_result():
    """Get last punch result for UI feedback."""
    return last_punch_result


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