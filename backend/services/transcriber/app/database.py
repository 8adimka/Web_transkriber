import os
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# Получение настроек подключения из переменных окружения
POSTGRES_HOST = os.getenv("POSTGRES_TRANSCRIBER_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_TRANSCRIBER_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_TRANSCRIBER_DB", "transcriberdb")
POSTGRES_USER = os.getenv("POSTGRES_TRANSCRIBER_USER", "postgres")
POSTGRES_PASSWORD = os.getenv(
    "POSTGRES_TRANSCRIBER_PASSWORD", "transcriber_password_change_in_prod_123"
)

# Формирование URL для синхронного подключения
DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# Создание синхронного движка
engine = create_engine(DATABASE_URL, echo=False, future=True)

# Создание фабрики сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class Transcription(Base):
    __tablename__ = "transcriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, nullable=False, index=True
    )  # ID пользователя из auth сервиса
    filename = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    orig_language = Column(String(10), default="RU")
    translate_to = Column(String(10), nullable=True)  # NULL если не перевод
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    file_size = Column(Integer, nullable=True)  # Размер в байтах

    # Индексы для оптимизации запросов
    __table_args__ = (
        Index("idx_transcriptions_user_id", "user_id"),
        Index("idx_transcriptions_created_at", "created_at"),
    )


def get_db() -> Generator[Session, None, None]:
    """Зависимость для получения сессии БД"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Инициализация БД (создание таблиц)"""
    Base.metadata.create_all(bind=engine)
