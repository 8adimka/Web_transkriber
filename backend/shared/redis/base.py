import os
from functools import lru_cache

from redis.asyncio import ConnectionError, Redis
from redis.exceptions import RedisError


@lru_cache
def get_redis() -> Redis:
    """Создает и возвращает подключение к Redis с кэшированием."""
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))

    return Redis(
        host=redis_host,
        port=redis_port,
        decode_responses=False,  # Для rate limiting храним байты
        socket_connect_timeout=5,  # Таймаут подключения
        socket_timeout=5,  # Таймаут операций
        retry_on_timeout=True,  # Повторять при таймауте
        max_connections=10,  # Максимальное количество соединений в пуле
    )


async def check_redis_health() -> bool:
    """Проверяет доступность Redis."""
    try:
        redis = get_redis()
        await redis.ping()
        return True
    except (ConnectionError, RedisError):
        return False
