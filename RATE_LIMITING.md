# Rate Limiting System

## Обзор

Система rate limiting реализована для защиты приложения от злоупотреблений и DDoS атак. Используется Redis для хранения состояния и обеспечения распределенной работы.

## Архитектура

### Компоненты

1. **Redis** - хранилище для счетчиков запросов
2. **Base Rate Limiter** (`backend/shared/rate_limiter/base.py`) - базовый rate limiter для HTTP запросов
3. **WebSocket Rate Limiter** (`backend/shared/rate_limiter/websocket.py`) - специализированный rate limiter для WebSocket соединений
4. **Metrics API** (`backend/shared/rate_limiter/metrics.py`) - эндпоинты для мониторинга

## Конфигурация

### Redis

- Хост: `redis_container` (в Docker), `localhost` (локально)
- Порт: `6379`
- Переменные окружения: `REDIS_HOST`, `REDIS_PORT`

### Лимиты

#### HTTP Endpoints (Auth Service)

- **Регистрация**: 3 запроса за 10 секунд с одного IP
- **Логин**: 5 запросов за минуту с одного IP  
- **Google OAuth**: 10 запросов за минуту с одного IP
- **Refresh токен**: 10 запросов за минуту с одного IP

#### WebSocket (Transcriber Service)

- **Подключения по IP**: максимум 3 одновременных соединения
- **Подключения по пользователю**: максимум 1 одновременное соединение
- **Сообщения**: максимум 60 сообщений в минуту с IP/пользователя

## Режим деградации

Если Redis недоступен:

- Все HTTP запросы блокируются (безопасный режим)
- Все WebSocket подключения блокируются
- В логи записываются предупреждения

## Мониторинг

### Эндпоинты

#### Auth Service

- `GET /rate-limiter/health` - проверка состояния Redis
- `GET /rate-limiter/stats` - статистика rate limiter
- `GET /rate-limiter/test/{endpoint}` - тестовый эндпоинт

#### Transcriber Service

- Те же эндпоинты доступны по тому же пути

### Логирование

- Каждое превышение лимита логируется с уровнем WARNING
- Ошибки Redis логируются с уровнем ERROR
- Успешные проверки логируются с уровнем DEBUG

## Интеграция

### HTTP Endpoints

Rate limiting добавляется как dependency в FastAPI:

```python
from backend.shared.rate_limiter.base import rate_limiter_factory

register_rate_limit = rate_limiter_factory(
    endpoint="auth_register",
    max_requests=3,
    window_seconds=10,
    identifier_type="ip"
)

@router.post("/register/", dependencies=[Depends(register_rate_limit)])
def register(...):
    ...
```

### WebSocket

Rate limiting интегрирован в `ws_routes.py`:

- Проверка перед принятием соединения
- Проверка каждого сообщения
- Автоматическая регистрация/удаление подключений

## Тестирование

1. Запустите все сервисы:

```bash
docker-compose up -d
```

1. Проверьте состояние rate limiter:

```bash
curl http://localhost:8000/rate-limiter/health
```

1. Протестируйте лимиты (например, для регистрации):

```bash
# Быстрые запросы для проверки лимита
for i in {1..5}; do
  curl -X POST http://localhost:8000/auth/register/ \
    -H "Content-Type: application/json" \
    -d '{"email":"test@example.com", "password":"test123"}'
  echo
  sleep 1
done
```

## Настройка

### Изменение лимитов

1. HTTP лимиты: `backend/services/auth/app/routers/auth.py`
2. WebSocket лимиты: `backend/shared/rate_limiter/websocket.py`

### Конфигурация Redis

1. Docker: `docker-compose.yml`
2. Локально: переменные окружения `REDIS_HOST`, `REDIS_PORT`

## Безопасность

- При недоступности Redis блокируются все запросы (безопасный режим)
- Логируются все попытки превышения лимитов
- Используется sliding window алгоритм для точного подсчета
- Поддержка распределенной среды через Redis
