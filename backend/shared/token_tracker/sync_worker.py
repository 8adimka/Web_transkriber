import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.shared.redis.base import get_redis

logger = logging.getLogger(__name__)


class TokenSyncWorker:
    """
    Фоновый воркер для синхронизации данных из Redis в PostgreSQL.
    Выполняет периодическую синхронизацию каждые 120 минут.
    """

    def __init__(self, redis: Redis, sync_interval_minutes: int = 120):
        self._redis = redis
        self._sync_interval = sync_interval_minutes * 60  # в секундах
        self._is_running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Запускает фоновую задачу синхронизации."""
        if self._is_running:
            logger.warning("TokenSyncWorker уже запущен")
            return

        self._is_running = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info(f"TokenSyncWorker запущен, интервал: {self._sync_interval} секунд")

    async def stop(self):
        """Останавливает фоновую задачу."""
        if not self._is_running:
            return

        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TokenSyncWorker остановлен")

    async def _sync_loop(self):
        """Основной цикл синхронизации."""
        while self._is_running:
            try:
                await self._perform_sync()
                await asyncio.sleep(self._sync_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле синхронизации: {e}")
                await asyncio.sleep(60)  # Подождать минуту перед повторной попыткой

    async def _perform_sync(self):
        """Выполняет одну итерацию синхронизации."""
        logger.info("Начало синхронизации Redis → PostgreSQL")
        start_time = time.time()

        try:
            # 1. Синхронизация токенов использования
            tokens_synced = await self._sync_token_usage()

            # 2. Синхронизация сырых событий
            events_synced = await self._sync_token_events()

            elapsed = time.time() - start_time
            logger.info(
                f"Синхронизация завершена за {elapsed:.2f} секунд. "
                f"Токены: {tokens_synced}, события: {events_synced}"
            )

        except Exception as e:
            logger.error(f"Ошибка при синхронизации: {e}")

    async def _sync_token_usage(self) -> int:
        """
        Синхронизирует данные использования токенов из Redis в PostgreSQL.

        Returns:
            Количество синхронизированных записей
        """
        try:
            # Ищем все ключи токенов
            pattern = "tokens:user:*:*"
            keys = await self._redis.keys(pattern)

            if not keys:
                logger.debug("Нет ключей токенов для синхронизации")
                return 0

            synced_count = 0
            # Динамический импорт SessionLocal
            try:
                from backend.services.auth.app.database import (
                    SessionLocal as AuthSessionLocal,
                )
            except ImportError:
                # Для случая, когда модуль запускается внутри auth сервиса
                from ...services.auth.app.database import (
                    SessionLocal as AuthSessionLocal,
                )

            async with AuthSessionLocal() as db:
                for key in keys:
                    if isinstance(key, bytes):
                        key = key.decode("utf-8")

                    # Парсим ключ: tokens:user:{user_id}:{period}
                    parts = key.split(":")
                    if len(parts) != 4:
                        continue

                    user_id_str = parts[2]
                    period = parts[3]

                    try:
                        user_id = int(user_id_str)
                    except ValueError:
                        logger.warning(f"Некорректный user_id в ключе {key}")
                        continue

                    # Получаем данные из Redis
                    data = await self._redis.hgetall(key)
                    if not data:
                        continue

                    # Преобразуем данные
                    deepgram_seconds = float(data.get(b"deepgram_seconds", b"0"))
                    deepl_characters = int(data.get(b"deepl_characters", b"0"))
                    total_requests = int(data.get(b"total_requests", b"0"))
                    last_updated = float(data.get(b"last_updated", b"0"))

                    # Выполняем upsert в PostgreSQL
                    await self._upsert_token_usage(
                        db=db,
                        user_id=user_id,
                        period=period,
                        deepgram_seconds=deepgram_seconds,
                        deepl_characters=deepl_characters,
                        total_requests=total_requests,
                        last_updated=last_updated,
                    )

                    synced_count += 1

                    # Логируем каждые 10 записей
                    if synced_count % 10 == 0:
                        logger.debug(f"Синхронизировано {synced_count} записей токенов")

            logger.info(
                f"Синхронизировано {synced_count} записей использования токенов"
            )
            return synced_count

        except Exception as e:
            logger.error(f"Ошибка при синхронизации токенов: {e}")
            return 0

    async def _upsert_token_usage(
        self,
        db: AsyncSession,
        user_id: int,
        period: str,
        deepgram_seconds: float,
        deepl_characters: int,
        total_requests: int,
        last_updated: float,
    ):
        """Выполняет upsert записи использования токенов."""
        try:
            # Проверяем существование таблицы
            # Если таблицы нет, пропускаем (миграции ещё не применены)
            try:
                # Используем raw SQL для upsert
                query = text("""
                    INSERT INTO token_usage 
                    (user_id, period, deepgram_seconds, deepl_characters, total_requests, last_updated, synced_at)
                    VALUES (:user_id, :period, :deepgram_seconds, :deepl_characters, :total_requests, :last_updated, :synced_at)
                    ON CONFLICT (user_id, period) 
                    DO UPDATE SET
                        deepgram_seconds = EXCLUDED.deepgram_seconds,
                        deepl_characters = EXCLUDED.deepl_characters,
                        total_requests = EXCLUDED.total_requests,
                        last_updated = EXCLUDED.last_updated,
                        synced_at = EXCLUDED.synced_at
                """)

                await db.execute(
                    query,
                    {
                        "user_id": user_id,
                        "period": period,
                        "deepgram_seconds": deepgram_seconds,
                        "deepl_characters": deepl_characters,
                        "total_requests": total_requests,
                        "last_updated": datetime.fromtimestamp(
                            last_updated, tz=timezone.utc
                        ),
                        "synced_at": datetime.now(timezone.utc),
                    },
                )
                await db.commit()

            except Exception as e:
                logger.warning(f"Таблица token_usage не существует или ошибка: {e}")
                await db.rollback()

        except Exception as e:
            logger.error(f"Ошибка при upsert токенов: {e}")
            await db.rollback()

    async def _sync_token_events(self) -> int:
        """
        Синхронизирует сырые события из Redis в PostgreSQL.

        Returns:
            Количество синхронизированных событий
        """
        try:
            # Ищем все ключи событий
            pattern = "token_events:user:*"
            keys = await self._redis.keys(pattern)

            if not keys:
                logger.debug("Нет ключей событий для синхронизации")
                return 0

            synced_count = 0
            # Динамический импорт SessionLocal
            try:
                from backend.services.auth.app.database import (
                    SessionLocal as AuthSessionLocal,
                )
            except ImportError:
                from ...services.auth.app.database import (
                    SessionLocal as AuthSessionLocal,
                )

            async with AuthSessionLocal() as db:
                for key in keys:
                    if isinstance(key, bytes):
                        key = key.decode("utf-8")

                    # Парсим ключ: token_events:user:{user_id}
                    parts = key.split(":")
                    if len(parts) != 3:
                        continue

                    user_id_str = parts[2]

                    try:
                        user_id = int(user_id_str)
                    except ValueError:
                        logger.warning(f"Некорректный user_id в ключе событий {key}")
                        continue

                    # Получаем все события из списка Redis
                    events_data = await self._redis.lrange(key, 0, -1)
                    if not events_data:
                        continue

                    # Обрабатываем каждое событие
                    for event_str in events_data:
                        try:
                            if isinstance(event_str, bytes):
                                event_str = event_str.decode("utf-8")

                            event_data = json.loads(event_str)

                            await self._insert_token_event(
                                db=db, user_id=user_id, event_data=event_data
                            )

                            synced_count += 1

                        except json.JSONDecodeError:
                            logger.warning(f"Некорректный JSON в событии: {event_str}")
                            continue
                        except Exception as e:
                            logger.error(f"Ошибка при обработке события: {e}")
                            continue

                    # Удаляем обработанные события из Redis
                    await self._redis.delete(key)

            logger.info(f"Синхронизировано {synced_count} событий")
            return synced_count

        except Exception as e:
            logger.error(f"Ошибка при синхронизации событий: {e}")
            return 0

    async def _insert_token_event(
        self, db: AsyncSession, user_id: int, event_data: Dict
    ):
        """Вставляет событие в таблицу token_events."""
        try:
            # Проверяем существование таблицы
            try:
                query = text("""
                    INSERT INTO token_events 
                    (event_id, user_id, service_type, amount, event_metadata, created_at)
                    VALUES (
                        gen_random_uuid(),
                        :user_id,
                        :service_type,
                        :amount,
                        :event_metadata,
                        :created_at
                    )
                """)

                await db.execute(
                    query,
                    {
                        "user_id": user_id,
                        "service_type": event_data.get("service_type", "unknown"),
                        "amount": float(event_data.get("amount", 0)),
                        "event_metadata": json.dumps(event_data.get("metadata", {})),
                        "created_at": datetime.fromtimestamp(
                            float(event_data.get("timestamp", time.time())),
                            tz=timezone.utc,
                        ),
                    },
                )
                await db.commit()

            except Exception as e:
                logger.warning(f"Таблица token_events не существует или ошибка: {e}")
                await db.rollback()

        except Exception as e:
            logger.error(f"Ошибка при вставке события: {e}")
            await db.rollback()

    async def force_sync(self):
        """Принудительно запускает синхронизацию немедленно."""
        logger.info("Принудительная синхронизация запущена")
        await self._perform_sync()


# Глобальный экземпляр воркера
_token_sync_worker: Optional[TokenSyncWorker] = None


def get_token_sync_worker() -> TokenSyncWorker:
    """Возвращает глобальный экземпляр TokenSyncWorker."""
    global _token_sync_worker
    if _token_sync_worker is None:
        _token_sync_worker = TokenSyncWorker(get_redis())
    return _token_sync_worker


async def start_token_sync_worker():
    """Запускает глобальный воркер синхронизации."""
    worker = get_token_sync_worker()
    await worker.start()


async def stop_token_sync_worker():
    """Останавливает глобальный воркер синхронизации."""
    global _token_sync_worker
    if _token_sync_worker:
        await _token_sync_worker.stop()
        _token_sync_worker = None


if __name__ == "__main__":
    """Точка входа для запуска воркера как скрипта."""
    import sys

    async def main():
        worker = get_token_sync_worker()
        await worker.start()
        try:
            # Бесконечный цикл
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nОстановка воркера...")
            await worker.stop()
            sys.exit(0)

    asyncio.run(main())
