"""Camera capture and ROI management for UVC fingerprint reader."""

import logging
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

from checador.config import Config

logger = logging.getLogger(__name__)


class CameraManager:
    """Manages V4L2 camera capture and ROI processing."""
    
    def __init__(self, config: Config):
        self.config = config
        self.cap: Optional[cv2.VideoCapture] = None
        self._is_open = False
    
    def open(self) -> bool:
        """Open camera device."""
        try:
            device = self.config.camera.device
            logger.info(f"Opening camera: {device}")
            
            self.cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
            
            if not self.cap.isOpened():
                logger.error(f"Failed to open camera: {device}")
                return False
            
            # Set camera properties
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.camera.resolution_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera.resolution_height)
            
            self._is_open = True
            logger.info("Camera opened successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error opening camera: {e}")
            return False
    
    def close(self):
        """Close camera device."""
        if self.cap:
            self.cap.release()
            self._is_open = False
            logger.info("Camera closed")
    
    def capture_frame(self) -> Optional[np.ndarray]:
        """Capture a single frame from camera."""
        if not self._is_open:
            if not self.open():
                return None
        
        ret, frame = self.cap.read()
        if not ret:
            logger.error("Failed to capture frame")
            return None
        
        return frame
    
    def get_roi_frame(self) -> Optional[np.ndarray]:
        """Capture frame and extract ROI."""
        frame = self.capture_frame()
        if frame is None:
            return None
        
        # Extract ROI
        roi = self.config.camera
        x, y, w, h = roi.roi_x, roi.roi_y, roi.roi_width, roi.roi_height
        
        # Validate ROI
        height, width = frame.shape[:2]
        if x + w > width or y + h > height:
            logger.warning(f"ROI exceeds frame bounds, using full frame")
            return frame
        
        return frame[y:y+h, x:x+w]
    
    def capture_fingerprint(self, output_path: Path) -> Tuple[bool, Optional[str]]:
        """
        Capture fingerprint image and save to disk.
        
        Returns:
            (success, error_message)
        """
        try:
            roi_frame = self.get_roi_frame()
            if roi_frame is None:
                return False, "Failed to capture frame"
            
            # Convert to grayscale for NBIS (requires 8-bit depth)
            if len(roi_frame.shape) == 3:
                gray_frame = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2GRAY)
            else:
                gray_frame = roi_frame
            
            # Save image
            cv2.imwrite(str(output_path), gray_frame)
            logger.info(f"Fingerprint image saved: {output_path}")
            return True, None
            
        except Exception as e:
            error = f"Error capturing fingerprint: {e}"
            logger.error(error)
            return False, error
    
    def get_frame_jpeg(self) -> Optional[bytes]:
        """Get current frame as JPEG bytes for streaming."""
        frame = self.capture_frame()
        if frame is None:
            return None
        
        ret, jpeg = cv2.imencode('.jpg', frame)
        if not ret:
            return None
        
        return jpeg.tobytes()
    
    def test_camera(self) -> dict:
        """Test camera and return diagnostic info."""
        result = {
            "device": self.config.camera.device,
            "accessible": False,
            "opened": False,
            "frame_captured": False,
            "resolution": None,
            "roi_valid": False,
            "error": None
        }
        
        try:
            # Check if device exists
            device_path = Path(self.config.camera.device)
            result["accessible"] = device_path.exists()
            
            if not result["accessible"]:
                result["error"] = f"Device {self.config.camera.device} not found"
                return result
            
            # Try to open
            if self.open():
                result["opened"] = True
                
                # Try to capture
                frame = self.capture_frame()
                if frame is not None:
                    result["frame_captured"] = True
                    result["resolution"] = f"{frame.shape[1]}x{frame.shape[0]}"
                    
                    # Validate ROI
                    roi = self.config.camera
                    if (roi.roi_x + roi.roi_width <= frame.shape[1] and
                        roi.roi_y + roi.roi_height <= frame.shape[0]):
                        result["roi_valid"] = True
                
                self.close()
            else:
                result["error"] = "Failed to open camera"
                
        except Exception as e:
            result["error"] = str(e)
        
        return result