FROM python:3.12-slim AS base

WORKDIR /app

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

COPY pyproject.toml .
RUN pip install uv && uv pip install --system -e .

FROM base AS production

COPY src/ ./src/
# alembic.ini points at src/data/migrations; without it the CLI cannot find the
# migration scripts, so the image could not migrate itself.
COPY alembic.ini ./
COPY entrypoint.sh ./

RUN chmod +x ./entrypoint.sh && mkdir -p /app/uploads && chown -R appuser:appgroup /app
USER appuser

ENV APP_ENV=production
ENV PORT=8080
EXPOSE 8080
# Migrates to head, then serves. See entrypoint.sh for why this runs here.
CMD ["./entrypoint.sh"]
