FROM nginx:alpine

# Установка SSL сертификатов
RUN mkdir -p /etc/nginx/ssl
COPY certs/localhost+2.pem /etc/nginx/ssl/
COPY certs/localhost+2-key.pem /etc/nginx/ssl/

# Копирование конфигурации
COPY nginx.conf /etc/nginx/nginx.conf

# Создание директории для логов
RUN mkdir -p /var/log/nginx

EXPOSE 80 443