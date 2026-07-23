from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
    access_requests,
    api_keys,
    auth,
    hotels,
    integrations,
    rooms,
    tasks,
    users,
)

settings = get_settings()

app = FastAPI(
    title="SevenOne Housekeeping Service",
    description="Backend API for hotel housekeeping management.",
    version="0.1.0",
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
app.include_router(access_requests.router)
app.include_router(api_keys.router)
app.include_router(integrations.router)
