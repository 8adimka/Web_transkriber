import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.shared.rate_limiter.base import get_rate_limiter
from backend.shared.rate_limiter.websocket import get_websocket_rate_limiter
from backend.shared.redis.base import check_redis_health

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rate-limiter", tags=["rate-limiter"])


@router.get("/health")
async def rate_limiter_health():
    """
    Проверяет состояние rate limiter и Redis.
    """
    redis_healthy = await check_redis_health()

    return {
        "redis_available": redis_healthy,
        "status": "healthy" if redis_healthy else "degraded",
        "message": "Rate limiter is operational"
        if redis_healthy
        else "Redis is unavailable, rate limiting is in degraded mode",
    }


@router.get("/stats")
async def rate_limiter_stats(
    rate_limiter=Depends(get_rate_limiter),
    ws_rate_limiter=Depends(get_websocket_rate_limiter),
):
    """
    Возвращает статистику rate limiter.
    """
    try:
        # Получаем базовую информацию о Redis
        redis_healthy = await check_redis_health()

        # Для WebSocket rate limiter можно получить статистику подключений
        # (в реальном приложении здесь можно добавить больше метрик)

        return {
            "redis_available": redis_healthy,
            "rate_limiter": {
                "type": "sliding_window",
                "redis_based": True,
                "degraded_mode": not redis_healthy,
            },
            "websocket_rate_limiter": {
                "max_connections_per_ip": ws_rate_limiter.max_connections_per_ip,
                "max_connections_per_user": ws_rate_limiter.max_connections_per_user,
                "messages_per_minute": ws_rate_limiter.messages_per_minute,
                "connection_ttl": ws_rate_limiter.connection_ttl,
            },
            "auth_endpoints": {
                "register": "3 requests per 10 seconds per IP",
                "login": "5 requests per minute per IP",
                "google_login": "10 requests per minute per IP",
                "refresh": "10 requests per minute per IP",
            },
        }
    except Exception as e:
        logger.error(f"Error getting rate limiter stats: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get rate limiter statistics"
        )


@router.get("/test/{endpoint}")
async def test_rate_limit(endpoint: str, rate_limiter=Depends(get_rate_limiter)):
    """
    Тестовый эндпоинт для проверки rate limiting.
    Не использовать в продакшене!
    """
    # Генерируем тестовый IP
    test_ip = "127.0.0.1"

    # Проверяем лимит
    is_limited = await rate_limiter.is_limited(
        identifier=test_ip,
        endpoint=f"test_{endpoint}",
        max_requests=3,
        window_seconds=10,
        identifier_type="ip",
    )

    return {
        "endpoint": endpoint,
        "test_ip": test_ip,
        "is_limited": is_limited,
        "message": "Request would be blocked"
        if is_limited
        else "Request would be allowed",
    }
