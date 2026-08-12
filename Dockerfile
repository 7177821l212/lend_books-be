FROM python:3.12-slim AS base

WORKDIR /app

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

COPY pyproject.toml .
RUN pip install uv && uv pip install --system -e .

FROM base AS production

COPY src/ ./src/
COPY src/data/migrations/ ./src/data/migrations/
COPY alembic.ini .
COPY entrypoint.sh .

RUN mkdir -p /app/uploads && chmod +x entrypoint.sh && chown -R appuser:appgroup /app
USER appuser

ENV PORT=8080
EXPOSE 8080
ENTRYPOINT ["./entrypoint.sh"]
