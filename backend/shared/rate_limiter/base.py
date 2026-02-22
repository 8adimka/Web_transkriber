import random
from functools import lru_cache
from time import time
from typing import Annotated

from backend.shared.redis.base import get_redis


class RateLimiter:
    def __init__(self, redis: Redis):
        self._redis = redis

    async def is_limited(
        self, ip_address: str, endpoint: str, max_requests: int, window_seconds: int
    ) -> bool:
        key = f"rate_limit:{ip_address}:{endpoint}"
        current_ms = time() * 1000
        window_start_ms = current_ms - window_seconds * 1000

        current_request = f"{time() * 1000}-{random.randint(0, 10000)}"

        async with self._redis.pipeline() as pipe:
            await pipe.zremrangebyscore(key, 0, window_start_ms)
            await pipe.zcard(key)
            await pipe.zadd(key, {current_request: current_ms})
            await pipe.expire(key, window_seconds)

            res = await pipe.execute()

            _, current_count, _, _ = res

            return current_count > max_requests


@lru_cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(get_redis())


def rate_limiter_factory(
    endpoint: str, max_requests: int, window_seconds: int
) -> RateLimiter:
    def dependency(
        request: Request,
        rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ):
        ip_address = request.client.host

        is_limited = await rate_limiter.is_limited(
            ip_address, endpoint, max_requests, window_seconds
        )

        if is_limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too Many Requests, please wait and try again later.",
            )

    return dependency
