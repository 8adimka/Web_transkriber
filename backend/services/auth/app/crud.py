from datetime import datetime, timezone

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models, schemas
from .security import get_encryption_manager

# Use argon2 as primary (no 72-byte limit) with bcrypt as fallback
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")


def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()


def get_user_by_id(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()


def create_user(db: Session, user: schemas.UserCreate):
    password = user.password
    if len(password.encode("utf-8")) > 72:
        password = password[:72]
    hashed_password = pwd_context.hash(password)
    db_user = models.User(email=user.email, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_user_by_google_id(db: Session, google_id: str):
    return db.query(models.User).filter(models.User.google_id == google_id).first()


def create_user_from_google(
    db: Session,
    email: str,
    google_id: str,
    full_name: str | None = None,
    picture_url: str | None = None,
    refresh_token: str | None = None,
):
    encrypted_refresh_token = None
    if refresh_token:
        encryption_manager = get_encryption_manager()
        encrypted_refresh_token = encryption_manager.encrypt(refresh_token)

    db_user = models.User(
        email=email,
        full_name=full_name,
        picture_url=picture_url,
        auth_provider=models.AuthProvider.GOOGLE.value,
        google_id=google_id,
        encrypted_google_refresh_token=encrypted_refresh_token,
        is_active=True,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def link_google_to_existing_user(
    db: Session, user: models.User, google_id: str, refresh_token: str | None = None
):
    user.google_id = google_id
    user.auth_provider = models.AuthProvider.GOOGLE.value

    if refresh_token:
        encryption_manager = get_encryption_manager()
        encrypted_refresh_token = encryption_manager.encrypt(refresh_token)
        user.encrypted_google_refresh_token = encrypted_refresh_token

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_refresh_token(db: Session, user: models.User, refresh_token: str):
    user.refresh_token = refresh_token
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_google_refresh_token(db: Session, user: models.User) -> str | None:
    if not user.encrypted_google_refresh_token:
        return None
    try:
        encryption_manager = get_encryption_manager()
        return encryption_manager.decrypt(user.encrypted_google_refresh_token)
    except Exception:
        return None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if len(plain_password.encode("utf-8")) > 72:
        plain_password = plain_password[:72]
    return pwd_context.verify(plain_password, hashed_password)


# UserSettings CRUD operations
def get_user_settings(db: Session, user_id: int):
    """Получить настройки пользователя, создавая их если не существуют"""
    settings = (
        db.query(models.UserSettings)
        .filter(models.UserSettings.user_id == user_id)
        .first()
    )
    if not settings:
        # Создаём настройки по умолчанию
        settings = models.UserSettings(
            user_id=user_id,
            microphone_enabled=False,  # Микрофон выключен по умолчанию
            tab_audio_enabled=True,
            original_language="RU",
            translation_language="EN",
            avatar_url=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_user_settings(db: Session, user_id: int, settings_update: dict):
    """Обновить настройки пользователя"""
    settings = get_user_settings(db, user_id)

    # Обновляем только переданные поля
    for key, value in settings_update.items():
        if hasattr(settings, key):
            setattr(settings, key, value)

    settings.updated_at = datetime.now(timezone.utc)
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def get_user_profile(db: Session, user_id: int):
    """Получить профиль пользователя с настройками и базовой информацией"""
    user = get_user_by_id(db, user_id)
    if not user:
        return None

    settings = get_user_settings(db, user_id)

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "picture_url": user.picture_url,
            "auth_provider": user.auth_provider,
            "created_at": user.created_at,
        },
        "settings": {
            "microphone_enabled": settings.microphone_enabled,
            "tab_audio_enabled": settings.tab_audio_enabled,
            "original_language": settings.original_language,
            "translation_language": settings.translation_language,
            "avatar_url": settings.avatar_url,
            "updated_at": settings.updated_at,
        },
    }
