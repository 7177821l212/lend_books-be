.PHONY: dev db migrate seed test lint format typecheck

dev:
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

db:
	docker-compose up db -d

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(msg)"

seed:
	python -m src.data.seed

test:
	pytest

lint:
	ruff check src tests

format:
	ruff format src tests

typecheck:
	mypy src

check: lint typecheck test
