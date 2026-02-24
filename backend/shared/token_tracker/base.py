import logging
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError

from backend.shared.redis.base import get_redis

logger = logging.getLogger(__name__)


class TokenTracker:
    """
    Сервис для учёта использования токенов в Redis и PostgreSQL.
    Использует hybrid write-through pattern:
    - Redis как primary store для горячих данных текущего периода
    - PostgreSQL как долговременное хранилище (синхронизируется фоновым воркером)
    """

    def __init__(self, redis: Redis):
        self._redis = redis
        self._redis_available = True

    def _get_current_period(self) -> str:
        """Возвращает текущий период в формате YYYY-MM"""
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m")

    def _get_redis_key(self, user_id: int, period: Optional[str] = None) -> str:
        """Генерирует ключ Redis для хранения токенов пользователя за период"""
        if period is None:
            period = self._get_current_period()
        return f"tokens:user:{user_id}:{period}"

    def _get_events_key(self, user_id: int) -> str:
        """Генерирует ключ Redis для хранения сырых событий"""
        return f"token_events:user:{user_id}"

    async def _check_redis_available(self) -> bool:
        """Проверяет доступность Redis."""
        if not self._redis_available:
            return False

        try:
            await self._redis.ping()
            return True
        except RedisError:
            self._redis_available = False
            logger.error("Redis is unavailable. Token tracking will be disabled.")
            return False

    async def track_deepgram_usage(
        self, user_id: int, audio_seconds: float, metadata: Optional[Dict] = None
    ) -> bool:
        """
        Учитывает использование DeepGram API.

        Args:
            user_id: ID пользователя
            audio_seconds: количество секунд аудио
            metadata: дополнительная информация для аудита

        Returns:
            True если учёт успешен, False если нет
        """
        if not await self._check_redis_available():
            return False

        try:
            period = self._get_current_period()
            key = self._get_redis_key(user_id, period)
            current_time = time.time()

            # Инкрементируем счётчики в Redis Hash
            async with self._redis.pipeline() as pipe:
                # Увеличиваем deepgram_seconds
                await pipe.hincrbyfloat(key, "deepgram_seconds", audio_seconds)
                # Увеличиваем total_requests
                await pipe.hincrby(key, "total_requests", 1)
                # Обновляем last_updated
                await pipe.hset(key, "last_updated", current_time)
                # Устанавливаем TTL (35 дней ≈ 3024000 секунд)
                await pipe.expire(key, 3024000)

                await pipe.execute()

            # Записываем сырое событие
            await self._record_event(
                user_id=user_id,
                service_type="deepgram",
                amount=audio_seconds,
                metadata=metadata or {},
            )

            logger.debug(
                f"Tracked DeepGram usage: user={user_id}, "
                f"seconds={audio_seconds}, period={period}"
            )
            return True

        except RedisError as e:
            logger.error(f"Redis error during DeepGram tracking: {e}")
            self._redis_available = False
            return False

    async def track_deepl_usage(
        self, user_id: int, text: str, metadata: Optional[Dict] = None
    ) -> bool:
        """
        Учитывает использование DeepL API.

        Args:
            user_id: ID пользователя
            text: переведённый текст (для подсчёта символов)
            metadata: дополнительная информация для аудита

        Returns:
            True если учёт успешен, False если нет
        """
        if not await self._check_redis_available():
            return False

        try:
            # Подсчитываем количество символов (Unicode code points)
            character_count = len(text)

            period = self._get_current_period()
            key = self._get_redis_key(user_id, period)
            current_time = time.time()

            # Инкрементируем счётчики в Redis Hash
            async with self._redis.pipeline() as pipe:
                # Увеличиваем deepl_characters
                await pipe.hincrby(key, "deepl_characters", character_count)
                # Увеличиваем total_requests
                await pipe.hincrby(key, "total_requests", 1)
                # Обновляем last_updated
                await pipe.hset(key, "last_updated", current_time)
                # Устанавливаем TTL (35 дней)
                await pipe.expire(key, 3024000)

                await pipe.execute()

            # Записываем сырое событие
            await self._record_event(
                user_id=user_id,
                service_type="deepl",
                amount=float(character_count),
                metadata=metadata or {},
            )

            logger.debug(
                f"Tracked DeepL usage: user={user_id}, "
                f"characters={character_count}, period={period}"
            )
            return True

        except RedisError as e:
            logger.error(f"Redis error during DeepL tracking: {e}")
            self._redis_available = False
            return False

    async def _record_event(
        self, user_id: int, service_type: str, amount: float, metadata: Dict
    ) -> bool:
        """
        Записывает сырое событие в Redis для последующей синхронизации с PostgreSQL.
        """
        if not await self._check_redis_available():
            return False

        try:
            event_key = self._get_events_key(user_id)
            event_data = {
                "service_type": service_type,
                "amount": str(amount),
                "metadata": str(metadata),
                "timestamp": str(time.time()),
            }

            # Используем Redis List для буферизации событий
            await self._redis.rpush(event_key, str(event_data))
            # Устанавливаем TTL на 7 дней для событий
            await self._redis.expire(event_key, 604800)

            return True

        except RedisError as e:
            logger.error(f"Redis error during event recording: {e}")
            return False

    async def get_current_usage(
        self, user_id: int, period: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Возвращает текущее использование токенов за период из Redis.

        Args:
            user_id: ID пользователя
            period: период (по умолчанию текущий)

        Returns:
            Словарь с данными использования
        """
        if not await self._check_redis_available():
            return {
                "deepgram_seconds": 0.0,
                "deepl_characters": 0,
                "total_requests": 0,
                "last_updated": 0.0,
                "redis_available": False,
            }

        try:
            key = self._get_redis_key(user_id, period)
            data = await self._redis.hgetall(key)

            if not data:
                return {
                    "deepgram_seconds": 0.0,
                    "deepl_characters": 0,
                    "total_requests": 0,
                    "last_updated": 0.0,
                    "redis_available": True,
                }

            # Преобразуем байтовые строки в нужные типы
            result = {
                "deepgram_seconds": float(data.get(b"deepgram_seconds", b"0")),
                "deepl_characters": int(data.get(b"deepl_characters", b"0")),
                "total_requests": int(data.get(b"total_requests", b"0")),
                "last_updated": float(data.get(b"last_updated", b"0")),
                "redis_available": True,
            }

            return result

        except RedisError as e:
            logger.error(f"Redis error during usage retrieval: {e}")
            return {
                "deepgram_seconds": 0.0,
                "deepl_characters": 0,
                "total_requests": 0,
                "last_updated": 0.0,
                "redis_available": False,
            }

    async def get_periods_for_user(self, user_id: int) -> list:
        """
        Возвращает список периодов, за которые есть данные в Redis.

        Args:
            user_id: ID пользователя

        Returns:
            Список периодов в формате YYYY-MM
        """
        if not await self._check_redis_available():
            return []

        try:
            # Ищем все ключи для пользователя
            pattern = f"tokens:user:{user_id}:*"
            keys = await self._redis.keys(pattern)

            # Извлекаем периоды из ключей
            periods = []
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                # Формат: tokens:user:{user_id}:{period}
                parts = key.split(":")
                if len(parts) == 4:
                    periods.append(parts[3])

            return periods

        except RedisError as e:
            logger.error(f"Redis error during periods retrieval: {e}")
            return []

    async def sync_from_postgresql(self, user_id: int, db_session) -> bool:
        """
        Синхронизирует данные из PostgreSQL в Redis.
        Используется при запуске приложения или когда Redis пустой.

        Args:
            user_id: ID пользователя
            db_session: SQLAlchemy сессия

        Returns:
            True если синхронизация успешна, False если нет
        """
        if not await self._check_redis_available():
            return False

        try:
            # Получаем данные из PostgreSQL
            from sqlalchemy import text

            query = text("""
                SELECT 
                    period,
                    deepgram_seconds,
                    deepl_characters,
                    total_requests,
                    last_updated
                FROM token_usage
                WHERE user_id = :user_id
                ORDER BY period DESC
            """)

            result = db_session.execute(query, {"user_id": user_id})
            rows = result.fetchall()

            if not rows:
                # Нет данных в PostgreSQL
                return True

            # Записываем данные в Redis
            for row in rows:
                period = row.period
                key = self._get_redis_key(user_id, period)

                # Создаем Hash в Redis
                async with self._redis.pipeline() as pipe:
                    await pipe.hset(key, "deepgram_seconds", str(row.deepgram_seconds))
                    await pipe.hset(key, "deepl_characters", str(row.deepl_characters))
                    await pipe.hset(key, "total_requests", str(row.total_requests))
                    if row.last_updated:
                        await pipe.hset(
                            key, "last_updated", str(row.last_updated.timestamp())
                        )
                    # Устанавливаем TTL (35 дней)
                    await pipe.expire(key, 3024000)
                    await pipe.execute()

            logger.info(
                f"Synced token usage from PostgreSQL to Redis for user {user_id}"
            )
            return True

        except Exception as e:
            logger.error(f"Error syncing from PostgreSQL to Redis: {e}")
            return False


@lru_cache
def get_token_tracker() -> TokenTracker:
    """Возвращает экземпляр TokenTracker с кэшированием."""
    return TokenTracker(get_redis())
