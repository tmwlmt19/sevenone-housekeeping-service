# SevenOne Housekeeping Service — Implementation Plan

## Overview

Python (FastAPI) backend for a multi-tenant hotel housekeeping SaaS platform. PostgreSQL on Neon. Deployed to Railway. Serves a React frontend (separate repo/project) via REST API.

---

## 1. Tech Stack

| Layer          | Choice                          |
|----------------|---------------------------------|
| Framework      | FastAPI                         |
| ORM            | SQLAlchemy (async) + Alembic    |
| Database       | PostgreSQL on Neon (serverless) |
| Auth           | JWT (bcrypt password hashing)   |
| Validation     | Pydantic v2 (built into FastAPI)|
| Hosting        | Railway                         |

---

## 2. Project Structure

```
sevenone-housekeeping-service/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, CORS, lifespan
│   ├── config.py            # Settings via pydantic-settings (DATABASE_URL, JWT_SECRET, etc.)
│   ├── database.py          # SQLAlchemy async engine & session
│   ├── models/              # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── hotel.py
│   │   ├── user.py
│   │   ├── room.py
│   │   └── task.py
│   ├── schemas/             # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── hotel.py
│   │   ├── user.py
│   │   ├── room.py
│   │   ├── task.py
│   │   └── auth.py
│   ├── routers/             # FastAPI route handlers
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── hotels.py
│   │   ├── users.py
│   │   ├── rooms.py
│   │   └── tasks.py
│   ├── dependencies.py      # get_db, get_current_user, role checks
│   └── auth.py              # JWT creation/verification, password hashing
├── alembic/                 # Database migrations
│   └── versions/
├── alembic.ini
├── requirements.txt
├── .env.example
└── PLAN.md
```

---

## 3. Database Schema

### hotels

| Column       | Type         | Notes                  |
|--------------|--------------|------------------------|
| id           | UUID (PK)    | Default: gen_random_uuid() |
| name         | VARCHAR(255) | NOT NULL               |
| address      | TEXT         | Optional               |
| created_at   | TIMESTAMPTZ  | Default: now()         |
| updated_at   | TIMESTAMPTZ  | Auto-update            |

### users

| Column       | Type         | Notes                      |
|--------------|--------------|----------------------------|
| id           | UUID (PK)    |                            |
| hotel_id     | UUID (FK)    | References hotels.id       |
| email        | VARCHAR(255) | UNIQUE, NOT NULL           |
| password_hash| VARCHAR(255) | NOT NULL                   |
| name         | VARCHAR(255) | NOT NULL                   |
| role         | PG ENUM      | 'admin' / 'manager' / 'housekeeper'. Postgres enum. |
| created_at   | TIMESTAMPTZ  |                            |
| updated_at   | TIMESTAMPTZ  |                            |

- One user belongs to exactly one hotel.
- `admin` can manage hotels, users, rooms, tasks.
- `manager` can manage rooms, tasks, and users within their hotel.
- `housekeeper` can view their assigned tasks and update task status.

### rooms

| Column       | Type         | Notes                      |
|--------------|--------------|----------------------------|
| id           | UUID (PK)    |                            |
| hotel_id     | UUID (FK)    | References hotels.id       |
| room_number  | VARCHAR(50)  | NOT NULL                   |
| floor        | INTEGER      | Optional                   |
| room_type    | VARCHAR(20)  | Short code, e.g. 'STD', 'STE', 'DLX', 'PNT', 'FAM'. Validated at API level, not a Postgres enum — hotels can define custom types without migrations. |
| status       | PG ENUM      | 'clean' / 'dirty' / 'in_progress' / 'out_of_service'. Postgres enum — these are system-defined states the app logic branches on. |
| created_at   | TIMESTAMPTZ  |                            |
| updated_at   | TIMESTAMPTZ  |                            |

- Unique constraint on (hotel_id, room_number).

### tasks

| Column       | Type         | Notes                      |
|--------------|--------------|----------------------------|
| id           | UUID (PK)    |                            |
| hotel_id     | UUID (FK)    | References hotels.id       |
| room_id      | UUID (FK)    | References rooms.id        |
| assigned_to  | UUID (FK)    | References users.id, nullable |
| status       | PG ENUM      | 'pending' / 'assigned' / 'in_progress' / 'completed'. Postgres enum. |
| priority     | PG ENUM      | 'low' / 'normal' / 'urgent'. Postgres enum. |
| notes        | TEXT         | Optional                   |
| due_date     | TIMESTAMPTZ  | Optional                   |
| completed_at | TIMESTAMPTZ  | Set when status → completed|
| created_at   | TIMESTAMPTZ  |                            |
| updated_at   | TIMESTAMPTZ  |                            |

---

## 4. API Endpoints (MVP)

### Auth
| Method | Path               | Description              | Access    |
|--------|--------------------|--------------------------|-----------|
| POST   | `/api/v1/auth/login` | Login, returns JWT token | Public    |

### Hotels
| Method | Path                    | Description       | Access    |
|--------|-------------------------|-------------------|-----------|
| POST   | `/api/v1/hotels`        | Create hotel      | Admin     |
| GET    | `/api/v1/hotels/{id}`   | Get hotel details | Auth'd    |
| PUT    | `/api/v1/hotels/{id}`   | Update hotel      | Admin     |

### Users
| Method | Path                                  | Description        | Access          |
|--------|---------------------------------------|--------------------|-----------------|
| POST   | `/api/v1/hotels/{hotel_id}/users`     | Create user        | Admin, Manager  |
| GET    | `/api/v1/hotels/{hotel_id}/users`     | List hotel users   | Admin, Manager  |
| GET    | `/api/v1/hotels/{hotel_id}/users/{id}`| Get user           | Auth'd          |
| PUT    | `/api/v1/hotels/{hotel_id}/users/{id}`| Update user        | Admin, Manager  |
| DELETE | `/api/v1/hotels/{hotel_id}/users/{id}`| Delete user        | Admin, Manager  |

### Rooms
| Method | Path                                   | Description        | Access          |
|--------|----------------------------------------|--------------------|-----------------|
| POST   | `/api/v1/hotels/{hotel_id}/rooms`      | Create room        | Admin, Manager  |
| GET    | `/api/v1/hotels/{hotel_id}/rooms`      | List hotel rooms   | Auth'd          |
| GET    | `/api/v1/hotels/{hotel_id}/rooms/{id}` | Get room           | Auth'd          |
| PUT    | `/api/v1/hotels/{hotel_id}/rooms/{id}` | Update room        | Admin, Manager  |
| DELETE | `/api/v1/hotels/{hotel_id}/rooms/{id}` | Delete room        | Admin, Manager  |

### Tasks
| Method | Path                                    | Description        | Access          |
|--------|-----------------------------------------|--------------------|-----------------|
| POST   | `/api/v1/hotels/{hotel_id}/tasks`       | Create task        | Admin, Manager  |
| GET    | `/api/v1/hotels/{hotel_id}/tasks`       | List tasks (filterable by status, assigned_to) | Auth'd |
| GET    | `/api/v1/hotels/{hotel_id}/tasks/{id}`  | Get task           | Auth'd          |
| PUT    | `/api/v1/hotels/{hotel_id}/tasks/{id}`  | Update task        | Admin, Manager  |
| PATCH  | `/api/v1/hotels/{hotel_id}/tasks/{id}/status` | Update task status | Assigned user, Manager, Admin |

---

## 5. Auth & Permissions Design

- **Login** returns a JWT containing `user_id`, `hotel_id`, and `role`.
- Token is passed as `Authorization: Bearer <token>` header.
- A dependency (`get_current_user`) decodes the token and loads the user.
- Role-based dependencies: `require_admin`, `require_manager_or_above`, etc.
- All hotel-scoped endpoints verify the user's `hotel_id` matches the URL's `hotel_id` (tenant isolation).
- No signup endpoint in MVP — an admin creates the first user via a seed script, then creates others through the API.

---

## 6. Implementation Order

### Phase 1: Project skeleton ✅
- [x] Initialize Python project (requirements.txt, .env.example, .gitignore updates)
- [x] Pin Python 3.12 (`.python-version`) — 3.14 lacks wheels for pydantic-core/bcrypt
- [x] Set up FastAPI app with CORS, health check endpoint
- [x] Configure SQLAlchemy async engine + session management
- [x] Set up Alembic for migrations (async, URL + metadata wired to app settings)

### Phase 2: Neon database ✅
- [x] Create Neon project and database (`sevenone-housekeeping-db`, project `orange-river-29984576`, Postgres 17)
- [x] Create separate `test` branch for the test suite
- [x] Configure connection string (`.env` from `.env.example`; direct non-pooler endpoints, SSL via `connect_args`)
- [x] Verified async connectivity to both `main` and `test` branches

**Neon reference** (credentials live only in `.env`, which is gitignored):
- Project: `sevenone-housekeeping-db` — `orange-river-29984576`
- Branch `main` (prod): `br-delicate-hat-at2trvcz`
- Branch `test`: `br-dawn-wildflower-at7qi2kp`
- Note: using **direct** (non-pooler) endpoints to avoid asyncpg + pgbouncer prepared-statement issues; revisit pooling if concurrency grows.

### Phase 3: Models & migrations ✅
- [x] Define all SQLAlchemy models (hotels, users, rooms, tasks) with shared UUID PK + timestamp mixins
- [x] Native Postgres enums (`user_role`, `room_status`, `task_status`, `task_priority`) persisting lowercase values
- [x] Generate initial Alembic migration (`286a7875aaf9`); enum types dropped in downgrade for re-upgrade safety
- [x] Apply migration to both `main` and `test` branches; verified tables + enum types present

### Phase 4: Auth ✅
- [x] Password hashing utilities (bcrypt directly — dropped passlib, which is unmaintained and breaks on bcrypt 5.x)
- [x] JWT creation / verification (python-jose; token carries `sub`=user id, `hotel_id`, `role`)
- [x] Login endpoint (`POST /api/v1/auth/login`, JSON) + `GET /api/v1/auth/me`
- [x] Auth dependencies (`get_current_user`, `require_roles`/`require_admin`/`require_manager_or_above`, `require_same_hotel`)
- [x] Seed script (`python -m app.seed`) — creates a hotel + admin user, idempotent on email
- [x] Verified full flow (bad/good login, /me with valid/missing/bad tokens)

> **Phase 6 testing note:** the module-level async engine + Starlette's sync `TestClient` causes "Future attached to a different loop" errors, because TestClient spins up a new event loop per request while the pooled asyncpg connection is bound to the first. Use httpx `AsyncClient` (single loop) and `NullPool` in test fixtures.

### Phase 5: CRUD endpoints ✅
- [x] Hotels router (create = admin/platform; get/update tenant-scoped)
- [x] Users router (CRUD, manager+ for writes, email-uniqueness 409, password hashing)
- [x] Rooms router (CRUD, unique room_number per hotel 409, room_type normalized to uppercase)
- [x] Tasks router (CRUD + `PATCH /{id}/status`; assignee-or-manager guard; cross-entity validation 400; auto-assign on create; completing a task sets `completed_at` and marks the room clean)
- [x] All routers tenant-scoped via `require_same_hotel` (404 on cross-tenant)
- [x] Verified end-to-end against the `test` branch (16/16 smoke checks: CRUD, permissions, isolation, side effects)

### Phase 6: Testing ✅
- [x] Test infrastructure (conftest, fixtures, NullPool engine on `test` branch, per-test transaction rollback via savepoint-joining session)
- [x] Auth tests (login success/failure, /me with valid/missing/bad tokens)
- [x] CRUD + permissions tests (hotels, users, rooms, tasks; role guards; 409 conflicts; 400 validation; completion side effects)
- [x] Tenant isolation tests (cross-hotel read/write → 404)
- [x] **41 tests passing.** Added `eager_defaults=True` to models so server-side defaults are fetched via RETURNING (avoids lazy IO under async / shared-session tests)

### Phase 7: Deploy
- [ ] Railway configuration (Procfile or railway.toml)
- [ ] Environment variables on Railway
- [ ] Verify deployment

---

## 7. Testing Strategy

### Approach: Integration tests over unit tests

Most of this app's logic is request → database → response. Mocking the database hides the real bugs (bad queries, constraint violations, missing migrations). Tests should hit a real Postgres instance.

### Tooling

| Package          | Purpose                                      |
|------------------|----------------------------------------------|
| pytest           | Test runner                                  |
| pytest-asyncio   | Async test support (SQLAlchemy async sessions)|
| httpx            | FastAPI's `TestClient` uses this under the hood |

### Test database

- Use a **Neon branch** as the test database — branching is instant and free, and the schema stays in sync with the main branch via migrations.
- Connection string set via `TEST_DATABASE_URL` env var.
- Alembic migrations run once at the start of the test session.

### Test isolation

- Each test runs inside a **database transaction that rolls back** at the end. Tests never commit, so they can't interfere with each other and don't need cleanup.
- A pytest fixture wraps the session in a savepoint and rolls back after each test.

### Fixtures (in `conftest.py`)

| Fixture           | What it provides                              |
|-------------------|-----------------------------------------------|
| `db_session`      | Async SQLAlchemy session (auto-rollback)       |
| `client`          | httpx `AsyncClient` wired to the FastAPI app   |
| `test_hotel`      | A seeded hotel for most tests to use           |
| `admin_user`      | User with `admin` role + auth headers          |
| `manager_user`    | User with `manager` role + auth headers        |
| `housekeeper_user`| User with `housekeeper` role + auth headers    |
| `test_room`       | A room in `test_hotel`                         |
| `test_task`       | A task assigned to `housekeeper_user`          |

### Test structure

```
tests/
├── conftest.py            # Fixtures, test DB setup, session management
├── test_auth.py           # Login, token validation, expired/missing tokens
├── test_hotels.py         # Hotel CRUD
├── test_users.py          # User CRUD + role-based access
├── test_rooms.py          # Room CRUD + unique constraint on room_number
├── test_tasks.py          # Task CRUD + status transitions
└── test_tenant_isolation.py  # Cross-hotel access denied
```

### What to test

**Auth**
- Login with valid credentials returns JWT
- Login with wrong password returns 401
- Request with expired/missing/malformed token returns 401

**CRUD (per resource)**
- Create → 201, returns created object
- List → 200, returns array filtered by hotel
- Get by ID → 200 / 404
- Update → 200, fields actually changed
- Delete → 204 / 404

**Permissions**
- Housekeeper cannot create/update/delete rooms, users, or tasks
- Housekeeper CAN update status on their own assigned tasks
- Manager can manage within their hotel
- Admin can manage everything

**Tenant isolation**
- User from Hotel A gets 403/404 when accessing Hotel B's rooms/tasks/users
- Listing resources only returns items from the user's hotel

**Edge cases**
- Duplicate room number within same hotel → 409
- Assign task to user from a different hotel → 400
- Complete a task → `completed_at` timestamp is set, room status updates to `clean`

### What NOT to test (MVP)

- Pydantic schema validation (framework-level, tested by FastAPI)
- SQLAlchemy model field definitions in isolation
- Individual helper functions unless they contain branching logic

---

## 8. Post-MVP Roadmap

Items below are **out of MVP scope** but will be built after validation. Ordered roughly by expected priority.

### Near-term (post-MVP)

- **Onboarding portal (separate React repo)** — A frontend web app (separate repository) providing a public **sign-up page** and self-service admin flows (add rooms, manage staff, etc.). This replaces `app/seed.py`, which stays only as the initial-admin bootstrap for fresh deployments. The backend will need a public registration endpoint (create hotel + first admin in one call) to support sign-up.
- **Hotel onboarding (bulk)** — Batch import from a CSV/Excel file of hotel data (rooms, staff) via an `/api/v1/hotels/{hotel_id}/import` endpoint that accepts a file upload.
- **Task history / audit log** — A `task_events` table recording every status change, assignment change, and edit with `user_id`, `timestamp`, and `old_value → new_value`. Enables "who did what and when" queries.
- **Room type & subtype** — Replace the simple `room_type` VARCHAR with a structured approach: `type` (standard, suite, deluxe, etc.) and `subtype` attributes (bed count, bed type, bathroom count, etc.). Could be a JSON column or a separate `room_attributes` table depending on query needs.
- **Bulk operations** — Mark multiple rooms dirty/clean in one call (e.g., after a block of checkouts). Endpoint like `PATCH /api/v1/hotels/{hotel_id}/rooms/bulk-status`.
- **Reporting / dashboard** — Task completion rates, average turnaround time, housekeeper workload distribution. Likely dedicated read-only endpoints that the frontend dashboard consumes.

### Longer-term

- **PMS integration** — Tie into booking / front desk software (Opera, Cloudbeds, etc.) to automatically mark rooms dirty on checkout, sync room inventory, and pull guest arrival times for priority cleaning.
- **Notifications** — Alert housekeepers when assigned a task (push notifications, SMS, or in-app).
- **Scheduling** — Auto-assign tasks based on housekeeper availability, floor proximity, workload balancing.
