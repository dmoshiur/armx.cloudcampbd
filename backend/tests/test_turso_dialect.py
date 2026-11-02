from __future__ import annotations

import turso.aio
import turso.aio.sync
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.turso import register_turso_dialect


async def test_embedded_replica_dialect_executes_sql_and_exposes_sync_api(tmp_path, monkeypatch):
    """Exercise our SQLAlchemy bridge without contacting a real Turso tenant."""

    async def local_replica(path: str, remote_url: str, **kwargs):
        return await turso.aio.connect(path)

    async def sync_ok(self):
        return True

    monkeypatch.setattr(turso.aio.sync, "connect", local_replica)
    monkeypatch.setattr(turso.aio.Connection, "push", sync_ok, raising=False)
    monkeypatch.setattr(turso.aio.Connection, "pull", sync_ok, raising=False)
    register_turso_dialect()

    engine = create_async_engine(
        f"sqlite+aioturso_sync:///{tmp_path / 'replica.db'}",
        connect_args={
            "remote_url": "libsql://test.example.turso.io",
            "auth_token": "test-token",
        },
    )
    try:
        async with engine.begin() as connection:
            assert (await connection.execute(text("select 40 + 2"))).scalar_one() == 42
            await connection.execute(text("create table proof (id integer primary key, value text)"))
            await connection.execute(text("insert into proof(value) values ('durable')"))
        async with engine.connect() as connection:
            assert (await connection.execute(text("select count(*) from proof"))).scalar_one() == 1
            raw = await connection.get_raw_connection()
            driver = raw.driver_connection
            assert await driver.push() is True
            assert await driver.pull() is True
    finally:
        await engine.dispose()
