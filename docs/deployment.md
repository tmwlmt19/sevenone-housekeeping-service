# Deployment (Railway)

The service deploys to [Railway](https://railway.com) from this GitHub repo.
Configuration lives in [`railway.toml`](../railway.toml).

## How it builds and runs

- **Builder:** Nixpacks (auto-detects Python from `requirements.txt`; pins the
  version from `.python-version`, currently 3.12).
- **Start command:** `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
  — applies pending migrations, then serves the API on the port Railway injects.
- **Health check:** Railway polls `/health` after each deploy.

## Database

This service uses the existing Neon project `sevenone-housekeeping-db`, branch
`main`. You can paste Neon's connection string into Railway **as-is** — the app
normalizes it at startup (converts `postgresql://` → `postgresql+asyncpg://` and
strips `sslmode`/`channel_binding` query params; SSL is applied in code).

> Use the **direct** (non-pooler) Neon host — i.e. the host *without* `-pooler`.
> The app uses asyncpg, which doesn't play well with Neon's pgbouncer pooler in
> transaction mode. (See PLAN.md §2.)

## Required environment variables

Set these in the Railway service (Variables tab):

| Variable        | Required | Notes                                                        |
|-----------------|----------|--------------------------------------------------------------|
| `DATABASE_URL`  | yes      | Neon `main` branch connection string (direct host).          |
| `JWT_SECRET`    | yes      | Long random string. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `CORS_ORIGINS`  | yes      | Comma-separated frontend origins, e.g. `https://app.example.com` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | Defaults to 1440 (24h).                          |
| `JWT_ALGORITHM` | no       | Defaults to `HS256`.                                         |

`TEST_DATABASE_URL` is **not** needed in production (tests only).

`PORT` is provided by Railway automatically — do not set it.

## First-time setup

1. **Create the Railway project** → "Deploy from GitHub repo" →
   select `sevenone-housekeeping-service`. Railway picks up `railway.toml`.
2. **Add the environment variables** above.
3. **Deploy.** The start command runs migrations automatically, so the schema is
   created/updated on first boot.
4. **Seed the initial admin** (one-time). From the Railway service shell, or
   locally with `DATABASE_URL` pointed at the prod branch:
   ```bash
   python -m app.seed --email admin@yourhotel.com --password <strong-password> \
       --name "Site Admin" --hotel-name "Your Hotel"
   ```
5. **Verify:** open `https://<your-app>.up.railway.app/health` → `{"status":"ok"}`,
   and `https://<your-app>.up.railway.app/docs` for the interactive API.

## Subsequent deploys

Push to `main` (or your configured deploy branch). Railway rebuilds and reruns
the start command; new Alembic migrations apply automatically.
