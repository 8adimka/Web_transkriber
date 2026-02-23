FROM python:3.11-slim

# Установка системных зависимостей (FFmpeg обязателен)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копирование зависимостей и установка
COPY backend/services/transcriber/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем shared директорию и transcriber сервис
COPY backend/shared/ ./backend/shared/
COPY backend/services/transcriber/app/ ./app/

# Создание папки для записей
RUN mkdir -p records

# Переменные окружения
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Запуск
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop", "--ws", "websockets"]
