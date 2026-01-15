"""Camera calibration endpoint."""

import logging

from fastapi import APIRouter, Response
from pydantic import BaseModel, field_validator

from checador.camera import CameraManager
from checador.config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calibration", tags=["calibration"])


class ROIRequest(BaseModel):
    x: int
    y: int
    width: int
    height: int
    
    @field_validator('x', 'y')
    @classmethod
    def validate_position(cls, v):
        if v < 0 or v > 1920:
            raise ValueError('Position must be between 0 and 1920')
        return v
    
    @field_validator('width', 'height')
    @classmethod
    def validate_size(cls, v):
        if v < 10 or v > 1920:
            raise ValueError('Size must be between 10 and 1920')
        return v


@router.get("/stream")
async def video_stream():
    """Stream camera feed for calibration."""
    config = get_config()
    camera = CameraManager(config)
    
    jpeg = camera.get_frame_jpeg()
    if jpeg is None:
        return Response(status_code=503, content="Camera not available")
    
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/roi")
async def get_roi():
    """Get current ROI settings."""
    config = get_config()
    return {
        "x": config.camera.roi_x,
        "y": config.camera.roi_y,
        "width": config.camera.roi_width,
        "height": config.camera.roi_height
    }


@router.post("/roi")
async def set_roi(roi: ROIRequest):
    """Set camera ROI - validation happens automatically via pydantic."""
    config = get_config()

    # Update config
    config.camera.roi_x = roi.x
    config.camera.roi_y = roi.y
    config.camera.roi_width = roi.width
    config.camera.roi_height = roi.height

    # Save to file with error handling
    try:
        config.save()
        logger.info(f"ROI updated: ({roi.x}, {roi.y}, {roi.width}, {roi.height})")
        return {"success": True, "message": "ROI saved"}
    except PermissionError as e:
        logger.error(f"Permission denied saving config: {e}")
        return {"success": False, "message": f"Permission denied: cannot write to config file"}
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return {"success": False, "message": f"Error saving config: {str(e)}"}