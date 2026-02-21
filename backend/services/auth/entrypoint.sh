#!/bin/bash
set -e

wait_for_db() {
    echo "Waiting for PostgreSQL to become available..."
    local host="$POSTGRES_AUTH_HOST"
    local port="$POSTGRES_AUTH_PORT"
    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if python -c "
import sys, psycopg2
try:
    conn = psycopg2.connect(
        host='$host',
        port=$port,
        dbname='$POSTGRES_AUTH_DB',
        user='$POSTGRES_AUTH_USER',
        password='$POSTGRES_AUTH_PASSWORD'
    )
    conn.close()
    sys.exit(0)
except Exception as e:
    sys.exit(1)
" 2>/dev/null; then
            echo "PostgreSQL is ready!"
            return 0
        fi
        echo "Attempt $attempt/$max_attempts: PostgreSQL not ready yet, waiting 2 seconds..."
        sleep 2
        attempt=$((attempt + 1))
    done

    echo "Error: PostgreSQL not available after $max_attempts attempts"
    return 1
}

# Wait for database
wait_for_db

echo "Applying database migrations..."
cd /app/alembic
max_retries=3
retry=1
while [ $retry -le $max_retries ]; do
    if alembic upgrade head; then
        echo "Migrations applied successfully."
        break
    else
        echo "Migration attempt $retry failed."
        if [ $retry -eq $max_retries ]; then
            echo "Migration failed after $max_retries attempts. Exiting."
            exit 1
        fi
        sleep 5
        retry=$((retry + 1))
    fi
done

echo "Starting FastAPI application..."
cd /app
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
