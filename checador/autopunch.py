"""Auto-punch mode with finger detection."""

import logging
import time
from datetime import datetime
from pathlib import Path
from threading import Thread, Event
from typing import Optional

import cv2
import numpy as np

from checador.camera import CameraManager
from checador.config import Config
from checador.database import Database
from checador.fingerprint import FingerprintMatcher
from checador.timeclock import TimeClock

logger = logging.getLogger(__name__)


class AutoPunchWorker:
    """Background worker for auto-punch mode."""
    
    def __init__(self, config: Config, database: Database):
        self.config = config
        self.db = database
        self.camera = CameraManager(config)
        self.matcher = FingerprintMatcher(config)
        self.timeclock = TimeClock(config, database)
        
        self.running = False
        self.enabled = False
        self.thread: Optional[Thread] = None
        self.stop_event = Event()
        
        # Detection settings
        self.cooldown_seconds = 5
        self.last_punch_time = 0
        self.difference_threshold = 0.15  # 15% change to trigger
        self.stable_frames = 3  # Need 3 stable frames before processing
        
        # State
        self.baseline_frame: Optional[np.ndarray] = None
        self.stable_count = 0
    
    def start(self):
        """Start auto-punch monitoring."""
        if self.running:
            logger.warning("Auto-punch already running")
            return
        
        self.running = True
        self.stop_event.clear()
        self.thread = Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("Auto-punch monitoring started")
    
    def stop(self):
        """Stop auto-punch monitoring."""
        self.running = False
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        self.camera.close()
        logger.info("Auto-punch monitoring stopped")
    
    def enable(self):
        """Enable auto-punch processing."""
        self.enabled = True
        self.baseline_frame = None
        logger.info("Auto-punch enabled")
    
    def disable(self):
        """Disable auto-punch processing."""
        self.enabled = False
        logger.info("Auto-punch disabled")
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        logger.info("Auto-punch monitor loop started")
        
        while self.running:
            try:
                if not self.enabled:
                    time.sleep(0.5)
                    continue
                
                # Check cooldown
                if time.time() - self.last_punch_time < self.cooldown_seconds:
                    time.sleep(0.1)
                    continue
                
                # Capture frame
                frame = self.camera.capture_frame()
                if frame is None:
                    time.sleep(0.5)
                    continue
                
                # Convert to grayscale for comparison
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                
                # Initialize baseline
                if self.baseline_frame is None:
                    self.baseline_frame = gray.copy()
                    logger.debug("Baseline frame captured")
                    time.sleep(0.1)
                    continue
                
                # Detect change
                if self._detect_finger_placement(gray):
                    self.stable_count += 1
                    
                    if self.stable_count >= self.stable_frames:
                        logger.info("Finger detected, processing punch...")
                        self._process_punch()
                        
                        # Reset state
                        self.stable_count = 0
                        self.baseline_frame = None
                        self.last_punch_time = time.time()
                else:
                    # Reset if no finger
                    if self.stable_count > 0:
                        self.stable_count = 0
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in auto-punch monitor: {e}")
                time.sleep(1)
        
        logger.info("Auto-punch monitor loop stopped")
    
    def _detect_finger_placement(self, current_frame: np.ndarray) -> bool:
        """
        Detect if a finger was placed on sensor.
        
        Returns True if significant change detected.
        """
        if self.baseline_frame is None:
            return False
        
        # Calculate difference
        diff = cv2.absdiff(self.baseline_frame, current_frame)
        
        # Calculate percentage of change
        change_ratio = np.sum(diff > 30) / diff.size
        
        logger.debug(f"Change ratio: {change_ratio:.3f}")
        
        return change_ratio > self.difference_threshold
    
    def _process_punch(self):
        """Process fingerprint punch."""
        try:
            # Import here to avoid circular dependency
            from checador.api import autopunch as autopunch_api
            
            # Capture fingerprint
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            temp_image = self.config.temp_dir / f"autopunch_{timestamp}.png"
            
            success, error = self.camera.capture_fingerprint(temp_image)
            if not success:
                logger.warning(f"Auto-punch capture failed: {error}")
                self._play_error_sound()
                autopunch_api.update_last_punch_result(False, f"Capture failed: {error}")
                return
            
            # Extract features
            success, probe_xyt, quality = self.matcher.extract_features(temp_image)
            if not success:
                logger.warning("Auto-punch feature extraction failed")
                self._play_error_sound()
                autopunch_api.update_last_punch_result(False, "Feature extraction failed")
                return
            
            # Get all templates
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            templates = loop.run_until_complete(self.db.get_all_templates())
            loop.close()
            
            if not templates:
                logger.warning("No enrolled users")
                self._play_error_sound()
                autopunch_api.update_last_punch_result(False, "No enrolled users")
                return
            
            # Build gallery
            gallery = [(t.id, Path(t.template_path)) for t in templates]
            
            # Identify
            match_result = self.matcher.identify(probe_xyt, gallery)
            
            if not match_result:
                logger.warning("Fingerprint not recognized")
                self._play_error_sound()
                autopunch_api.update_last_punch_result(False, "Fingerprint not recognized")
                return
            
            template_id, match_score = match_result
            
            # Get user from template
            template = next(t for t in templates if t.id == template_id)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            user = loop.run_until_complete(self.db.get_user(template.user_id))
            loop.close()
            
            if not user or not user.active:
                logger.warning("User not found or inactive")
                self._play_error_sound()
                autopunch_api.update_last_punch_result(False, "User not found or inactive")
                return
            
            # Record punch
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success, punch, error = loop.run_until_complete(
                self.timeclock.record_punch(user, match_score)
            )
            loop.close()
            
            if not success:
                logger.warning(f"Punch recording failed: {error}")
                self._play_error_sound()
                autopunch_api.update_last_punch_result(False, f"Punch failed: {error}")
                return
            
            logger.info(
                f"Auto-punch successful: {user.name} ({user.employee_code}) - "
                f"{punch.punch_type}, score={match_score}"
            )
            self._play_success_sound(punch.punch_type)
            autopunch_api.update_last_punch_result(
                True, 
                "Punch recorded successfully",
                user.name,
                punch.punch_type,
                match_score
            )
            
        except Exception as e:
            logger.error(f"Error processing auto-punch: {e}")
            self._play_error_sound()
            from checador.api import autopunch as autopunch_api
            autopunch_api.update_last_punch_result(False, f"Error: {str(e)}")
    
    def _play_success_sound(self, punch_type: str):
        """Play success beep."""
        try:
            if punch_type == "IN":
                # Two short beeps for IN
                self._beep(0.1)
                time.sleep(0.1)
                self._beep(0.1)
            else:
                # One long beep for OUT
                self._beep(0.3)
        except Exception as e:
            logger.debug(f"Audio feedback failed: {e}")
    
    def _play_error_sound(self):
        """Play error beep."""
        try:
            # Three short beeps for error
            for _ in range(3):
                self._beep(0.05)
                time.sleep(0.05)
        except Exception as e:
            logger.debug(f"Audio feedback failed: {e}")
    
    def _beep(self, duration: float):
        """Play a beep sound."""
        import subprocess
        # Use system beep (PC speaker)
        try:
            subprocess.run(
                ['beep', '-l', str(int(duration * 1000))],
                timeout=1,
                capture_output=True
            )
        except:
            # Fallback to speaker-test if beep not available
            try:
                subprocess.run(
                    ['speaker-test', '-t', 'sine', '-f', '1000', '-l', '1'],
                    timeout=duration + 0.1,
                    capture_output=True
                )
            except:
                pass
    
    def get_status(self) -> dict:
        """Get auto-punch status."""
        return {
            "running": self.running,
            "enabled": self.enabled,
            "cooldown_seconds": self.cooldown_seconds,
            "last_punch": self.last_punch_time,
        }