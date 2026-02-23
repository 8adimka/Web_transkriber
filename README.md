# Web Transcriber

Веб-приложение для записи и транскрибации рабочих встреч (Deepgram), а также осуществления потокового перевода в реальном времени на различные языки (DeepL).
Использует звук микрофона и системный звук (вкладки или доступные окна), обрабатывает его через FFmpeg.

## Особенности

- **Захват двух источников звука**: микрофон пользователя и системный звук (вкладка/окно)
- **Транскрибация и Перевод**: потоковая передача аудио в Deepgram с минимальной задержкой, перевод через DeepL
- **Аутентификация пользователей**: JWT-токены с поддержкой Google OAuth 2.0
- **Хранение транскрипций**: PostgreSQL база данных для сохранения всех транскрипций пользователей
- **Rate Limiting**: защита от злоупотреблений, реализовано через Redis
- **Интерфейс**: интуитивное управление с динамическим отображением кнопок
- **Скачивание файлов**: сохранение транскрипта в текстовый файл с датой создания

## Архитектура

- **Frontend**: Vanilla JS + MediaRecorder API. Потоки через AudioContext.
- **Backend (Transcriber)**: FastAPI (Async). Принимает WebM/Opus стрим, декодирует FFmpeg'ом в PCM "на лету" (pipes) и стримит в Deepgram.
- **Backend (Auth)**: FastAPI сервис аутентификации с JWT токенами и Google OAuth.
- **Nginx**: HTTPS прокси, обслуживание статики, WebSocket проксирование.
- **PostgreSQL**: Две независимые базы данных для аутентификации и хранения транскрипций.
- **Redis**: Хранилище для rate limiting и сессий.

## Предварительные требования

1. Docker и Docker Compose
2. API ключ от [Deepgram](https://deepgram.com/)
3. Google OAuth Client ID и Secret (для аутентификации через Google)
4. mkcert (для локальных SSL сертификатов) - установится автоматически

## Быстрый старт (Docker)

### 1. Настройка окружения

```bash
# Настройка сервиса транскрибера
cd backend/services/transcriber
cp .env.example .env
# Отредактируйте .env и вставьте ваш DEEPGRAM_API_KEY

# Настройка сервиса аутентификации
cd ../auth
cp .env.example .env
# Отредактируйте .env и добавьте GOOGLE_CLIENT_ID и GOOGLE_CLIENT_SECRET
cd ../../..
```

### 2. Генерация SSL сертификатов (для HTTPS)

```bash
# Установка mkcert (если не установлен)
sudo apt install libnss3-tools  # или эквивалент для вашей ОС
curl -s https://api.github.com/repos/FiloSottile/mkcert/releases/latest | grep browser_download_url | grep linux-amd64 | cut -d '"' -f 4 | wget -qi -
chmod +x mkcert-v*-linux-amd64
sudo mv mkcert-v*-linux-amd64 /usr/local/bin/mkcert

# Генерация сертификатов
mkcert -install
mkcert localhost
mkdir -p certs
mv localhost.pem certs/localhost+2.pem
mv localhost-key.pem certs/localhost+2-key.pem
```

### 3. Запуск приложения

- После всех предварительных настроек для запуска проекта достаточно применить:

```bash
docker-compose up --build -d
```

### 4. Использование

1. Откройте браузер по адресу **<https://localhost>** (примите предупреждение о самоподписанном сертификате)
2. Зарегистрируйтесь или войдите через Google OAuth
3. Выберите нужные настройки языка и источников аудио-потоков - микрофон и/или системный звук
4. Нажмите **"Начать запись"** - доступны два режима:

    - Транскрибация -> для записи диалога в текстовой форме;
    - Потоковый перевод -> осуществляет перевод аудио в реальном времени с выбранного языка с получением субтитров.

5. Разрешите доступ к микрофону
6. Во всплывающем окне выберите вкладку или окно для захвата системного звука (**ОБЯЗАТЕЛЬНО нажните "Share audio"**)
7. Текст будет появляться на экране в реальном времени
8. Нажмите **"Остановить"** для завершения записи
9. Скачайте полный транскрипт по появившейся ссылке (опционально)
10. Просмотрите все сохраненные транскрипции на странице "Посмотреть сохранённые диалоги"

## Сервисы

### 1. Сервис транскрибера (`transcriber`)

- Обработка аудио потоков через FFmpeg
- Стриминг в Deepgram API
- Хранение транскрипций в PostgreSQL
- API для управления транскрипциями (получение, скачивание, удаление)
- Rate limiting через Redis

### 2. Сервис аутентификации (`auth`)

- Регистрация и аутентификация пользователей
- JWT токены (access и refresh)
- Google OAuth интеграция
- Управление пользователями в PostgreSQL

### 3. Frontend (`nginx`)

- Обслуживание статических файлов
- HTTPS проксирование
- WebSocket проксирование к backend сервисам

## Конфигурация

### Переменные окружения (backend/services/transcriber/.env)

| Переменная | Описание | Значение по умолчанию |
|------------|----------|----------------------|
| `DEEPGRAM_API_KEY` | API ключ Deepgram | (обязательно) |
| `DEEPGRAM_CHUNK_SIZE` | Размер буфера отправки в Deepgram | 3200 |
| `QUEUE_MAX_SIZE` | Размер очереди asyncio | 40 |
| `CHUNK_DURATION_MS` | Длительность чанка в миллисекундах | 450 |
| `POSTGRES_TRANSCRIBER_HOST` | Хост PostgreSQL для транскрипций | postgres_transcriber |
| `POSTGRES_TRANSCRIBER_PORT` | Порт PostgreSQL | 5432 |
| `POSTGRES_TRANSCRIBER_DB` | Имя базы данных | transcriberdb |
| `POSTGRES_TRANSCRIBER_USER` | Пользователь PostgreSQL | postgres |
| `POSTGRES_TRANSCRIBER_PASSWORD` | Пароль PostgreSQL | (из docker-compose.yml) |
| `REDIS_HOST` | Хост Redis | redis_container |
| `REDIS_PORT` | Порт Redis | 6379 |

### Переменные окружения (backend/services/auth/.env)

| Переменная | Описание | Значение по умолчанию |
|------------|----------|----------------------|
| `GOOGLE_CLIENT_ID` | Google OAuth Client ID | (обязательно) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth Client Secret | (обязательно) |
| `SECRET_KEY` | Секретный ключ для JWT | (генерируется автоматически) |
| `ALGORITHM` | Алгоритм JWT | RS256 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Время жизни access токена | 30 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Время жизни refresh токена | 30 |
| `POSTGRES_AUTH_HOST` | Хост PostgreSQL для аутентификации | postgres_auth |
| `POSTGRES_AUTH_PORT` | Порт PostgreSQL | 5432 |
| `POSTGRES_AUTH_DB` | Имя базы данных | authdb |
| `POSTGRES_AUTH_USER` | Пользователь PostgreSQL | postgres |
| `POSTGRES_AUTH_PASSWORD` | Пароль PostgreSQL | (из docker-compose.yml) |
| `REDIS_HOST` | Хост Redis | redis_container |
| `REDIS_PORT` | Порт Redis | 6379 |

### Nginx конфигурация

- Порт 80: HTTP → HTTPS редирект
- Порт 443: HTTPS с самоподписанными сертификатами
- Проксирование `/ws/stream` → transcriber:8000
- Проксирование `/transcriptions/*` → transcriber:8000
- Проксирование `/auth/*` → auth:8000
- Обслуживание статики из `/usr/share/nginx/html`

## Rate Limiting

Система использует Redis для реализации rate limiting:

- **WebSocket соединения**: ограничение на количество одновременных сессий и дополнительные настройки:
  - max_connections_per_ip -> Лимит подключений с одного IP адреса
  - max_connections_per_user -> Лимит подключений на одного пользователя (по user_id)
  - messages_per_minute -> Лимит сообщений в минуту
- **API endpoints**: защита от злоупотреблений
- **Аутентификация**: ограничение попыток входа

## Хранение данных

### PostgreSQL для транскрипций

- Таблица `transcriptions` с полями: id, user_id, filename, content, orig_language, translate_to, file_size, created_at
- Индексы по user_id для быстрого поиска транскрипций пользователя
- Автоматическое формирование имени файла на основе даты создания

### PostgreSQL для аутентификации

- Таблица `users` с информацией о пользователях
- Таблица `refresh_tokens` для управления сессиями

## Отладка и мониторинг

### Просмотр логов

```bash
# Логи сервиса транскрибера
docker-compose logs -f transcriber

# Логи сервиса аутентификации
docker-compose logs -f auth

# Логи PostgreSQL для транскрипций
docker-compose logs -f postgres_transcriber

# Логи PostgreSQL для аутентификации
docker-compose logs -f postgres_auth

# Логи Redis
docker-compose logs -f redis_container

# Логи фронтенда (nginx)
docker-compose logs -f frontend
```

### Проверка состояния

```bash
docker-compose ps
```

### Остановка приложения

```bash
docker-compose down
```

## Устранение проблем

### 1. "Нет доступа к микрофону"

- Убедитесь, что используете HTTPS
- Проверьте разрешения браузера
- Перезагрузите страницу

### 2. "Нет звука с системного источника"

- При выборе окна/вкладки обязательно поставьте галочку "Share audio"
- Убедитесь, что в выбранном окне есть звук

### 3. "WebSocket соединение разрывается"

- Проверьте, что сервис транскрибера запущен (`docker-compose ps`)
- Проверьте логи транскрибера на наличие ошибок

### 4. "Нет транскрипции"

- Проверьте API ключ Deepgram в `.env` файле
- Убедитесь, что есть звук на входе (проверьте индикаторы громкости системы)

### 5. "Ошибки аутентификации"

- Проверьте настройки Google OAuth в `.env` файле сервиса аутентификации
- Убедитесь, что Redis и PostgreSQL для аутентификации запущены

### 6. "Ошибки базы данных"

- Проверьте, что контейнеры PostgreSQL запущены
- Убедитесь, что пароли в `.env` файлах соответствуют настройкам в docker-compose.yml

## Лицензия

MIT

## Автор

- Мединцев Вадим Сергеевич

Проект разработан для транскрибации рабочих встреч и потокового перевода в реальном времени.
