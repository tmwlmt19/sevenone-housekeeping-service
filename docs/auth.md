# Authentication & Authorization

This document explains how auth works in the housekeeping service: password
storage, JWT sessions, and how FastAPI's dependency injection enforces
authentication, roles, and multi-tenant isolation.

Relevant files:
- [`app/auth.py`](../app/auth.py) — password hashing + JWT create/decode
- [`app/dependencies.py`](../app/dependencies.py) — auth/role/tenant dependencies
- [`app/routers/auth.py`](../app/routers/auth.py) — `/login` and `/me` endpoints
- [`app/seed.py`](../app/seed.py) — initial admin/hotel seeding

---

## 1. Password hashing

Passwords are never stored — only a one-way **bcrypt** hash is. bcrypt is a
deliberately slow, salted password-hashing function (unlike fast general-purpose
hashes like SHA-256, which are brute-forceable).

```python
def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")
```

- `bcrypt.gensalt()` produces a **random salt per password**, so identical
  passwords yield different hashes (defeats rainbow tables).
- The salt and cost factor are embedded in the output hash string
  (`$2b$<cost>$<salt><digest>`), so verification needs only the stored hash:

```python
def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(_prepare(password), password_hash.encode("utf-8"))
```

`checkpw` re-hashes the candidate using the salt/cost from the stored hash and
does a constant-time comparison. Hashing is **one-way**: we never decrypt, we
only re-hash and compare.

**72-byte truncation.** bcrypt only considers the first 72 bytes of input, and
bcrypt 5.x raises rather than silently truncating, so `_prepare()` truncates
explicitly before hashing and verifying.

> **Library note:** We use the `bcrypt` package directly instead of `passlib`.
> `passlib` has been unmaintained since 2020 and raises on bcrypt 5.x
> (`module 'bcrypt' has no attribute '__about__'`). See `requirements.txt`.

---

## 2. JWT sessions

A login returns a **JSON Web Token (JWT)** — a signed token the client sends on
every subsequent request. Sessions are **stateless**: the server stores nothing;
the token's signature is self-verifying.

```python
payload = {"sub": str(user.id), "iat": now, "exp": expire,
           "hotel_id": str(user.hotel_id), "role": user.role.value}
jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
```

Claims:
- `sub` — the user id (the subject of the token)
- `iat` / `exp` — issued-at / expiry (expiry from `ACCESS_TOKEN_EXPIRE_MINUTES`)
- `hotel_id`, `role` — convenience claims for tenancy/role decisions

**Signed, not encrypted.** The token is signed with `JWT_SECRET` using HMAC-SHA256
(HS256). The signature proves we issued it and it wasn't tampered with, but the
payload is only base64-encoded — **anyone can read it**. Therefore:
- Never put secrets in a JWT, only identifiers. (We don't store PII, so the
  `hotel_id`/`role` claims are fine.)
- `JWT_SECRET` must stay secret and be a long random value in production.

```python
def decode_access_token(token: str):
    try:
        return jwt.decode(token, settings.jwt_secret,
                          algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
```

`jwt.decode` verifies the signature **and** checks `exp` in one step. Passing
`algorithms=[...]` explicitly is a security requirement — it prevents
"alg: none" and algorithm-confusion attacks.

**Tradeoff:** stateless tokens can't be revoked before they expire, which is why
the lifetime is bounded. If we later need revocation, options are a short-lived
access token + refresh token, or a server-side denylist.

---

## 3. FastAPI dependency injection

FastAPI resolves an endpoint's needs from its function signature: parameters
declared with `Depends(...)` are built (recursively) before the handler runs.
This replaces the ordered middleware chain pattern from frameworks like Express —
each route *declares* exactly which "middleware" it requires.

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    claims = decode_access_token(token)
    # ...validate claims, load and return the User, else raise 401
```

- `OAuth2PasswordBearer` extracts the token from the
  `Authorization: Bearer <token>` header (and enables the docs "Authorize"
  box). `tokenUrl` is documentation metadata only.
- `Depends(get_db)` injects an `AsyncSession`. Dependencies can depend on other
  dependencies; FastAPI builds and deduplicates the graph per request.

Any endpoint that needs the logged-in user just declares it:

```python
@router.get("/me")
async def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user
```

If the token is missing/expired/invalid, `get_current_user` raises `401` and the
handler body never executes.

---

## 4. Role-based authorization

Roles are enforced with a **dependency factory** — a function that returns a
dependency closure:

```python
def require_roles(*roles: UserRole):
    async def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(403, "...")
        return current_user
    return _checker

require_admin = require_roles(UserRole.ADMIN)
require_manager_or_above = require_roles(UserRole.ADMIN, UserRole.MANAGER)
```

Usage in a protected endpoint:

```python
async def create_room(..., current_user: User = Depends(require_admin)):
    ...
```

Both failure cases are handled before the handler runs, with a deliberate
status-code distinction:
- **401 Unauthorized** — not authenticated ("who are you?")
- **403 Forbidden** — authenticated but wrong role ("you can't do this")

---

## 5. Multi-tenant isolation

Every hotel-scoped URL is `/api/v1/hotels/{hotel_id}/...`. `require_same_hotel`
checks the path's `hotel_id` against the `hotel_id` baked into the user's token:

```python
def require_same_hotel(hotel_id, current_user):
    if current_user.hotel_id != hotel_id:
        raise HTTPException(404, "Resource not found")
```

It returns **404, not 403**, on purpose: a 403 would leak that the hotel exists.
A 404 reveals nothing about other tenants. This check is applied in every
hotel-scoped endpoint.

---

## Request lifecycle

1. `POST /api/v1/auth/login` with email + password → look up user →
   `verify_password` → issue a JWT carrying `sub`, `hotel_id`, `role`.
2. Client stores the token and sends `Authorization: Bearer <token>` on
   subsequent requests.
3. On a protected route:
   `OAuth2PasswordBearer` (extract token) →
   `get_current_user` (decode/validate, load `User`) →
   role guard (e.g. `require_admin`) →
   `require_same_hotel` (tenant check) →
   handler runs.

---

## Seeding the first user

There is no public signup. Bootstrap an initial hotel + admin with:

```bash
python -m app.seed --email admin@example.com --password <password> \
    --name "Site Admin" --hotel-name "Demo Hotel"
```

The script is idempotent on the admin email. After that, admins/managers create
additional users through the API.
