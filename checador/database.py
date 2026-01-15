"""Database models and operations for Checador."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, relationship, selectinload, sessionmaker

Base = declarative_base()


class User(Base):
    """User/employee model."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    employee_code = Column(String(50), unique=True, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    templates = relationship("Template", back_populates="user", cascade="all, delete-orphan")
    punches = relationship("Punch", back_populates="user")
    devices = relationship("Device", back_populates="user", cascade="all, delete-orphan")


class Template(Base):
    """Fingerprint template model."""
    __tablename__ = "templates"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    template_path = Column(String(500), nullable=False)
    quality = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    user = relationship("User", back_populates="templates")


class Punch(Base):
    """Time punch record."""
    __tablename__ = "punches"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    timestamp_utc = Column(DateTime, nullable=False)
    timestamp_local = Column(DateTime, nullable=False)
    punch_type = Column(String(10), nullable=False)  # IN or OUT
    match_score = Column(Integer, nullable=False)
    device_id = Column(String(100), nullable=False)
    synced = Column(Boolean, default=False, nullable=False)
    sync_error = Column(String(500), nullable=True)
    sync_at = Column(DateTime, nullable=True)
    
    user = relationship("User", back_populates="punches")


class Device(Base):
    """Enrolled device model."""
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String(100), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Security fields
    enrolled_user_agent = Column(String(500), nullable=True)

    user = relationship("User", back_populates="devices")


class Setting(Base):
    """Application settings key-value store."""
    __tablename__ = "settings"
    
    key = Column(String(100), primary_key=True)
    value = Column(String(1000), nullable=False)


class Database:
    """Database manager."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
        )
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
    
    async def initialize(self):
        """Create all tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def get_session(self) -> AsyncSession:
        """Get a new database session."""
        return self.async_session()
    
    async def create_user(
        self, name: str, employee_code: str
    ) -> User:
        """Create a new user."""
        async with self.async_session() as session:
            user = User(name=name, employee_code=employee_code)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user
    
    async def get_user(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        async with self.async_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            return result.scalar_one_or_none()
    
    async def get_user_by_code(self, employee_code: str) -> Optional[User]:
        """Get user by employee code."""
        async with self.async_session() as session:
            result = await session.execute(
                select(User).where(User.employee_code == employee_code)
            )
            return result.scalar_one_or_none()
    
    async def list_users(self, active_only: bool = True) -> List[User]:
        """List all users."""
        async with self.async_session() as session:
            query = select(User)
            if active_only:
                query = query.where(User.active == True)
            result = await session.execute(query.order_by(User.name))
            return list(result.scalars().all())
    
    async def deactivate_user(self, user_id: int):
        """Deactivate a user."""
        async with self.async_session() as session:
            user = await session.get(User, user_id)
            if user:
                user.active = False
                await session.commit()

    async def delete_user(self, user_id: int) -> bool:
        """Delete a user and all associated data."""
        async with self.async_session() as session:
            user = await session.get(User, user_id)
            if user:
                # Manually delete punches first (no cascade on Punch)
                await session.execute(
                    delete(Punch).where(Punch.user_id == user_id)
                )
                # Templates and Devices are handled by cascade
                await session.delete(user)
                await session.commit()
                return True
            return False

    async def register_device(
        self, user_id: int, token: str, name: str, user_agent: str = None
    ) -> Optional[Device]:
        """Register a new device for a user."""
        async with self.async_session() as session:
            # Check if token exists
            result = await session.execute(select(Device).where(Device.token == token))
            if result.scalar_one_or_none():
                return None

            device = Device(
                user_id=user_id,
                token=token,
                name=name,
                enrolled_user_agent=user_agent,
            )
            session.add(device)
            try:
                await session.commit()
                await session.refresh(device)
                return device
            except:
                await session.rollback()
                return None

    async def get_device_by_token(self, token: str) -> Optional[Device]:
        """Get device by token."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Device)
                .where(Device.token == token)
                .options(selectinload(Device.user))
            )
            return result.scalar_one_or_none()

    async def delete_device(self, device_id: int) -> bool:
        """Delete a device."""
        async with self.async_session() as session:
            device = await session.get(Device, device_id)
            if device:
                await session.delete(device)
                await session.commit()
                return True
            return False

    async def update_device_user_agent(self, token: str, user_agent: str) -> bool:
        """Update device's stored User-Agent (for handling browser updates)."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Device).where(Device.token == token)
            )
            device = result.scalar_one_or_none()
            if device:
                device.enrolled_user_agent = user_agent
                await session.commit()
                return True
            return False

    async def list_devices(self) -> List[Device]:
        """List all enrolled devices with their users."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Device).options(selectinload(Device.user)).order_by(Device.created_at.desc())
            )
            return list(result.scalars().all())
    
    async def add_template(
        self, user_id: int, template_path: str, quality: int
    ) -> Template:
        """Add fingerprint template for user."""
        async with self.async_session() as session:
            template = Template(
                user_id=user_id,
                template_path=template_path,
                quality=quality,
            )
            session.add(template)
            await session.commit()
            await session.refresh(template)
            return template
    
    async def get_user_templates(self, user_id: int) -> List[Template]:
        """Get all templates for a user."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Template).where(Template.user_id == user_id)
            )
            return list(result.scalars().all())
    
    async def get_all_templates(self) -> List[Template]:
        """Get all templates for matching."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Template)
                .join(User)
                .where(User.active == True)
                .order_by(Template.quality.desc())
            )
            return list(result.scalars().all())
    
    async def record_punch(
        self,
        user_id: int,
        timestamp_utc: datetime,
        timestamp_local: datetime,
        punch_type: str,
        match_score: int,
        device_id: str,
    ) -> Punch:
        """Record a punch."""
        async with self.async_session() as session:
            punch = Punch(
                user_id=user_id,
                timestamp_utc=timestamp_utc,
                timestamp_local=timestamp_local,
                punch_type=punch_type,
                match_score=match_score,
                device_id=device_id,
            )
            session.add(punch)
            await session.commit()
            await session.refresh(punch)
            return punch
    
    async def get_last_punch(self, user_id: int) -> Optional[Punch]:
        """Get user's most recent punch."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Punch)
                .where(Punch.user_id == user_id)
                .order_by(Punch.timestamp_utc.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def get_user_punch_count_today(self, user_id: int) -> int:
        """Get the number of punches for a user today (local time)."""
        async with self.async_session() as session:
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            result = await session.execute(
                select(func.count(Punch.id))
                .where(Punch.user_id == user_id)
                .where(Punch.timestamp_local >= today_start)
            )
            return result.scalar() or 0

    async def get_unsynced_punches(self, limit: int = 100) -> List[Punch]:
        """Get punches that haven't been synced."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Punch)
                .where(Punch.synced == False)
                .order_by(Punch.timestamp_utc)
                .limit(limit)
            )
            return list(result.scalars().all())
    
    async def mark_punches_synced(self, punch_ids: List[int]):
        """Mark punches as synced."""
        async with self.async_session() as session:
            for punch_id in punch_ids:
                punch = await session.get(Punch, punch_id)
                if punch:
                    punch.synced = True
                    punch.sync_at = datetime.utcnow()
            await session.commit()
    
    async def mark_punch_sync_error(self, punch_id: int, error: str):
        """Mark punch sync error."""
        async with self.async_session() as session:
            punch = await session.get(Punch, punch_id)
            if punch:
                punch.sync_error = error[:500]
            await session.commit()
    
    async def get_punches(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        user_id: Optional[int] = None,
    ) -> List[Punch]:
        """Get punches with optional filters."""
        async with self.async_session() as session:
            query = select(Punch)
            
            if start_date:
                query = query.where(Punch.timestamp_local >= start_date)
            if end_date:
                query = query.where(Punch.timestamp_local <= end_date)
            if user_id:
                query = query.where(Punch.user_id == user_id)
            
            query = query.order_by(Punch.timestamp_local)
            result = await session.execute(query)
            return list(result.scalars().all())
    
    async def get_setting(self, key: str) -> Optional[str]:
        """Get a setting value."""
        async with self.async_session() as session:
            setting = await session.get(Setting, key)
            return setting.value if setting else None
    
    async def set_setting(self, key: str, value: str):
        """Set a setting value."""
        async with self.async_session() as session:
            setting = await session.get(Setting, key)
            if setting:
                setting.value = value
            else:
                setting = Setting(key=key, value=value)
                session.add(setting)
            await session.commit()