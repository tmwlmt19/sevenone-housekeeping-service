# Local Development

How to run the SevenOne Housekeeping API on your machine. No local Postgres or
Docker is required — the app talks to a **Neon** cloud database that is already
configured in `.env`.

> See also: [deployment.md](deployment.md) (Railway / production) and
> [auth.md](auth.md) (JWT, roles, tenant isolation).

---

## Prerequisites

- **Python 3.12** (`.python-version` pins `3.12.13`).
- A `.env` file in the repo root (already present in local checkouts). If you
  need to recreate it, `cp .env.example .env` and fill in the values — see
  [Environment](#environment).

## One-time setup

```bash
# Create the virtualenv and install dependencies
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Apply database migrations (safe to re-run; no-op if already at head)
.venv/bin/alembic upgrade head
```

## Run the API

```bash
.venv/bin/uvicorn app.main:app --reload
```

- API: <http://localhost:8000>
- Health check: <http://localhost:8000/health> → `{"status": "ok"}`
- Interactive docs (Swagger): <http://localhost:8000/docs>
- OpenAPI schema: <http://localhost:8000/openapi.json> (the frontend generates
  its typed client from this)

`--reload` restarts the server on code changes. Drop it for a non-watching run.

---

## Environment

`.env` (loaded by `app/config.py`) holds:

| Variable                      | Purpose                                                        |
| ----------------------------- | ------------------------------------------------------------- |
| `DATABASE_URL`                | Neon connection string (async; SSL handled in code).          |
| `TEST_DATABASE_URL`           | Separate Neon **`test` branch** used only by the test suite.  |
| `JWT_SECRET`                  | Signing secret for access tokens.                             |
| `JWT_ALGORITHM`               | `HS256`.                                                      |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` (24h). No refresh token yet.                           |
| `CORS_ORIGINS`                | Comma-separated allowed origins. Includes the Vite dev server `http://localhost:5173`. |

> ⚠️ **The local `.env` points at the real, shared Neon database**, not a
> throwaway. Data you create while running locally persists. The test suite is
> isolated: it uses the `test` branch with per-test transaction rollback.

---

## Database state & seeding

The schema is migrated to head. Bootstrap an initial hotel + admin with the seed
script (idempotent — re-running with an existing email is a no-op):

```bash
.venv/bin/python -m app.seed \
  --email admin@example.com --password <password> \
  --name "Site Admin" --hotel-name "Demo Hotel"
```

### Dev credentials (MVP only)

A seeded admin already exists for local development and demos:

| Field    | Value            |
| -------- | ---------------- |
| Email    | `admin@demo.com` |
| Password | `DemoAdmin123!`  |
| Role     | `admin`          |
| Hotel    | `Demo Hotel`     |

> ⚠️ **Committing credentials is not something we'd normally do.** This is an
> explicit, temporary exception for MVP development against shared demo data.
> Rotate/remove this before the product handles any real customer data, and move
> secrets (including `.env`) out of the repo.

To reset this password (the seed script won't overwrite an existing user):

```bash
.venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import select
from app.auth import hash_password
from app.database import AsyncSessionLocal
from app.models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(
            select(User).where(User.email == "admin@demo.com")
        )).scalar_one()
        u.password_hash = hash_password("DemoAdmin123!")
        await db.commit()
        print("password reset")

asyncio.run(main())
PY
```

---

## Running the test suite

```bash
.venv/bin/python -m pytest
```

Tests run against `TEST_DATABASE_URL` (the Neon `test` branch) with per-test
rollback, so they never persist data. See [PLAN.md](../PLAN.md) §7.

---

## Connecting the frontend

The web app (`sevenone-housekeeping-web`) reads its base URL from
`VITE_API_BASE_URL`. Point it at this server:

```
VITE_API_BASE_URL=http://localhost:8000
```

`CORS_ORIGINS` already allows the Vite dev origin (`http://localhost:5173`), so
no extra config is needed for local development.
