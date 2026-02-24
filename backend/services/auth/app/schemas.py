from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class AuthResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None = None
    picture_url: str | None = None
    auth_provider: str | None = None
    access_token: str
    refresh_token: str
    token_type: str

    class Config:
        from_attributes = True


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class User(BaseModel):
    id: int
    email: EmailStr

    class Config:
        from_attributes = True


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None = None
    picture_url: str | None = None
    auth_provider: str | None = None

    class Config:
        from_attributes = True


class UserSettingsUpdate(BaseModel):
    """Схема для обновления настроек пользователя"""

    microphone_enabled: Optional[bool] = None
    tab_audio_enabled: Optional[bool] = None
    original_language: Optional[str] = None
    translation_language: Optional[str] = None
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True


class UserSettingsResponse(BaseModel):
    """Схема для ответа с настройками пользователя"""

    user_id: int
    microphone_enabled: bool
    tab_audio_enabled: bool
    original_language: str
    translation_language: str
    avatar_url: Optional[str] = None
    updated_at: datetime

    class Config:
        from_attributes = True


class UserProfileResponse(BaseModel):
    """Схема для ответа с профилем пользователя"""

    user: dict
    settings: dict

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    """Схема для обновления профиля пользователя"""

    full_name: Optional[str] = None
    picture_url: Optional[str] = None

    class Config:
        from_attributes = True


class ChangePasswordRequest(BaseModel):
    """Схема для смены пароля"""

    current_password: str
    new_password: str

    class Config:
        from_attributes = True


class ChangePasswordResponse(BaseModel):
    """Схема для ответа на смену пароля"""

    success: bool
    message: str

    class Config:
        from_attributes = True
