# sevenone-housekeeping-service

Backend API for a multi-tenant hotel housekeeping SaaS platform.
FastAPI + async SQLAlchemy + PostgreSQL (Neon).

Serves three frontends via cookie-based SSO:

- `sevenone-housekeeping-login` — shared login app (sets the session cookie)
- `sevenone-housekeeping-web` — hotel operations app (managers + housekeepers)
- `sevenone-housekeeping-admin` — platform/owner console (cross-tenant admins)

**Roles:** admin = platform owner (cross-tenant); manager/housekeeper = hotel
employees (tenant-scoped). **Auth:** login sets an httpOnly session cookie
(`/auth/login`), cleared by `/auth/logout`; `get_current_user` reads the cookie
(bearer fallback for tests). See [docs/auth.md](docs/auth.md). Whole-system status
lives in the web repo's `docs/status.md`.

## Documentation

- [Implementation plan](PLAN.md) — architecture, schema, and phased progress
- [Local development](docs/local-development.md) — run the API locally, env, seeding, dev credentials
- [Authentication & authorization](docs/auth.md) — password hashing, JWT, roles, tenant isolation
- [Deployment](docs/deployment.md) — Railway setup, env vars, first-time seeding

## Development

```bash
# Install dependencies (Python 3.12)
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Configure environment
cp .env.example .env   # then fill in DATABASE_URL / TEST_DATABASE_URL / JWT_SECRET

# Apply migrations
.venv/bin/alembic upgrade head

# Seed an initial hotel + admin
.venv/bin/python -m app.seed --email admin@example.com --password <password>

# Run the API locally
.venv/bin/uvicorn app.main:app --reload

# Run the test suite (uses TEST_DATABASE_URL — the Neon "test" branch)
.venv/bin/python -m pytest
```

Tests run against the Neon `test` branch with per-test transaction rollback, so
they never persist data. See [PLAN.md](PLAN.md) §7 for the testing strategy.
