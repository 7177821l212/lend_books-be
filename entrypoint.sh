#!/bin/sh
# Container entrypoint: bring the schema up to date, then serve.
#
# Alembic is a CLI — it only migrates when something runs it. Nothing did, so
# every schema change had to be applied by hand against Cloud SQL before a
# deploy, and forgetting meant the new code queried columns that did not exist.
#
# Migrating here ties the schema to the image that needs it. If the upgrade
# fails we exit non-zero and never start the server: the revision fails its
# health check and Cloud Run keeps routing to the previous one, rather than
# serving traffic against a half-migrated database.
#
# Concurrent instances of the same revision are safe — env.py takes a Postgres
# advisory lock, so the first one migrates and the others wait and no-op.
set -eu

echo "[entrypoint] running database migrations..."
alembic upgrade head
echo "[entrypoint] migrations complete; current revision:"
alembic current

echo "[entrypoint] starting API on port ${PORT:-8080}"
exec python -m uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8080}"
