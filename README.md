# LendBook — Backend API (FastAPI)

> **Phase 1 Foundation** — REST API for the LendBook mobile lending management app.  
> Built with FastAPI, SQLAlchemy v2 (async), PostgreSQL, and deployed on GCP Cloud Run.

---

## Overview

LendBook backend serves two client roles over a single REST API:

| Role | Key Operations |
|---|---|
| **Investor** | Create loans, manage customers, view reports, manage collectors |
| **Collector** | View daily pickup list, record payments, view history |

All business logic enforces role-based access control — collectors only see loans assigned to them; investors see everything under their account.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.115+ |
| Language | Python 3.11+ |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 16 (Cloud SQL on GCP) |
| Migrations | Alembic |
| Auth | JWT (python-jose + passlib bcrypt) |
| Validation | Pydantic v2 |
| Package Manager | uv |
| Container | Docker + Cloud Run |
| Linting | Ruff |
| Type Checking | MyPy (strict) |
| Testing | pytest-asyncio |

---

## Project Structure

```
src/
├── api/
│   └── rest/
│       ├── app.py              # FastAPI factory — CORS, routers
│       ├── dependencies.py     # get_db, get_current_user, require_role
│       └── routes/
│           ├── health.py       # GET /health
│           ├── auth.py         # POST /auth/login, /refresh, GET /me
│           ├── customers.py    # CRUD + blacklist
│           ├── loans.py        # Create, detail, close
│           ├── payments.py     # Collect, missed, history
│           ├── collectors.py   # Team list, my-day
│           └── reports.py      # Overdue, summary
├── core/
│   ├── exceptions/base.py      # HTTP exception hierarchy
│   └── services/               # Business logic (one per domain)
├── data/
│   ├── clients/postgres_client.py   # Async SQLAlchemy engine
│   ├── repositories/                # Data access layer
│   │   └── base_repository.py       # Generic list/get/create/delete
│   ├── models/postgres/             # SQLAlchemy ORM models
│   │   ├── base.py                  # TimestampMixin, UUID generator
│   │   ├── user.py
│   │   ├── customer.py
│   │   ├── loan.py
│   │   ├── installment.py
│   │   └── payment.py
│   └── migrations/                  # Alembic versions
├── schemas/                         # Pydantic request/response models
│   ├── auth.py
│   ├── customer.py
│   ├── loan.py
│   ├── payment.py
│   └── common.py                    # PaginatedResponse, ErrorDetail
├── constants/
│   └── enums.py                     # UserRole, LoanStatus, PaymentMode...
├── utils/
│   └── security.py                  # JWT create/verify, bcrypt hash/verify
├── config/
│   └── settings.py                  # Pydantic settings from env
└── main.py                          # App entry point
```

---

## Data Model

```
User ──────────────────────────────────────────────
  id, email, hashed_password, name, phone
  role: investor | collector
  investor_id (collector belongs to investor)

Customer ──────────────────────────────────────────
  id, investor_id, name, phone, location
  risk_level: low | medium | high
  is_blacklisted, blacklist_reason

Loan ───────────────────────────────────────────────
  id, investor_id, customer_id, collector_id
  principal, interest_rate, lending_model
  repayment_frequency: daily | weekly | monthly
  total_installments, installment_amount
  start_date, status: active | overdue | closed

Installment ────────────────────────────────────────
  id, loan_id, sequence, due_date, amount
  status: pending | due_today | overdue | paid

Payment ────────────────────────────────────────────
  id, loan_id, collector_id
  amount, mode: CASH | UPI | BANK
  proof_photo_url, notes, collected_at
```

---

## API Endpoints

All endpoints prefixed with `/api/v1`. Requires `Authorization: Bearer <token>` except `/health` and `/auth/login`.

| Method | Endpoint | Role | Description |
|---|---|---|---|
| `GET` | `/health` | Public | Health check |
| `POST` | `/auth/login` | Public | Email + password login |
| `POST` | `/auth/refresh` | Public | Refresh access token |
| `GET` | `/auth/me` | Any | Current user profile |
| `GET` | `/customers` | Any | List customers (filtered by role) |
| `POST` | `/customers` | Investor | Create customer |
| `GET` | `/customers/:id` | Any | Customer detail |
| `PATCH` | `/customers/:id` | Investor | Update customer |
| `POST` | `/customers/:id/blacklist` | Investor | Blacklist customer |
| `GET` | `/loans` | Any | List loans |
| `POST` | `/loans` | Investor | Create loan + generate installments |
| `GET` | `/loans/:id` | Any | Loan detail + schedule |
| `POST` | `/loans/:id/close` | Investor | Close loan early |
| `POST` | `/payments/collect` | Collector | Record payment |
| `POST` | `/payments/missed` | Collector | Mark installment missed |
| `GET` | `/payments/history` | Any | Payment history |
| `GET` | `/collectors` | Investor | List team |
| `GET` | `/collectors/my-day` | Collector | Today's pickup list |
| `GET` | `/reports/overdue` | Investor | Overdue loans report |
| `GET` | `/reports/summary` | Investor | Portfolio analytics |

---

## Getting Started

### Prerequisites

- Python 3.11+
- Docker Desktop
- `uv` package manager: `curl -LsSf https://astral.sh/uv/install.sh | sh`

### Local Setup

```bash
# 1. Clone and enter directory
cd lendbook-be

# 2. Create virtual environment
uv venv
source .venv/bin/activate

# 3. Install dependencies
uv pip install -e ".[dev]"

# 4. Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL and JWT_SECRET_KEY

# 5. Start the database
make db

# 6. Run migrations
make migrate

# 7. Start the API (hot reload)
make dev
# API running at http://localhost:8000
# Docs at http://localhost:8000/docs
```

### Docker (full stack)

```bash
docker-compose up --build
# API: http://localhost:8000
# DB:  localhost:5432
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://user:pass@host:5432/dbname` |
| `JWT_SECRET_KEY` | ✅ | 32-byte hex secret (`openssl rand -hex 32`) |
| `JWT_ALGORITHM` | | Default: `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | | Default: `60` |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | | Default: `30` |
| `CORS_ORIGINS` | | JSON array of allowed origins |
| `GCS_BUCKET_NAME` | | Cloud Storage bucket for proof photos |
| `APP_ENV` | | `development` \| `production` |

---

## Development Commands

```bash
make dev          # Run API with hot reload
make db           # Start PostgreSQL via Docker
make migrate      # Apply Alembic migrations
make revision msg="add users table"  # Create new migration
make test         # Run test suite
make lint         # Ruff linter
make format       # Ruff formatter
make typecheck    # MyPy strict check
make check        # lint + typecheck + test (CI gate)
```

---

## GCP Deployment

```
Cloud Run  ──► lendbook-be container (this repo)
               │
               ├── Cloud SQL (Postgres 16) — private IP
               ├── Cloud Storage — proof photos
               └── Secret Manager — JWT_SECRET_KEY, DB_PASSWORD
```

```bash
# Build and push Docker image
gcloud builds submit --tag gcr.io/PROJECT_ID/lendbook-be

# Deploy to Cloud Run
gcloud run deploy lendbook-be \
  --image gcr.io/PROJECT_ID/lendbook-be \
  --region asia-south1 \
  --add-cloudsql-instances PROJECT:REGION:INSTANCE \
  --set-secrets JWT_SECRET_KEY=jwt-secret:latest \
  --set-env-vars APP_ENV=production
```

---

## Testing

```bash
# Unit tests
pytest tests/unit/

# Integration tests (requires running DB)
pytest tests/integration/

# Full suite with coverage
pytest
```

---

## Code Standards

Follows the project Python standards:
- Async-first (`async/await` for all I/O)
- Architecture: `routes → services → repositories → models`
- Pydantic v2 for all input validation
- Ruff + MyPy strict enforced in CI

---

## Frontend

See [`lendbook-fe`](https://github.com/7177821l212/lend_books-fe) — React Native (Expo).
