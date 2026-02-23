FROM python:3.12-slim

WORKDIR /app

# Установка tzdata для корректного времени и установка временной зоны
RUN apt-get update && apt-get install -y tzdata && \
    ln -fs /usr/share/zoneinfo/Europe/Moscow /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

COPY backend/services/auth/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создаем директорию для ключей (ключи будут смонтированы через volumes)
RUN mkdir -p /app/keys

# Копируем shared директорию и auth сервис
COPY backend/shared/ ./backend/shared/
COPY backend/services/auth/app/ ./app/
COPY backend/services/auth/app/alembic/ ./alembic/
COPY backend/services/auth/entrypoint.sh .

RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
