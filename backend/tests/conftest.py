"""Test harness: isolated SQLite database, real app, no network calls."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TMPDIR = tempfile.mkdtemp(prefix="armx-test-")
os.environ.update(
    {
        "ENV": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{TMPDIR}/test.db",
        "JWT_SECRET": "test-secret-that-is-long-enough-for-hs256-signing",
        "AUTO_CREATE_TABLES": "true",
        "LLM_PROVIDER": "mock",
        "PIPELINE_MODE": "simulated",
        "MESSAGING_MODE": "simulated",
        "PROJECT_WORKSPACE": f"{TMPDIR}/workspace",
        "REQUIRE_EMAIL_VERIFICATION": "false",
        "WEB_ORIGIN": "http://localhost:3000",
        "SEARCH_PROVIDER": "none",
        "HOME_ASSISTANT_URL": "",
        "HOME_ASSISTANT_TOKEN": "",
        "RATE_LIMIT_DISABLED": "1",
    }
)

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.security import rate_limiter  # noqa: E402
from app.main import create_app  # noqa: E402
from app.registry import registry  # noqa: E402

app = create_app()


@pytest.fixture(scope="session", autouse=True)
def _prepare_db() -> None:
    import asyncio

    registry.load()

    async def _create() -> None:
        import app.models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    Path(settings.PROJECT_WORKSPACE).mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
async def _clean_tables():
    """Truncate between tests so ordering never matters."""
    rate_limiter._buckets.clear()  # noqa: SLF001 - test isolation
    yield
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"DELETE FROM {table.name}"))


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def db():
    async with SessionLocal() as session:
        yield session


async def _signup(client: httpx.AsyncClient, email: str, password: str = "Sup3rSecret!") -> dict:
    resp = await client.post(
        "/api/auth/signup", json={"email": email, "password": password, "display_name": "Tester"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def user_tokens(client):
    return await _signup(client, "user@example.com")


@pytest.fixture
async def auth_headers(user_tokens):
    return {"Authorization": f"Bearer {user_tokens['access_token']}"}


@pytest.fixture
async def admin_tokens(client):
    """Promote a second account to admin directly (CLI would do this in production)."""
    from sqlalchemy import select

    from app.models import User

    tokens = await _signup(client, "admin@example.com")
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == "admin@example.com"))).scalar_one()
        user.role = "admin"
        await session.commit()
    return tokens


@pytest.fixture
async def vip_tokens(client):
    from sqlalchemy import select

    from app.models import User

    tokens = await _signup(client, "vip@example.com")
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == "vip@example.com"))).scalar_one()
        user.role = "vip"
        await session.commit()
    return tokens


@pytest.fixture
def admin_headers(admin_tokens):
    return {"Authorization": f"Bearer {admin_tokens['access_token']}"}


@pytest.fixture
def vip_headers(vip_tokens):
    return {"Authorization": f"Bearer {vip_tokens['access_token']}"}
