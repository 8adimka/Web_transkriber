from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.shared.user_settings.redis_store import get_settings_store

from .. import crud
from ..database import SessionLocal
from ..dependencies import get_current_user
from ..schemas import ChangePasswordRequest, UserProfileUpdate, UserSettingsUpdate

router = APIRouter(prefix="/user", tags=["user"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/profile")
async def get_user_profile(
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Получить профиль пользователя с настройками и базовой информацией.
    """
    profile = crud.get_user_profile(db, current_user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    return profile


@router.get("/settings")
async def get_user_settings(
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Получить настройки пользователя.
    Сначала проверяем Redis, если нет - берем из PostgreSQL.
    """
    # Пробуем получить из Redis
    redis_store = get_settings_store()
    redis_settings = await redis_store.get_settings(current_user_id)

    if redis_settings:
        # Удаляем метаданные
        clean_settings = {
            k: v for k, v in redis_settings.items() if not k.startswith("_")
        }
        return {
            "user_id": current_user_id,
            "source": "redis",
            "settings": clean_settings,
        }

    # Если нет в Redis, берем из PostgreSQL
    settings = crud.get_user_settings(db, current_user_id)
    return {
        "user_id": current_user_id,
        "source": "postgresql",
        "settings": {
            "microphone_enabled": settings.microphone_enabled,
            "tab_audio_enabled": settings.tab_audio_enabled,
            "original_language": settings.original_language,
            "translation_language": settings.translation_language,
            "avatar_url": settings.avatar_url,
            "updated_at": settings.updated_at,
        },
    }


@router.put("/settings")
async def update_user_settings(
    settings_update: UserSettingsUpdate,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Обновить настройки пользователя.
    Сохраняем в Redis (оперативные данные) и PostgreSQL (постоянное хранилище).
    """
    # Преобразуем Pydantic модель в словарь, исключая None значения
    update_dict = settings_update.dict(exclude_unset=True)

    # Проверяем, что есть что обновлять
    if not update_dict:
        raise HTTPException(status_code=400, detail="Нет данных для обновления")

    # 1. Обновляем в PostgreSQL (постоянное хранилище)
    updated_settings = crud.update_user_settings(db, current_user_id, update_dict)

    # 2. Сохраняем в Redis (оперативные данные)
    redis_store = get_settings_store()
    await redis_store.update_settings(current_user_id, update_dict)

    return {
        "user_id": current_user_id,
        "updated": True,
        "source": "both",
        "settings": {
            "microphone_enabled": updated_settings.microphone_enabled,
            "tab_audio_enabled": updated_settings.tab_audio_enabled,
            "original_language": updated_settings.original_language,
            "translation_language": updated_settings.translation_language,
            "avatar_url": updated_settings.avatar_url,
            "updated_at": updated_settings.updated_at,
        },
    }


@router.get("/stats/summary")
async def get_user_stats_summary(
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Получить сводную статистику пользователя (токены + профиль).
    Использует Redis как primary store, синхронизирует из PostgreSQL при необходимости.
    """
    # Получаем профиль
    profile = crud.get_user_profile(db, current_user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Получаем статистику токенов из Redis
    from datetime import datetime, timezone

    from backend.shared.token_tracker import get_token_tracker

    current_year = datetime.now(timezone.utc).year
    token_tracker = get_token_tracker()

    # Получаем данные за текущий год из Redis
    total_deepgram_seconds = 0.0
    total_deepl_characters = 0
    total_requests = 0

    # Получаем все периоды за текущий год из Redis
    periods = await token_tracker.get_periods_for_user(current_user_id)
    year_periods = [p for p in periods if p.startswith(f"{current_year}-")]

    if not year_periods:
        # Если в Redis нет данных за текущий год, пробуем синхронизировать из PostgreSQL
        await token_tracker.sync_from_postgresql(current_user_id, db)

        # Повторно получаем периоды
        periods = await token_tracker.get_periods_for_user(current_user_id)
        year_periods = [p for p in periods if p.startswith(f"{current_year}-")]

    # Суммируем данные по всем периодам за текущий год
    for period in year_periods:
        usage = await token_tracker.get_current_usage(current_user_id, period)
        if usage.get("redis_available", False):
            total_deepgram_seconds += usage.get("deepgram_seconds", 0.0)
            total_deepl_characters += usage.get("deepl_characters", 0)
            total_requests += usage.get("total_requests", 0)

    token_stats = {
        "total_deepgram_seconds": total_deepgram_seconds,
        "total_deepl_characters": total_deepl_characters,
        "total_requests": total_requests,
        "year": current_year,
        "source": "redis" if year_periods else "postgresql",
    }

    return {
        "profile": profile,
        "token_stats": token_stats,
    }


@router.get("/settings/redis/sync")
async def sync_settings_to_redis(
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Синхронизировать настройки из PostgreSQL в Redis.
    Полезно при перезапуске сервиса или очистке Redis.
    """
    # Получаем настройки из PostgreSQL
    settings = crud.get_user_settings(db, current_user_id)

    # Подготавливаем данные для Redis
    redis_data = {
        "microphone_enabled": settings.microphone_enabled,
        "tab_audio_enabled": settings.tab_audio_enabled,
        "original_language": settings.original_language,
        "translation_language": settings.translation_language,
        "avatar_url": settings.avatar_url,
    }

    # Сохраняем в Redis
    redis_store = get_settings_store()
    success = await redis_store.set_settings(current_user_id, redis_data)

    if success:
        return {
            "user_id": current_user_id,
            "synced": True,
            "message": "Настройки синхронизированы в Redis",
        }
    else:
        raise HTTPException(
            status_code=500, detail="Ошибка синхронизации настроек в Redis"
        )


@router.put("/profile")
async def update_user_profile(
    profile_update: UserProfileUpdate,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Обновить профиль пользователя (имя, аватар).
    """
    # Получаем пользователя
    user = crud.get_user_by_id(db, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Обновляем поля
    update_dict = profile_update.dict(exclude_unset=True)
    for key, value in update_dict.items():
        if hasattr(user, key):
            setattr(user, key, value)

    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "picture_url": user.picture_url,
        "auth_provider": user.auth_provider,
    }


@router.post("/change-password")
async def change_password(
    password_request: ChangePasswordRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Сменить пароль пользователя.
    """
    # Получаем пользователя
    user = crud.get_user_by_id(db, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Проверяем текущий пароль
    if not crud.verify_password(
        password_request.current_password, user.hashed_password
    ):
        raise HTTPException(status_code=401, detail="Текущий пароль неверен")

    # Хэшируем новый пароль
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

    new_password = password_request.new_password
    if len(new_password.encode("utf-8")) > 72:
        new_password = new_password[:72]

    hashed_password = pwd_context.hash(new_password)
    user.hashed_password = hashed_password

    db.add(user)
    db.commit()

    return {"success": True, "message": "Пароль успешно изменен"}
