# sevenone-housekeeping-service

Backend API for a multi-tenant hotel housekeeping SaaS platform.
FastAPI + async SQLAlchemy + PostgreSQL (Neon).

## Documentation

- [Implementation plan](PLAN.md) — architecture, schema, and phased progress
- [Authentication & authorization](docs/auth.md) — password hashing, JWT, roles, tenant isolation

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
