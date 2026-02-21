import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import settings
from .crud import get_user_by_email
from .database import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token/")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.private_key, algorithm=settings.algorithm)


def create_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def create_tokens(user_id: int, email: str) -> dict:
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user_id), "email": email},
        expires_delta=access_token_expires,
    )
    refresh_token = create_refresh_token()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: Session = Depends(get_db)
) -> int:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.public_key, algorithms=[settings.algorithm]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    user = get_user_by_email(db, payload.get("email"))
    if user is None:
        raise credentials_exception
    return int(user_id)


def validate_refresh_token(refresh_token: str, db: Session) -> int:
    user = get_user_by_refresh_token(db, refresh_token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    return user.id


def get_user_by_refresh_token(db: Session, refresh_token: str):
    from . import models

    return (
        db.query(models.User).filter(models.User.refresh_token == refresh_token).first()
    )
