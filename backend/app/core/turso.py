"""Async SQLAlchemy dialect and replica controls for Turso.

pyturso ships an async local dialect and an async embedded-replica driver, but
not a combined SQLAlchemy dialect yet. This small bridge composes those public
interfaces: SQLAlchemy talks to the local replica through ``turso.aio.sync``;
commits are explicitly pushed to Turso by :mod:`app.core.db`.
"""
from __future__ import annotations

from sqlalchemy.dialects import registry
from turso.sqlalchemy.dialect import AioTursoDialect, AsyncAdapt_turso_dbapi


class AioTursoSyncDialect(AioTursoDialect):
    """SQLAlchemy asyncio dialect backed by a Turso embedded replica."""

    driver = "aioturso_sync"
    supports_statement_cache = True

    @classmethod
    def import_dbapi(cls):
        import turso
        import turso.aio.sync

        return AsyncAdapt_turso_dbapi(turso.aio.sync, turso)


_registered = False


def register_turso_dialect() -> None:
    """Register once without requiring a package-level entry point."""
    global _registered
    if _registered:
        return
    registry.register(
        "sqlite.aioturso_sync",
        "app.core.turso",
        "AioTursoSyncDialect",
    )
    _registered = True
