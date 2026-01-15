"""Configuration management."""

import logging
from pathlib import Path
from typing import Optional

import toml
from pydantic import BaseModel
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class AppConfig(BaseModel):
    """Application configuration."""
    device_id: str = "CHECADOR-001"
    host: str = "0.0.0.0"
    port: int = 8000
    admin_password_hash: str
    ssl_enabled: bool = False
    ssl_certfile: str = "/etc/checador/ssl/cert.pem"
    ssl_keyfile: str = "/etc/checador/ssl/key.pem"


class CameraConfig(BaseModel):
    """Camera configuration."""
    device: str = "/dev/video0"
    resolution_width: int = 640
    resolution_height: int = 480
    roi_x: int = 0
    roi_y: int = 0
    roi_width: int = 640
    roi_height: int = 480


class FingerprintConfig(BaseModel):
    """Fingerprint matching configuration."""
    mindtct_path: str = "/usr/local/nbis/bin/mindtct"
    bozorth3_path: str = "/usr/local/nbis/bin/bozorth3"
    match_threshold: int = 40
    min_quality_score: int = 20
    required_templates: int = 3


class DatabaseConfig(BaseModel):
    """Database configuration."""
    path: str = "/var/lib/checador/checador.db"


class StorageConfig(BaseModel):
    """Storage configuration."""
    template_dir: str = "/var/lib/checador/templates"
    temp_dir: str = "/var/lib/checador/temp"


class TimeclockConfig(BaseModel):
    """Timeclock configuration."""
    antibounce_seconds: int = 10
    max_punches_per_day: int = 6  # Default: 3 in + 3 out
    punch_cooldown_seconds: int = 300  # 5 minutes between punches


class DeviceSecurityConfig(BaseModel):
    """Device punch security configuration."""
    user_agent_check_enabled: bool = True
    challenge_expiry_seconds: int = 300  # 5 minutes


class ServerConfig(BaseModel):
    """Server sync configuration."""
    enabled: bool = False
    url: str = ""
    api_key: str = ""
    sync_interval_minutes: int = 5


class AutoPunchConfig(BaseModel):
    """Auto-punch configuration."""
    enabled_on_startup: bool = False
    cooldown_seconds: int = 5
    difference_threshold: float = 0.15
    stable_frames: int = 3


class Config:
    """Main configuration class."""
    
    def __init__(self, config_path: str = "/etc/checador/config.toml"):
        self.config_path = Path(config_path)
        self._load()
    
    def _load(self):
        """Load configuration from TOML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        with open(self.config_path, 'r') as f:
            config_data = toml.load(f)
        
        self.app = AppConfig(**config_data.get('app', {}))
        self.camera = CameraConfig(**config_data.get('camera', {}))
        self.fingerprint = FingerprintConfig(**config_data.get('fingerprint', {}))
        self.database = DatabaseConfig(**config_data.get('database', {}))
        self.storage = StorageConfig(**config_data.get('storage', {}))
        self.timeclock = TimeclockConfig(**config_data.get('timeclock', {}))
        self.server = ServerConfig(**config_data.get('server', {}))
        self.autopunch = AutoPunchConfig(**config_data.get('autopunch', {}))
        self.device_security = DeviceSecurityConfig(**config_data.get('device_security', {}))
        
        # Convert paths
        self.database_path = Path(self.database.path)
        self.template_dir = Path(self.storage.template_dir)
        self.temp_dir = Path(self.storage.temp_dir)
        
        logger.info(f"Configuration loaded from {self.config_path}")
    
    def save(self):
        """Save configuration to TOML file."""
        config_data = {
            'app': self.app.model_dump(),
            'camera': self.camera.model_dump(),
            'fingerprint': self.fingerprint.model_dump(),
            'database': self.database.model_dump(),
            'storage': self.storage.model_dump(),
            'timeclock': self.timeclock.model_dump(),
            'server': self.server.model_dump(),
            'autopunch': self.autopunch.model_dump(),
            'device_security': self.device_security.model_dump(),
        }
        
        with open(self.config_path, 'w') as f:
            toml.dump(config_data, f)
        
        logger.info(f"Configuration saved to {self.config_path}")


# Global config instance
_config: Optional[Config] = None


def get_config(config_path: str = "/etc/checador/config.toml") -> Config:
    """Get or create global config instance."""
    global _config
    if _config is None:
        _config = Config(config_path)
    return _config