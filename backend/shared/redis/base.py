from functools import lru_cache

from redis.asyncio import Redis


@lru_cache
def get_redis() -> Redis:
    return Redis(host="localhost", port=6379)
