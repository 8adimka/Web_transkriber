# Web Transcriber

Веб-приложение для записи и транскрибации встреч в реальном времени. Объединяет звук микрофона и системный звук (вкладки), обрабатывает его через FFmpeg и отправляет в Deepgram.

## Структура

- **Frontend:** Vanilla JS + MediaRecorder API. Смешивает потоки через AudioContext.
- **Backend:** FastAPI (Async). Принимает WebM/Opus стрим, декодирует FFmpeg'ом в PCM "на лету" (pipes) и стримит в Deepgram.

## Предварительные требования

1. Docker и Docker Compose.
2. API ключ от [Deepgram](https://deepgram.com/).

## Быстрый старт (Docker)

1. **Настройка окружения:**

   ```bash
   cd backend
   cp .env.example .env
   # Отредактируйте .env и вставьте ваш DEEPGRAM_API_KEY
   cd ..

2. Запуск:

   ```bash
   docker-compose up --build
3. Использование:

Откройте браузер по адресу <http://localhost:80> (или просто откройте frontend/index.html в браузере, если не используете контейнер nginx).

Нажмите "Начать транскрибацию".

Разрешите доступ к микрофону.

Во всплывающем окне выберите вкладку или окно для захвата системного звука (ОБЯЗАТЕЛЬНО поставьте галочку "Share system audio" / "Также поделиться аудио вкладки").

Говорите. Текст будет появляться на экране.

Нажмите "Остановить" для получения ссылки на скачивание полного лога.

### Локальный запуск (без Docker)

#### Backend

1. Установите FFmpeg в систему (apt install ffmpeg или brew install ffmpeg).

2. Python 3.10+:

   ```bash

   cd backend
   python -m venv venv
   source venv/bin/activate  # или venv\Scripts\activate на Windows
   pip install -r requirements.txt
3. Запуск сервера:

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

#### Frontend

Просто откройте frontend/index.html в браузере. Убедитесь, что в app.js адрес WebSocket соответствует локальному серверу (ws://localhost:8000/ws/stream).

## Тонкая настройка и отладка

Конфигурация (.env)
DEEPGRAM_CHUNK_SIZE: Размер буфера отправки в Deepgram. 3200 байт ~ 100мс аудио.

QUEUE_MAX_SIZE: Размер очереди asyncio. Если сеть медленная, очередь заполнится и сервер пошлет сигнал throttle.

## Профилирование

FFmpeg запускается как подпроцесс. Чтобы проверить нагрузку:
docker stats - посмотрите CPU контейнера backend.
Если нагрузка высокая, FFmpeg может не успевать декодировать Opus. Убедитесь, что клиент шлет данные с разумным интервалом (по умолчанию 450ms).

## Логи

Логи пишутся в stdout контейнера.

   ```bash
   docker logs -f transcriber_backend
