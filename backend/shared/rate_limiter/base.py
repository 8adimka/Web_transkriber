import logging
import random
from functools import lru_cache
from time import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from backend.shared.redis.base import get_redis

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, redis: Redis):
        self._redis = redis
        self._redis_available = True

    async def _check_redis_available(self) -> bool:
        """Проверяет доступность Redis."""
        if not self._redis_available:
            return False

        try:
            await self._redis.ping()
            return True
        except RedisError:
            self._redis_available = False
            logger.error("Redis is unavailable. All requests will be blocked.")
            return False

    async def is_limited(
        self,
        identifier: str,
        endpoint: str,
        max_requests: int,
        window_seconds: int,
        identifier_type: str = "ip",
    ) -> bool:
        """
        Проверяет, превышен ли лимит запросов.

        Args:
            identifier: IP адрес или user_id
            endpoint: Имя эндпоинта
            max_requests: Максимальное количество запросов
            window_seconds: Окно времени в секундах
            identifier_type: Тип идентификатора ('ip' или 'user')

        Returns:
            True если лимит превышен, False если нет
        """
        # Если Redis недоступен - блокируем все запросы
        if not await self._check_redis_available():
            logger.warning(
                f"Redis unavailable, blocking request from {identifier_type}:{identifier} to {endpoint}"
            )
            return True

        key = f"rate_limit:{identifier_type}:{identifier}:{endpoint}"
        current_ms = time() * 1000
        window_start_ms = current_ms - window_seconds * 1000

        # Генерируем уникальный идентификатор запроса
        current_request = f"{current_ms}-{random.randint(0, 10000)}"

        try:
            async with self._redis.pipeline() as pipe:
                # Удаляем старые записи вне временного окна
                await pipe.zremrangebyscore(key, 0, window_start_ms)
                # Получаем количество запросов в окне
                await pipe.zcard(key)
                # Добавляем текущий запрос
                await pipe.zadd(key, {current_request: current_ms})
                # Устанавливаем TTL для ключа
                await pipe.expire(key, window_seconds)

                res = await pipe.execute()

                # res содержит результаты каждой команды в порядке выполнения
                # zremrangebyscore, zcard, zadd, expire
                _, current_count, _, _ = res

                if current_count > max_requests:
                    logger.warning(
                        f"Rate limit exceeded: {identifier_type}:{identifier} "
                        f"to {endpoint} ({current_count}/{max_requests} in {window_seconds}s)"
                    )
                    return True

                logger.debug(
                    f"Rate limit check: {identifier_type}:{identifier} "
                    f"to {endpoint} ({current_count}/{max_requests} in {window_seconds}s)"
                )
                return False

        except RedisError as e:
            logger.error(f"Redis error during rate limiting: {e}")
            self._redis_available = False
            # При ошибке Redis блокируем все запросы
            return True


@lru_cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(get_redis())


def rate_limiter_factory(
    endpoint: str, max_requests: int, window_seconds: int, identifier_type: str = "ip"
):
    """
    Фабрика для создания зависимостей rate limiting.

    Args:
        endpoint: Имя эндпоинта
        max_requests: Максимальное количество запросов
        window_seconds: Окно времени в секундах
        identifier_type: Тип идентификатора ('ip' или 'user')

    Returns:
        FastAPI dependency
    """

    async def dependency(
        request: Request,
        rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ):
        if identifier_type == "ip":
            identifier = request.client.host
            if not identifier:
                identifier = "unknown"
        elif identifier_type == "user":
            # Для user-based rate limiting нужно получать user_id из токена
            # Пока что используем IP как fallback
            identifier = request.client.host or "unknown"
        else:
            identifier = request.client.host or "unknown"

        is_limited = await rate_limiter.is_limited(
            identifier, endpoint, max_requests, window_seconds, identifier_type
        )

        if is_limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too Many Requests, please wait and try again later.",
                headers={"Retry-After": str(window_seconds)},
            )

    return dependency
