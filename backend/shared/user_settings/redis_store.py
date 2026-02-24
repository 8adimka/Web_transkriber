"""
Redis хранилище для оперативных настроек пользователя.
Настройки хранятся с TTL 7 дней для автоматической очистки неиспользуемых данных.
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional

from ..redis.base import get_redis


class UserSettingsRedisStore:
    """Redis хранилище для настроек пользователя"""

    def __init__(self):
        self.redis = get_redis()
        self.key_prefix = "user_settings:"
        self.ttl_days = 7  # TTL в днях

    def _get_key(self, user_id: int) -> str:
        """Получить ключ Redis для настроек пользователя"""
        return f"{self.key_prefix}{user_id}"

    async def get_settings(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Получить настройки пользователя из Redis.
        Возвращает None, если настройки не найдены.
        """
        key = self._get_key(user_id)
        data = await self.redis.get(key)

        if not data:
            return None

        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None

    async def set_settings(self, user_id: int, settings: Dict[str, Any]) -> bool:
        """
        Сохранить настройки пользователя в Redis.
        Возвращает True при успешном сохранении.
        """
        key = self._get_key(user_id)

        # Добавляем метаданные
        settings_with_meta = {
            **settings,
            "_updated_at": datetime.utcnow().isoformat(),
            "_user_id": user_id,
        }

        try:
            data = json.dumps(settings_with_meta)
            ttl_seconds = self.ttl_days * 24 * 60 * 60
            await self.redis.setex(key, ttl_seconds, data)
            return True
        except Exception:
            return False

    async def update_settings(
        self, user_id: int, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Обновить настройки пользователя в Redis.
        Возвращает обновленные настройки или None при ошибке.
        """
        # Получаем текущие настройки
        current = await self.get_settings(user_id)
        if not current:
            current = {}

        # Удаляем метаданные из обновлений
        updates_clean = {k: v for k, v in updates.items() if not k.startswith("_")}

        # Обновляем настройки
        updated = {**current, **updates_clean}

        # Сохраняем
        success = await self.set_settings(user_id, updated)
        if success:
            return updated
        return None

    async def delete_settings(self, user_id: int) -> bool:
        """Удалить настройки пользователя из Redis"""
        key = self._get_key(user_id)
        deleted = await self.redis.delete(key)
        return deleted > 0

    async def get_all_user_ids(self) -> list[int]:
        """Получить список всех user_id, у которых есть настройки в Redis"""
        pattern = f"{self.key_prefix}*"
        keys = await self.redis.keys(pattern)

        user_ids = []
        for key in keys:
            try:
                # Извлекаем user_id из ключа
                user_id_str = key.decode().replace(self.key_prefix, "")
                user_ids.append(int(user_id_str))
            except (ValueError, AttributeError):
                continue

        return user_ids


# Глобальный экземпляр хранилища
_settings_store: Optional[UserSettingsRedisStore] = None


def get_settings_store() -> UserSettingsRedisStore:
    """Получить глобальный экземпляр хранилища настроек"""
    global _settings_store
    if _settings_store is None:
        _settings_store = UserSettingsRedisStore()
    return _settings_store
