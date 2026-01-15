"""Device management API with security features."""

import secrets
import time
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from checador.config import get_config
from checador.database import Database, Punch

router = APIRouter(prefix="/api/devices", tags=["devices"])

# Challenge token storage: {challenge: (device_token, expiry_timestamp)}
_challenges: Dict[str, tuple] = {}


def _cleanup_expired_challenges():
    """Remove expired challenges."""
    now = time.time()
    expired = [k for k, v in _challenges.items() if v[1] < now]
    for k in expired:
        del _challenges[k]


class DeviceEnrollRequest(BaseModel):
    user_id: int
    token: str
    name: str
    admin_token: str


class PunchRequest(BaseModel):
    token: str
    challenge: str


class ChallengeRequest(BaseModel):
    token: str


class StatusResponse(BaseModel):
    enrolled: bool
    device_name: Optional[str] = None
    user_name: Optional[str] = None


@router.post("/enroll")
async def enroll_device(data: DeviceEnrollRequest, request: Request):
    """Enroll a new device with user-agent binding."""
    config = get_config()
    db = Database(config.database_path)

    # Get user-agent for binding
    user_agent = request.headers.get("user-agent", "")

    device = await db.register_device(
        data.user_id, data.token, data.name, user_agent=user_agent
    )
    if not device:
        raise HTTPException(status_code=400, detail="Device already registered or error")

    return {"success": True, "device_id": device.id}


@router.post("/challenge")
async def get_challenge(data: ChallengeRequest, request: Request):
    """
    Get a challenge token for punch authentication.
    Challenge is bound to the device token and expires.
    """
    config = get_config()
    db = Database(config.database_path)

    # Verify device exists
    device = await db.get_device_by_token(data.token)
    if not device:
        raise HTTPException(status_code=404, detail="Device not enrolled")

    # Check user-agent if enabled - auto-update on mismatch (token is primary auth)
    if config.device_security.user_agent_check_enabled:
        current_ua = request.headers.get("user-agent", "")
        if device.enrolled_user_agent and current_ua != device.enrolled_user_agent:
            # Token matches, so this is the same device - update stored User-Agent
            # This handles browser updates gracefully while maintaining security
            await db.update_device_user_agent(data.token, current_ua)

    # Cleanup old challenges
    _cleanup_expired_challenges()

    # Generate new challenge
    challenge = secrets.token_urlsafe(32)
    expiry = time.time() + config.device_security.challenge_expiry_seconds
    _challenges[challenge] = (data.token, expiry)

    return {"challenge": challenge, "expires_in": config.device_security.challenge_expiry_seconds}


@router.post("/punch")
async def punch_with_device(data: PunchRequest, request: Request):
    """
    Punch using a device token with challenge verification.

    Security checks:
    1. Challenge token must be valid and not expired
    2. Challenge must match the device token
    3. User-agent must match enrolled device
    4. Rate limiting: cooldown between punches
    5. Rate limiting: max punches per day
    """
    config = get_config()
    db = Database(config.database_path)

    # 1. Verify challenge
    _cleanup_expired_challenges()
    challenge_data = _challenges.pop(data.challenge, None)
    if not challenge_data:
        raise HTTPException(status_code=403, detail="Invalid or expired challenge")

    stored_token, expiry = challenge_data
    if stored_token != data.token:
        raise HTTPException(status_code=403, detail="Challenge token mismatch")

    if time.time() > expiry:
        raise HTTPException(status_code=403, detail="Challenge expired")

    # 2. Get device
    device = await db.get_device_by_token(data.token)
    if not device:
        raise HTTPException(status_code=404, detail="Device not enrolled")

    # 3. Check user-agent - auto-update on mismatch (token + challenge is primary auth)
    if config.device_security.user_agent_check_enabled:
        current_ua = request.headers.get("user-agent", "")
        if device.enrolled_user_agent and current_ua != device.enrolled_user_agent:
            # Token + challenge verified, so this is the same device - update stored User-Agent
            await db.update_device_user_agent(data.token, current_ua)

    # 4. Check cooldown period
    last_punch = await db.get_last_punch(device.user_id)
    if last_punch:
        seconds_since_last = (datetime.utcnow() - last_punch.timestamp_utc).total_seconds()
        if seconds_since_last < config.timeclock.punch_cooldown_seconds:
            remaining = int(config.timeclock.punch_cooldown_seconds - seconds_since_last)
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {remaining} seconds before punching again"
            )

    # 5. Check daily punch limit
    punch_count_today = await db.get_user_punch_count_today(device.user_id)
    if punch_count_today >= config.timeclock.max_punches_per_day:
        raise HTTPException(
            status_code=429,
            detail=f"Daily punch limit reached ({config.timeclock.max_punches_per_day})"
        )

    # Determine punch type
    punch_type = "IN"
    if last_punch and last_punch.punch_type == "IN":
        punch_type = "OUT"

    # Record punch
    timestamp = datetime.utcnow()
    punch = Punch(
        user_id=device.user_id,
        timestamp_utc=timestamp,
        timestamp_local=datetime.now(),
        punch_type=punch_type,
        match_score=100,
        device_id=f"device_{device.id}",
        synced=False
    )

    async with db.async_session() as session:
        session.add(punch)
        await session.commit()

    return {
        "success": True,
        "user_name": device.user.name,
        "punch_type": punch_type,
        "timestamp": timestamp.isoformat()
    }


@router.get("/my-status")
async def check_status(token: str, request: Request):
    """Check if device is enrolled and get status."""
    config = get_config()
    db = Database(config.database_path)

    device = await db.get_device_by_token(token)
    if device:
        # Auto-update user-agent if enabled and mismatched (token is primary auth)
        if config.device_security.user_agent_check_enabled:
            current_ua = request.headers.get("user-agent", "")
            if device.enrolled_user_agent and current_ua != device.enrolled_user_agent:
                # Token matches, so this is the same device - update stored User-Agent
                await db.update_device_user_agent(token, current_ua)

        return {
            "enrolled": True,
            "device_name": device.name,
            "user_name": device.user.name if device.user else None,
            "user_agent_match": True  # Always true now since we auto-update
        }

    return {"enrolled": False}


@router.delete("/{device_id}")
async def delete_device(device_id: int, admin_token: str):
    """Delete a device."""
    config = get_config()
    db = Database(config.database_path)

    success = await db.delete_device(device_id)
    return {"success": success}
