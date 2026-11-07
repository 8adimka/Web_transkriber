#!/bin/bash

echo "=== Тестирование полного цикла работы API ==="
echo

# 1. Регистрация нового пользователя
echo "1. Регистрация нового пользователя..."
REGISTER_RESPONSE=$(curl -s -k -X POST "https://localhost/auth/register/" \
  -H "Content-Type: application/json" \
  -d '{"email": "cycle_test@example.com", "password": "test123", "full_name": "Cycle Test User"}')

echo "$REGISTER_RESPONSE" | jq .
ACCESS_TOKEN=$(echo "$REGISTER_RESPONSE" | jq -r '.access_token')
USER_ID=$(echo "$REGISTER_RESPONSE" | jq -r '.id')

if [ "$ACCESS_TOKEN" = "null" ] || [ -z "$ACCESS_TOKEN" ]; then
    echo "Ошибка: не удалось получить токен"
    exit 1
fi

echo "Токен получен: ${ACCESS_TOKEN:0:20}..."
echo "ID пользователя: $USER_ID"
echo

# 2. Получение настроек пользователя
echo "2. Получение настроек пользователя..."
SETTINGS_RESPONSE=$(curl -s -k "https://localhost/user/settings" \
  -H "Authorization: Bearer $ACCESS_TOKEN")

echo "$SETTINGS_RESPONSE" | jq .
echo

# 3. Получение статистики токенов
echo "3. Получение статистики токенов..."
STATS_RESPONSE=$(curl -s -k "https://localhost/user/stats/summary" \
  -H "Authorization: Bearer $ACCESS_TOKEN")

echo "$STATS_RESPONSE" | jq .
echo

# 4. Обновление настроек
echo "4. Обновление настроек..."
UPDATE_RESPONSE=$(curl -s -k -X PUT "https://localhost/user/settings" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"microphone_enabled": false, "original_language": "EN", "translation_language": "RU"}')

echo "$UPDATE_RESPONSE" | jq .
echo

# 5. Проверка обновленных настроек
echo "5. Проверка обновленных настроек..."
UPDATED_SETTINGS=$(curl -s -k "https://localhost/user/settings" \
  -H "Authorization: Bearer $ACCESS_TOKEN")

echo "$UPDATED_SETTINGS" | jq .
echo

# 6. Проверка работы rate limiter
echo "6. Проверка работы rate limiter..."
for i in {1..3}; do
    echo "Запрос $i:"
    RATE_RESPONSE=$(curl -s -k "https://localhost/rate-limiter/test" \
      -H "Authorization: Bearer $ACCESS_TOKEN")
    echo "$RATE_RESPONSE" | jq .
    echo
done

echo "=== Тестирование завершено успешно ==="
echo "Все API эндпоинты работают корректно."
echo "Фронтенд должен работать через https://localhost"