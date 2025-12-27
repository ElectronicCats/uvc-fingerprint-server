"""Fingerprint matching using NBIS."""

import logging
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from checador.config import Config

logger = logging.getLogger(__name__)


class FingerprintMatcher:
    """Handle fingerprint feature extraction and matching."""
    
    def __init__(self, config: Config):
        self.config = config
        self._verify_nbis_tools()
        
        self.mindtct_path = self.config.fingerprint.mindtct_path
        self.bozorth3_path = self.config.fingerprint.bozorth3_path
    
    def _verify_nbis_tools(self):
        """Verify NBIS tools are available."""
        for tool in [self.config.fingerprint.mindtct_path,
                     self.config.fingerprint.bozorth3_path]:
            if not Path(tool).exists():
                raise FileNotFoundError(f"NBIS tool not found: {tool}")
    
    def extract_features(self, image_path: Path) -> Tuple[bool, Optional[Path], int]:
        """
        Extract minutiae features from fingerprint image.
        
        Returns:
            (success, xyt_path, quality_score)
        """
        try:
            xyt_path = image_path.with_suffix('.xyt')
            
            # Run mindtct
            result = subprocess.run(
                [self.mindtct_path, str(image_path), str(xyt_path.with_suffix(''))],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.error(f"mindtct failed: {result.stderr}")
                return False, None, 0
            
            # Check if XYT file was created
            if not xyt_path.exists():
                logger.error("XYT file not created")
                return False, None, 0
            
            # Parse quality score from output
            quality = self._parse_quality(result.stdout)
            
            logger.info(f"Features extracted: {xyt_path} (quality={quality})")
            return True, xyt_path, quality
            
        except subprocess.TimeoutExpired:
            logger.error("mindtct timeout")
            return False, None, 0
        except Exception as e:
            logger.error(f"Feature extraction error: {e}")
            return False, None, 0
    
    def _parse_quality(self, mindtct_output: str) -> int:
        """Parse quality score from mindtct output."""
        try:
            for line in mindtct_output.split('\n'):
                if 'Quality' in line or 'NFIQ' in line:
                    # Extract number from line
                    parts = line.split()
                    for part in parts:
                        if part.isdigit():
                            return int(part)
            
            # Default quality if not found
            return 50
        except:
            return 50
    
    def match(self, probe_xyt: Path, gallery_xyt: Path) -> int:
        """
        Match two fingerprint templates.
        
        Returns:
            Match score (higher is better)
        """
        try:
            result = subprocess.run(
                [self.bozorth3_path, str(probe_xyt), str(gallery_xyt)],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.error(f"bozorth3 failed: {result.stderr}")
                return 0
            
            # Parse score from output
            score = int(result.stdout.strip())
            return score
            
        except subprocess.TimeoutExpired:
            logger.error("bozorth3 timeout")
            return 0
        except Exception as e:
            logger.error(f"Matching error: {e}")
            return 0
    
    def identify(
        self, 
        probe_xyt: Path, 
        gallery: List[Tuple[int, Path]]
    ) -> Optional[Tuple[int, int]]:
        """
        Identify fingerprint against gallery.
        
        Args:
            probe_xyt: Probe fingerprint template
            gallery: List of (template_id, xyt_path) tuples
        
        Returns:
            (template_id, score) if match found, None otherwise
        """
        best_match_id = None
        best_score = 0
        
        for template_id, gallery_xyt in gallery:
            score = self.match(probe_xyt, gallery_xyt)
            
            if score > best_score:
                best_score = score
                best_match_id = template_id
        
        logger.info(f"Best match: template_id={best_match_id}, score={best_score}, threshold={self.config.fingerprint.match_threshold}")
        
        if best_score >= self.config.fingerprint.match_threshold:
            logger.info(f"Match found: template_id={best_match_id}, score={best_score}")
            return (best_match_id, best_score)
        else:
            logger.info(f"No match found (best score={best_score}, threshold={self.config.fingerprint.match_threshold})")
            return None