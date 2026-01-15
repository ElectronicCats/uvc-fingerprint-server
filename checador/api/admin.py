"""Admin endpoints: enrollment, user management."""

import logging
import secrets
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from time import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel

from checador.auth import AuthManager
from checador.camera import CameraManager
from checador.config import get_config
from checador.database import Database, User
from checador.fingerprint import FingerprintMatcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    success: bool
    token: Optional[str] = None


class EnrollRequest(BaseModel):
    name: str
    employee_code: str
    token: str


class EnrollResponse(BaseModel):
    success: bool
    user_id: Optional[int] = None
    message: str
    required_templates: Optional[int] = None


class CaptureResponse(BaseModel):
    success: bool
    quality: int
    sample_number: int
    message: str


class UserResponse(BaseModel):
    id: int
    name: str
    employee_code: str
    active: bool
    created_at: datetime
    template_count: int


# Token store with expiration
TOKEN_EXPIRY_HOURS = 8
active_tokens: Dict[str, datetime] = {}

# Simple rate limiting for login
login_attempts: Dict[str, List[float]] = defaultdict(list)
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 60


def check_rate_limit(ip: str) -> bool:
    """Check if IP has exceeded login rate limit."""
    now = time()
    # Clean old attempts
    login_attempts[ip] = [t for t in login_attempts[ip] if now - t < LOGIN_WINDOW_SECONDS]
    
    # Check limit
    if len(login_attempts[ip]) >= MAX_LOGIN_ATTEMPTS:
        return False
    
    # Record attempt
    login_attempts[ip].append(now)
    return True


def verify_token(token: str) -> bool:
    """Verify admin token and check expiration."""
    if token not in active_tokens:
        return False
    
    # Check if expired
    if datetime.utcnow() > active_tokens[token]:
        logger.info("Token expired, removing")
        del active_tokens[token]
        return False
    
    return True


@router.post("/login", response_model=LoginResponse)
async def login(request: Request, login_data: LoginRequest):
    """Admin login with rate limiting and session expiration."""
    # Rate limiting
    client_ip = request.client.host
    if not check_rate_limit(client_ip):
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait."
        )
    
    config = get_config()
    auth = AuthManager(config)
    
    if auth.verify_password(login_data.password):
        # Generate token with expiration
        token = secrets.token_urlsafe(32)
        active_tokens[token] = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)
        
        logger.info(f"Admin login successful from {client_ip}")
        return LoginResponse(success=True, token=token)
    
    logger.warning(f"Admin login failed from {client_ip}")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid password"
    )


@router.post("/logout")
async def logout(token: str):
    """Admin logout."""
    if token in active_tokens:
        del active_tokens[token]
    return {"success": True}


@router.post("/enroll/start", response_model=EnrollResponse)
async def start_enrollment(request: EnrollRequest):
    """Start user enrollment process."""
    if not verify_token(request.token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    config = get_config()
    db = Database(config.database_path)
    
    try:
        # Check if employee code exists
        existing = await db.get_user_by_code(request.employee_code)
        if existing:
            return EnrollResponse(
                success=False,
                message=f"Employee code {request.employee_code} already exists"
            )
        
        # Create user
        user = await db.create_user(request.name, request.employee_code)
        
        logger.info(f"Enrollment started for {user.name} ({user.employee_code})")
        return EnrollResponse(
            success=True,
            user_id=user.id,
            message="User created, ready for fingerprint capture",
            required_templates=config.fingerprint.required_templates
        )
        
    except Exception as e:
        logger.error(f"Enrollment error: {e}")
        return EnrollResponse(success=False, message=str(e))


@router.post("/enroll/capture", response_model=CaptureResponse)
async def capture_sample(user_id: int, sample_number: int, token: str):
    """Capture fingerprint sample during enrollment."""
    if not verify_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    config = get_config()
    db = Database(config.database_path)
    camera = CameraManager(config)
    matcher = FingerprintMatcher(config)
    
    try:
        # Get user
        user = await db.get_user(user_id)
        if not user:
            return CaptureResponse(
                success=False,
                quality=0,
                sample_number=sample_number,
                message="User not found"
            )
        
        # Generate filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{user.employee_code}_{sample_number}_{timestamp}"
        image_path = config.template_dir / f"{filename}.png"
        
        # Capture fingerprint
        success, error = camera.capture_fingerprint(image_path)
        if not success:
            return CaptureResponse(
                success=False,
                quality=0,
                sample_number=sample_number,
                message=error or "Capture failed"
            )
        
        # Extract features
        success, xyt_path, quality = matcher.extract_features(image_path)
        if not success:
            return CaptureResponse(
                success=False,
                quality=0,
                sample_number=sample_number,
                message="Feature extraction failed"
            )
        
        # Check quality
        if quality < config.fingerprint.min_quality_score:
            return CaptureResponse(
                success=False,
                quality=quality,
                sample_number=sample_number,
                message=f"Low quality fingerprint (score={quality}, minimum={config.fingerprint.min_quality_score})"
            )
        
        # Store template
        await db.add_template(
            user_id=user.id,
            template_path=str(xyt_path),
            quality=quality
        )
        
        logger.info(f"Sample {sample_number} captured for user {user.employee_code}, quality={quality}")
        
        return CaptureResponse(
            success=True,
            quality=quality,
            sample_number=sample_number,
            message="Sample captured successfully"
        )
        
    except Exception as e:
        logger.error(f"Capture error: {e}")
        return CaptureResponse(
            success=False,
            quality=0,
            sample_number=sample_number,
            message=str(e)
        )


@router.get("/users", response_model=List[UserResponse])
async def list_users(token: str):
    """List all users."""
    if not verify_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    config = get_config()
    db = Database(config.database_path)
    
    users = await db.list_users(active_only=False)
    
    result = []
    for user in users:
        templates = await db.get_user_templates(user.id)
        result.append(UserResponse(
            id=user.id,
            name=user.name,
            employee_code=user.employee_code,
            active=user.active,
            created_at=user.created_at,
            template_count=len(templates)
        ))
    
    return result


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(user_id: int, token: str):
    """Deactivate a user."""
    if not verify_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    config = get_config()
    db = Database(config.database_path)
    
    await db.deactivate_user(user_id)
    logger.info(f"User {user_id} deactivated")
    
    return {"success": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, token: str):
    """Delete a user permanently."""
    if not verify_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    config = get_config()
    db = Database(config.database_path)

    success = await db.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info(f"User {user_id} deleted")

    return {"success": True}


class DeviceResponse(BaseModel):
    id: int
    user_id: int
    user_name: str
    user_code: str
    name: str
    token: str
    created_at: datetime


@router.get("/devices", response_model=List[DeviceResponse])
async def list_devices(token: str):
    """List all enrolled devices."""
    if not verify_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    config = get_config()
    db = Database(config.database_path)

    devices = await db.list_devices()

    return [
        DeviceResponse(
            id=device.id,
            user_id=device.user_id,
            user_name=device.user.name if device.user else "Unknown",
            user_code=device.user.employee_code if device.user else "Unknown",
            name=device.name,
            token=device.token,
            created_at=device.created_at
        )
        for device in devices
    ]


@router.delete("/devices/{device_id}")
async def delete_device(device_id: int, token: str):
    """Delete a device."""
    if not verify_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    config = get_config()
    db = Database(config.database_path)

    success = await db.delete_device(device_id)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")

    logger.info(f"Device {device_id} deleted")

    return {"success": True}