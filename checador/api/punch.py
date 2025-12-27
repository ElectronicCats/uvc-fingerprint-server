"""Punch endpoint."""

import logging
from pathlib import Path

from fastapi import APIRouter
from typing import Optional
from pydantic import BaseModel

from checador.camera import CameraManager
from checador.config import get_config
from checador.database import Database
from checador.fingerprint import FingerprintMatcher
from checador.timeclock import TimeClock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["punch"])


class PunchResponse(BaseModel):
    success: bool
    message: str
    user_name: Optional[str] = None
    punch_type: Optional[str] = None
    match_score: Optional[int] = None


@router.post("/punch", response_model=PunchResponse)
async def punch():
    """Process a punch attempt."""
    config = get_config()
    db = Database(config.database_path)
    camera = CameraManager(config)
    matcher = FingerprintMatcher(config)
    timeclock = TimeClock(config, db)
    
    try:
        # Capture fingerprint
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        temp_image = config.temp_dir / f"probe_{timestamp}.png"
        
        success, error = camera.capture_fingerprint(temp_image)
        if not success:
            return PunchResponse(
                success=False,
                message=error or "Failed to capture fingerprint"
            )
        
        # Extract features
        success, probe_xyt, quality = matcher.extract_features(temp_image)
        if not success:
            return PunchResponse(
                success=False,
                message="Failed to extract fingerprint features"
            )
        
        # Get all templates
        templates = await db.get_all_templates()
        if not templates:
            return PunchResponse(
                success=False,
                message="No enrolled users"
            )
        
        # Build gallery
        gallery = [(t.id, Path(t.template_path)) for t in templates]
        
        # Identify
        match_result = matcher.identify(probe_xyt, gallery)
        
        if not match_result:
            return PunchResponse(
                success=False,
                message="Fingerprint not recognized"
            )
        
        template_id, match_score = match_result
        
        # Get user from template
        template = next(t for t in templates if t.id == template_id)
        user = await db.get_user(template.user_id)
        
        if not user or not user.active:
            return PunchResponse(
                success=False,
                message="User not found or inactive"
            )
        
        # Record punch
        success, punch, error = await timeclock.record_punch(user, match_score)
        
        if not success:
            return PunchResponse(
                success=False,
                message=error or "Failed to record punch"
            )
        
        return PunchResponse(
            success=True,
            message=f"Punch recorded successfully",
            user_name=user.name,
            punch_type=punch.punch_type,
            match_score=match_score
        )
        
    except Exception as e:
        logger.error(f"Punch error: {e}")
        return PunchResponse(
            success=False,
            message="Internal error"
        )


from datetime import datetime
from typing import Optional
