from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_async_dsn(url: str | None) -> str | None:
    """Coerce a Postgres URL into the async (asyncpg) form this app needs.

    Accepts the raw connection string Neon/Railway provide
    (`postgresql://...?sslmode=require&channel_binding=require`) and returns the
    `postgresql+asyncpg://...` form with query params stripped. SSL is applied
    via connect_args in app/database.py, and asyncpg rejects libpq query params
    like `sslmode`/`channel_binding`, so we drop them here.
    """
    if url is None:
        return None
    url = url.split("?", 1)[0]
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    return url


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str
    test_database_url: str | None = None

    _normalize_dsn = field_validator("database_url", "test_database_url")(
        normalize_async_dsn
    )

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # Session cookie (used for cross-app SSO). In prod set cookie_domain to the
    # shared parent domain (e.g. ".sevenone.com") and cookie_secure=true.
    # TODO: refresh tokens are deferred — today the cookie holds the 24h access
    # token and the user re-logs in on expiry. See docs/auth.md.
    session_cookie_name: str = "sevenone_session"
    cookie_domain: str | None = None
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    cors_origins: str = (
        "http://localhost:5173,http://localhost:5174,"
        "http://localhost:5175,http://localhost:3000"
    )

    # Email / password reset. When resend_api_key is unset, sends are a no-op
    # that just logs (dev/test); set it in prod to actually deliver mail. See
    # docs/forgot-password (backlog: self-service forgot-password).
    resend_api_key: str | None = None
    email_from: str = "SevenOne <no-reply@send.sevenone.com>"
    # Login-app route that renders the reset form; the raw token is appended as
    # ?token=... . Prod: https://login.sevenone.com/reset-password
    password_reset_url_base: str = "http://localhost:5174/reset-password"
    # Login-app sign-in URL, linked from the welcome email a new user receives.
    # Prod: https://login.sevenone.com
    login_url: str = "http://localhost:5174"
    password_reset_token_ttl_minutes: int = 30
    # Per-user throttle: refuse to mint a new reset token if one was created for
    # that user within this window.
    password_reset_min_interval_seconds: int = 60

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
