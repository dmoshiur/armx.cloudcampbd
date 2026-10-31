#!/usr/bin/env python
"""Create the first Admin account.

This is the ONLY way an admin is ever created - public signup always produces a
standard user. Run it on the server:

    python -m scripts.create_admin --email you@example.com

The password is read from a prompt (or FIRST_ADMIN_PASSWORD / --password for
automation). Re-running with an existing email promotes that account instead of
creating a duplicate.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import EmailStr, TypeAdapter  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal, init_models  # noqa: E402
from app.core.security import hash_password, password_problems  # noqa: E402
from app.models import Role, User  # noqa: E402


async def create_admin(email: str, password: str, display_name: str) -> int:
    problems = password_problems(password)
    if problems:
        print(f"Refusing: password {', '.join(problems)}", file=sys.stderr)
        return 1

    async with SessionLocal() as db:
        await init_models()
        existing = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
        if existing is not None:
            existing.role = Role.ADMIN.value
            existing.password_hash = hash_password(password)
            existing.is_verified = True
            existing.is_active = True
            await db.commit()
            print(f"Promoted existing account {email} to admin and rotated its password.")
            return 0

        user = User(
            email=email.lower(),
            display_name=display_name or email.split("@")[0],
            password_hash=hash_password(password),
            role=Role.ADMIN.value,
            is_verified=True,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(f"Created admin {email} (id={user.id}).")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", default=settings.FIRST_ADMIN_EMAIL, help="admin email")
    parser.add_argument("--password", default="", help="password (otherwise prompted)")
    parser.add_argument("--name", default="", help="display name")
    args = parser.parse_args()

    email = (args.email or input("Admin email: ")).strip()
    try:
        # Use the same validator as the API so the CLI cannot create an account
        # that can never sign in (e.g. a reserved TLD like example.local).
        email = TypeAdapter(EmailStr).validate_python(email)
    except Exception:
        print(
            f"'{email}' is not a deliverable email address. Use a real domain "
            "(reserved names such as .local or .invalid are rejected).",
            file=sys.stderr,
        )
        return 2

    password = args.password or settings.FIRST_ADMIN_PASSWORD
    if not password:
        password = getpass.getpass("Admin password (min 10 chars, upper + symbol): ")
        if getpass.getpass("Confirm password: ") != password:
            print("Passwords do not match", file=sys.stderr)
            return 2

    return asyncio.run(create_admin(email, password, args.name))


if __name__ == "__main__":
    raise SystemExit(main())
