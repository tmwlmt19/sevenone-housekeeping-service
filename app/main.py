import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.routers import (
    access_requests,
    api_keys,
    auth,
    floor_maps,
    hotels,
    integrations,
    rooms,
    tasks,
    users,
)

logger = logging.getLogger(__name__)
settings = get_settings()


def _warn_on_localhost_email_links(s: Settings) -> None:
    """When mail is actually being delivered (RESEND_API_KEY set) but the URLs
    baked into welcome / password-reset emails still point at localhost, those
    links are dead in a deployed environment. Surface it loudly at boot — this
    is exactly how the welcome-email link got shipped pointing at localhost."""
    if not s.resend_api_key:
        return
    stale = {
        name: value
        for name, value in (
            ("LOGIN_URL", s.login_url),
            ("PASSWORD_RESET_URL_BASE", s.password_reset_url_base),
        )
        if "localhost" in value or "127.0.0.1" in value
    }
    if stale:
        logger.warning(
            "Email delivery is enabled but %s still point at localhost — the "
            "links in welcome/reset emails will be unreachable. Set them to this "
            "environment's login app URL.",
            ", ".join(f"{k}={v}" for k, v in stale.items()),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _warn_on_localhost_email_links(settings)
    yield


app = FastAPI(
    title="SevenOne Housekeeping Service",
    description="Backend API for hotel housekeeping management.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(hotels.router)
app.include_router(users.router)
app.include_router(rooms.router)
app.include_router(tasks.router)
app.include_router(floor_maps.router)
app.include_router(access_requests.router)
app.include_router(api_keys.router)
app.include_router(integrations.router)
