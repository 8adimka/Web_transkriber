import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

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


class TokenUsage(Base):
    """Долговременное хранилище использования токенов по месяцам"""

    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    period = Column(String(7), nullable=False)  # Формат: YYYY-MM
    deepgram_seconds = Column(
        Float, default=0.0
    )  # Секунды аудио, обработанные DeepGram
    deepl_characters = Column(Integer, default=0)  # Символы, переведённые DeepL
    total_requests = Column(Integer, default=0)  # Общее количество запросов к API
    last_updated = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    synced_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Связь с пользователем
    user = relationship("User", backref="token_usages")

    # Уникальный индекс на пользователя и период
    __table_args__ = (UniqueConstraint("user_id", "period", name="uq_user_period"),)


class TokenEvent(Base):
    """Сырые события использования токенов для аудита"""

    __tablename__ = "token_events"

    event_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    service_type = Column(String(20), nullable=False)  # "deepgram" или "deepl"
    amount = Column(
        Float, nullable=False
    )  # Количество (секунды для DeepGram, символы для DeepL)
    event_metadata = Column(JSON, nullable=True)  # Дополнительная информация
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Связь с пользователем
    user = relationship("User", backref="token_events")


class UserSettings(Base):
    """Настройки пользователя"""

    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True
    )
    microphone_enabled = Column(Boolean, default=True)
    tab_audio_enabled = Column(Boolean, default=True)
    original_language = Column(String(10), default="RU")
    translation_language = Column(String(10), default="EN")
    avatar_url = Column(Text, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Связь с пользователем
    user = relationship("User", backref="settings")
