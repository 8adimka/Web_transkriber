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
