from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from .database import Base


class AuthProvider(str, Enum):
    LOCAL = "local"
    GOOGLE = "google"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    picture_url = Column(String, nullable=True)
    auth_provider = Column(String, default=AuthProvider.LOCAL.value, nullable=False)
    google_id = Column(String, unique=True, nullable=True)
    encrypted_google_refresh_token = Column(Text, nullable=True)
    refresh_token = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
