import logging
import time
from typing import Dict, Optional, Tuple

from redis.asyncio import Redis
from redis.exceptions import RedisError

from backend.shared.redis.base import get_redis

logger = logging.getLogger(__name__)


class WebSocketRateLimiter:
    """
    Rate limiter для WebSocket соединений и сообщений.

    Отслеживает:
    1. Количество активных подключений с одного IP
    2. Количество активных подключений на одного пользователя
    3. Частоту сообщений с IP/пользователя
    """

    def __init__(
        self,
        redis: Redis,
        max_connections_per_ip: int = 3,  # Лимит подключений с одного IP адреса
        max_connections_per_user: int = 1,  # Лимит подключений на одного пользователя (по user_id)
        messages_per_minute: int = 1000,  # Лимит сообщений в минуту
        connection_ttl: int = 3600,  # 1 час TTL для записей о подключениях
    ):
        self._redis = redis
        self.max_connections_per_ip = max_connections_per_ip
        self.max_connections_per_user = max_connections_per_user
        self.messages_per_minute = messages_per_minute
        self.connection_ttl = connection_ttl
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
            logger.error(
                "Redis is unavailable. All WebSocket connections will be blocked."
            )
            return False

    async def check_connection(
        self, ip: str, user_id: Optional[int] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Проверяет, можно ли установить новое WebSocket подключение.

        Args:
            ip: IP адрес клиента
            user_id: ID пользователя (если аутентифицирован)

        Returns:
            Tuple[разрешено_ли_подключение, сообщение_об_ошибке]
        """
        # Если Redis недоступен - блокируем все подключения
        if not await self._check_redis_available():
            logger.warning(
                f"Redis unavailable, blocking WebSocket connection from IP: {ip}"
            )
            return False, "Service temporarily unavailable"

        try:
            # Проверка лимита подключений по IP
            ip_connections_key = f"ws:connections:ip:{ip}"
            current_ip_connections = await self._redis.get(ip_connections_key)
            current_ip_connections = (
                int(current_ip_connections) if current_ip_connections else 0
            )

            if current_ip_connections >= self.max_connections_per_ip:
                logger.warning(
                    f"WebSocket connection limit exceeded for IP {ip}: "
                    f"{current_ip_connections}/{self.max_connections_per_ip}"
                )
                return (
                    False,
                    f"Too many connections from your IP (max {self.max_connections_per_ip})",
                )

            # Проверка лимита подключений по пользователю (если user_id предоставлен)
            if user_id:
                user_connections_key = f"ws:connections:user:{user_id}"
                current_user_connections = await self._redis.get(user_connections_key)
                current_user_connections = (
                    int(current_user_connections) if current_user_connections else 0
                )

                if current_user_connections >= self.max_connections_per_user:
                    logger.warning(
                        f"WebSocket connection limit exceeded for user {user_id}: "
                        f"{current_user_connections}/{self.max_connections_per_user}"
                    )
                    return (
                        False,
                        f"Too many connections for your account (max {self.max_connections_per_user})",
                    )

            # Все проверки пройдены
            logger.debug(
                f"WebSocket connection allowed: IP={ip}, "
                f"user_id={user_id}, "
                f"ip_connections={current_ip_connections}, "
                f"user_connections={current_user_connections if user_id else 'N/A'}"
            )
            return True, None

        except RedisError as e:
            logger.error(f"Redis error during WebSocket connection check: {e}")
            self._redis_available = False
            return False, "Service temporarily unavailable"

    async def register_connection(
        self,
        ip: str,
        user_id: Optional[int] = None,
        connection_id: Optional[str] = None,
    ) -> bool:
        """
        Регистрирует новое WebSocket подключение.

        Args:
            ip: IP адрес клиента
            user_id: ID пользователя (если аутентифицирован)
            connection_id: Уникальный идентификатор соединения (опционально)

        Returns:
            True если регистрация успешна, False если нет
        """
        if not await self._check_redis_available():
            return False

        try:
            # Увеличиваем счетчик подключений по IP
            ip_connections_key = f"ws:connections:ip:{ip}"
            await self._redis.incr(ip_connections_key)
            await self._redis.expire(ip_connections_key, self.connection_ttl)

            # Увеличиваем счетчик подключений по пользователю (если user_id предоставлен)
            if user_id:
                user_connections_key = f"ws:connections:user:{user_id}"
                await self._redis.incr(user_connections_key)
                await self._redis.expire(user_connections_key, self.connection_ttl)

            # Регистрируем конкретное соединение (если connection_id предоставлен)
            if connection_id:
                connection_key = f"ws:connection:{connection_id}"
                connection_data = {
                    "ip": ip,
                    "user_id": str(user_id) if user_id else "",
                    "created_at": str(time.time()),
                }
                # Сохраняем на 1 час
                await self._redis.hset(connection_key, mapping=connection_data)
                await self._redis.expire(connection_key, self.connection_ttl)

            logger.debug(
                f"WebSocket connection registered: IP={ip}, user_id={user_id}, "
                f"connection_id={connection_id}"
            )
            return True

        except RedisError as e:
            logger.error(f"Redis error during WebSocket connection registration: {e}")
            self._redis_available = False
            return False

    async def unregister_connection(
        self,
        ip: str,
        user_id: Optional[int] = None,
        connection_id: Optional[str] = None,
    ) -> bool:
        """
        Удаляет регистрацию WebSocket подключения.

        Args:
            ip: IP адрес клиента
            user_id: ID пользователя (если аутентифицирован)
            connection_id: Уникальный идентификатор соединения (опционально)

        Returns:
            True если удаление успешно, False если нет
        """
        if not await self._check_redis_available():
            return False

        try:
            # Уменьшаем счетчик подключений по IP
            ip_connections_key = f"ws:connections:ip:{ip}"
            current = await self._redis.decr(ip_connections_key)
            if current <= 0:
                await self._redis.delete(ip_connections_key)

            # Уменьшаем счетчик подключений по пользователю (если user_id предоставлен)
            if user_id:
                user_connections_key = f"ws:connections:user:{user_id}"
                current = await self._redis.decr(user_connections_key)
                if current <= 0:
                    await self._redis.delete(user_connections_key)

            # Удаляем запись о конкретном соединении (если connection_id предоставлен)
            if connection_id:
                connection_key = f"ws:connection:{connection_id}"
                await self._redis.delete(connection_key)

            logger.debug(
                f"WebSocket connection unregistered: IP={ip}, user_id={user_id}, "
                f"connection_id={connection_id}"
            )
            return True

        except RedisError as e:
            logger.error(f"Redis error during WebSocket connection unregistration: {e}")
            self._redis_available = False
            return False

    async def check_message(
        self, ip: str, user_id: Optional[int] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Проверяет, можно ли отправить новое сообщение через WebSocket.

        Args:
            ip: IP адрес клиента
            user_id: ID пользователя (если аутентифицирован)

        Returns:
            Tuple[разрешено_ли_сообщение, сообщение_об_ошибке]
        """
        # Если Redis недоступен - блокируем все сообщения
        if not await self._check_redis_available():
            logger.warning(
                f"Redis unavailable, blocking WebSocket message from IP: {ip}"
            )
            return False, "Service temporarily unavailable"

        try:
            current_time = time.time()
            minute_window = int(current_time // 60)  # Целое количество минут с эпохи

            # Проверка лимита сообщений по IP
            ip_messages_key = f"ws:messages:ip:{ip}:{minute_window}"
            current_ip_messages = await self._redis.incr(ip_messages_key)

            # Устанавливаем TTL на 2 минуты (чтобы ключ жил дольше окна)
            await self._redis.expire(ip_messages_key, 120)

            if current_ip_messages > self.messages_per_minute:
                logger.warning(
                    f"WebSocket message limit exceeded for IP {ip}: "
                    f"{current_ip_messages}/{self.messages_per_minute} messages per minute"
                )
                return (
                    False,
                    f"Too many messages from your IP (max {self.messages_per_minute} per minute)",
                )

            # Проверка лимита сообщений по пользователю (если user_id предоставлен)
            if user_id:
                user_messages_key = f"ws:messages:user:{user_id}:{minute_window}"
                current_user_messages = await self._redis.incr(user_messages_key)
                await self._redis.expire(user_messages_key, 120)

                if current_user_messages > self.messages_per_minute:
                    logger.warning(
                        f"WebSocket message limit exceeded for user {user_id}: "
                        f"{current_user_messages}/{self.messages_per_minute} messages per minute"
                    )
                    return (
                        False,
                        f"Too many messages from your account (max {self.messages_per_minute} per minute)",
                    )

            # Все проверки пройдены
            logger.debug(
                f"WebSocket message allowed: IP={ip}, user_id={user_id}, "
                f"ip_messages={current_ip_messages}, "
                f"user_messages={current_user_messages if user_id else 'N/A'}"
            )
            return True, None

        except RedisError as e:
            logger.error(f"Redis error during WebSocket message check: {e}")
            self._redis_available = False
            return False, "Service temporarily unavailable"

    async def get_connection_stats(
        self, ip: Optional[str] = None, user_id: Optional[int] = None
    ) -> Dict:
        """
        Возвращает статистику подключений.

        Args:
            ip: IP адрес для фильтрации (опционально)
            user_id: ID пользователя для фильтрации (опционально)

        Returns:
            Словарь со статистикой
        """
        stats = {}

        if not await self._check_redis_available():
            return {"redis_available": False}

        try:
            if ip:
                ip_key = f"ws:connections:ip:{ip}"
                ip_count = await self._redis.get(ip_key)
                stats["ip_connections"] = int(ip_count) if ip_count else 0
                stats["ip_max_connections"] = self.max_connections_per_ip

            if user_id:
                user_key = f"ws:connections:user:{user_id}"
                user_count = await self._redis.get(user_key)
                stats["user_connections"] = int(user_count) if user_count else 0
                stats["user_max_connections"] = self.max_connections_per_user

            stats["redis_available"] = True
            return stats

        except RedisError as e:
            logger.error(f"Redis error during stats retrieval: {e}")
            return {"redis_available": False, "error": str(e)}


# Синглтон для использования в приложении
_websocket_rate_limiter: Optional[WebSocketRateLimiter] = None


def get_websocket_rate_limiter() -> WebSocketRateLimiter:
    """Возвращает экземпляр WebSocket rate limiter."""
    global _websocket_rate_limiter
    if _websocket_rate_limiter is None:
        _websocket_rate_limiter = WebSocketRateLimiter(get_redis())
    return _websocket_rate_limiter
