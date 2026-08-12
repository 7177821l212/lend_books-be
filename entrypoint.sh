#!/bin/bash

echo "Running database migrations..."
alembic upgrade head || {
  echo "WARNING: Migration failed, but continuing startup..."
}

echo "Starting application..."
exec python -m uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8080}
