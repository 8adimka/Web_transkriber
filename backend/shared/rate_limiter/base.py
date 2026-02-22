import random
from time import time


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
