"""Test fixtures.

Isolation strategy: each test runs inside a single outer DB transaction that is
rolled back at the end. The session joins that transaction using SAVEPOINTs
(`join_transaction_mode="create_savepoint"`), so handler-level `commit()` calls
don't actually persist — they release a savepoint and a new one begins. Nothing
survives the test.

We use httpx's AsyncClient on a single event loop and a NullPool engine, because
the module-level async engine + Starlette's sync TestClient causes
"Future attached to a different loop" errors.
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import create_access_token, hash_password
from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.enums import RoomStatus, TaskPriority, TaskStatus, UserRole
from app.models.hotel import Hotel
from app.models.room import Room
from app.models.task import Task
from app.models.user import User

settings = get_settings()


def auth_headers(user: User) -> dict[str, str]:
    """Build an Authorization header for a user without a login round-trip."""
    token = create_access_token(
        subject=str(user.id),
        extra_claims={"hotel_id": str(user.hotel_id), "role": user.role.value},
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    assert settings.test_database_url, "TEST_DATABASE_URL must be set"
    engine = create_async_engine(
        settings.test_database_url,
        poolclass=NullPool,
        connect_args={"ssl": "require"},
    )
    connection = await engine.connect()
    trans = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield session
    finally:
        app.dependency_overrides.pop(get_db, None)
        await session.close()
        await trans.rollback()
        await connection.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_hotel(db: AsyncSession, name: str) -> Hotel:
    hotel = Hotel(name=name)
    db.add(hotel)
    await db.flush()
    return hotel


async def _make_user(
    db: AsyncSession,
    hotel: Hotel,
    email: str,
    role: UserRole,
    password: str = "password123",
) -> User:
    user = User(
        hotel_id=hotel.id,
        email=email,
        password_hash=hash_password(password),
        name=email.split("@")[0],
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def test_hotel(db_session: AsyncSession) -> Hotel:
    return await _make_hotel(db_session, "Test Hotel")


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession, test_hotel: Hotel) -> User:
    return await _make_user(db_session, test_hotel, "admin@test.com", UserRole.ADMIN)


@pytest_asyncio.fixture
async def manager_user(db_session: AsyncSession, test_hotel: Hotel) -> User:
    return await _make_user(
        db_session, test_hotel, "manager@test.com", UserRole.MANAGER
    )


@pytest_asyncio.fixture
async def housekeeper_user(db_session: AsyncSession, test_hotel: Hotel) -> User:
    return await _make_user(
        db_session, test_hotel, "housekeeper@test.com", UserRole.HOUSEKEEPER
    )


@pytest_asyncio.fixture
async def test_room(db_session: AsyncSession, test_hotel: Hotel) -> Room:
    room = Room(
        hotel_id=test_hotel.id,
        room_number="101",
        floor=1,
        room_type="STD",
        status=RoomStatus.DIRTY,
    )
    db_session.add(room)
    await db_session.flush()
    return room


@pytest_asyncio.fixture
async def test_task(
    db_session: AsyncSession,
    test_hotel: Hotel,
    test_room: Room,
    housekeeper_user: User,
) -> Task:
    task = Task(
        hotel_id=test_hotel.id,
        room_id=test_room.id,
        assigned_to=housekeeper_user.id,
        status=TaskStatus.ASSIGNED,
        priority=TaskPriority.NORMAL,
    )
    db_session.add(task)
    await db_session.flush()
    return task


@pytest_asyncio.fixture
async def other_hotel(db_session: AsyncSession) -> Hotel:
    """A second tenant, for cross-hotel isolation tests."""
    return await _make_hotel(db_session, "Other Hotel")


@pytest_asyncio.fixture
async def other_admin(db_session: AsyncSession, other_hotel: Hotel) -> User:
    return await _make_user(
        db_session, other_hotel, "other-admin@test.com", UserRole.ADMIN
    )
