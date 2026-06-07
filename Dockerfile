FROM python:3.12-slim AS base

WORKDIR /app

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

COPY pyproject.toml .
RUN pip install uv && uv pip install --system -e .

FROM base AS production

COPY src/ ./src/

RUN chown -R appuser:appgroup /app
USER appuser

ENV PORT=8080
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
