"""Seed an initial service admin user.

Usage:
    # Hotel-independent platform admin (recommended):
    python -m app.seed --email admin@example.com --password secret \\
        --name "Site Admin"

    # Optionally also create a hotel and attach the admin to it (legacy):
    python -m app.seed --email admin@example.com --password secret \\
        --name "Site Admin" --hotel-name "Demo Hotel"

Re-running with an existing admin email is a no-op (idempotent).
"""

import argparse
import asyncio

from sqlalchemy import select

from app.auth import hash_password
from app.database import AsyncSessionLocal
from app.models.enums import UserRole
from app.models.hotel import Hotel
from app.models.user import User


async def seed_admin(
    *, email: str, password: str, name: str, hotel_name: str | None
) -> None:
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            print(f"User {email!r} already exists — nothing to do.")
            return

        # Platform admins are cross-tenant and belong to no hotel by default.
        hotel_id = None
        if hotel_name:
            hotel = Hotel(name=hotel_name)
            db.add(hotel)
            await db.flush()  # assign hotel.id
            hotel_id = hotel.id

        admin = User(
            hotel_id=hotel_id,
            email=email,
            password_hash=hash_password(password),
            name=name,
            role=UserRole.ADMIN,
        )
        db.add(admin)
        await db.commit()
        where = f" attached to hotel {hotel_name!r}" if hotel_name else ""
        print(f"Created service admin {email!r}{where}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed an initial admin user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="Site Admin")
    parser.add_argument(
        "--hotel-name",
        default=None,
        help="Optionally create and attach a hotel (legacy). "
        "Omit for a hotel-independent service admin.",
    )
    args = parser.parse_args()

    asyncio.run(
        seed_admin(
            email=args.email,
            password=args.password,
            name=args.name,
            hotel_name=args.hotel_name,
        )
    )


if __name__ == "__main__":
    main()
