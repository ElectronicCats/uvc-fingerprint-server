"""Time clock logic: punch recording, auto-toggle, anti-bounce."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from checador.config import Config
from checador.database import Database, Punch, User

logger = logging.getLogger(__name__)


class TimeClock:
    """Time clock business logic."""
    
    def __init__(self, config: Config, database: Database):
        self.config = config
        self.db = database
    
    async def determine_punch_type(self, user: User) -> str:
        """
        Determine next punch type (IN or OUT) for user.
        Auto-toggles based on last punch.
        """
        last_punch = await self.db.get_last_punch(user.id)
        
        if last_punch is None:
            return "IN"
        
        # Toggle: if last was IN, next is OUT
        return "OUT" if last_punch.punch_type == "IN" else "IN"
    
    async def check_antibounce(self, user: User) -> bool:
        """
        Check if user is in anti-bounce window.
        
        Returns:
            True if punch should be blocked (too soon)
        """
        last_punch = await self.db.get_last_punch(user.id)
        
        if last_punch is None:
            return False
        
        # Check time since last punch
        now = datetime.utcnow()
        time_diff = (now - last_punch.timestamp_utc).total_seconds()
        
        if time_diff < self.config.timeclock.antibounce_seconds:
            logger.warning(
                f"Anti-bounce blocked: user_id={user.id}, "
                f"last_punch={time_diff:.1f}s ago"
            )
            return True
        
        return False
    
    async def record_punch(
        self, user: User, match_score: int
    ) -> Tuple[bool, Optional[Punch], Optional[str]]:
        """
        Record a punch for user.
        
        Returns:
            (success, punch_record, error_message)
        """
        try:
            # Check anti-bounce
            if await self.check_antibounce(user):
                return False, None, "Please wait before punching again"
            
            # Determine punch type
            punch_type = await self.determine_punch_type(user)
            
            # Record punch
            now_utc = datetime.utcnow()
            now_local = datetime.now()
            
            punch = await self.db.record_punch(
                user_id=user.id,
                timestamp_utc=now_utc,
                timestamp_local=now_local,
                punch_type=punch_type,
                match_score=match_score,
                device_id=self.config.app.device_id,
            )
            
            logger.info(
                f"Punch recorded: user={user.name} ({user.employee_code}), "
                f"type={punch_type}, score={match_score}"
            )
            
            return True, punch, None
            
        except Exception as e:
            logger.error(f"Error recording punch: {e}")
            return False, None, str(e)
