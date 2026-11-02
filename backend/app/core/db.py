"""Async SQLAlchemy engine, session factory and base model."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Literal

from sqlalchemy import DateTime, String, event
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite/libSQL drops tzinfo; normalise before any comparison."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IDFormatMixin:
    """String IDs keep SQLite/Postgres/Turso behaviour identical."""

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)


if settings.turso_enabled:
    from app.core.turso import register_turso_dialect

    register_turso_dialect()
    Path(settings.TURSO_REPLICA_PATH).expanduser().parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    settings.effective_database_url,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,
    future=True,
    connect_args=settings.database_connect_args,
)

if settings.effective_database_url.startswith("sqlite+"):
    # SQLite and Turso replicas require explicit FK enforcement. WAL is managed
    # by Turso itself, so only plain aiosqlite sets that journal mode here.
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver level
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        if settings.effective_database_url.startswith("sqlite+aiosqlite"):
            cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


async def _replica_driver(connection: AsyncConnection):
    raw = await connection.get_raw_connection()
    driver = getattr(raw, "driver_connection", None)
    if driver is None or not hasattr(driver, "push"):
        raise RuntimeError("The configured Turso connection does not expose replica synchronization")
    return driver


async def sync_turso_replica(direction: Literal["pull", "push"] = "push") -> bool:
    """Synchronize the local embedded replica with Turso.

    A local commit is never reported as successful to application code until its
    push completes. Pulls are used at startup and periodically so changes made by
    another legitimate Turso client become visible on this Render instance.
    """
    if not settings.turso_enabled:
        return False
    async with engine.connect() as connection:
        driver = await _replica_driver(connection)
        result = await getattr(driver, direction)()
        return bool(result) if direction == "pull" else True


class ReplicatingAsyncSession(AsyncSession):
    async def commit(self) -> None:
        await super().commit()
        if settings.turso_enabled:
            await sync_turso_replica("push")


SessionLocal = async_sessionmaker(engine, class_=ReplicatingAsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_models() -> None:
    """Dev/test convenience. Production uses Alembic."""
    import app.models  # noqa: F401  (register mappers)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if settings.turso_enabled:
        await sync_turso_replica("push")
