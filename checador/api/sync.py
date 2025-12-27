"""Sync status and control endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional


from checador.api.admin import verify_token
from checador.config import get_config
from checador.database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncStatusResponse(BaseModel):
    enabled: bool
    running: bool
    server_url: Optional[str]
    unsynced_count: int


# Will be set by main.py
sync_worker = None


def set_sync_worker(worker):
    """Set sync worker instance."""
    global sync_worker
    sync_worker = worker


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status():
    """Get sync status."""
    if not sync_worker:
        raise HTTPException(status_code=500, detail="Sync worker not initialized")
    
    status = await sync_worker.get_status()
    return SyncStatusResponse(**status)


@router.post("/trigger")
async def trigger_sync(token: str):
    """Manually trigger sync."""
    if not verify_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    if not sync_worker:
        raise HTTPException(status_code=500, detail="Sync worker not initialized")
    
    success = await sync_worker.sync_now()
    
    return {
        "success": success,
        "message": "Sync completed" if success else "Sync failed"
    }


from typing import Optional
