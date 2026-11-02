"""A.R.M.X AI - FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api import (
    admin,
    assistant,
    auth,
    device_management,
    devices,
    llm_admin,
    misc,
    setup,
    webhooks,
)
from app.audit import audit
from app.core.bootstrap import seed_initial_admin
from app.core.config import settings
from app.core.db import SessionLocal, init_models, sync_turso_replica
from app.llm.router import provider_status_async, seed_environment_providers
from app.models import ToolDefinition
from app.registry import registry
from app.security import GatewayError
from app.worker import run_worker

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
)
log = logging.getLogger("armx")


async def sync_tool_definitions() -> None:
    """Mirror the code registry into the DB so admins can toggle tools."""
    async with SessionLocal() as db:
        existing = {
            d.name: d
            for d in (await db.execute(select(ToolDefinition))).scalars().all()
        }
        for spec in registry.all():
            row = existing.get(spec.name)
            payload = spec.definition_row()
            if row is None:
                db.add(ToolDefinition(**payload))
            else:
                row.description = payload["description"]
                row.risk_tier = payload["risk_tier"]
                row.scopes = payload["scopes"]
                row.confirm_required = payload["confirm_required"]
                row.rate_limit_per_minute = payload["rate_limit_per_minute"]
                row.dry_run_supported = payload["dry_run_supported"]
        await db.commit()


async def _turso_sync_loop() -> None:
    while True:
        await asyncio.sleep(settings.TURSO_SYNC_INTERVAL_SECONDS)
        try:
            # Retry any locally durable writes first, then accept remote changes.
            await sync_turso_replica("push")
            changed = await sync_turso_replica("pull")
            if changed:
                log.info("Pulled remote Turso changes into the embedded replica")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - requires a live Turso service
            log.error(
                "Turso sync failed; locally durable writes remain queued for retry: %s",
                exc,
            )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    registry.load()
    log.info("Loaded %s tools", len(registry.all()))
    if settings.AUTO_CREATE_TABLES:
        await init_models()
    if settings.turso_enabled:
        await sync_turso_replica("push")
        await sync_turso_replica("pull")

    try:
        async with SessionLocal() as db:
            seeded_admin = await seed_initial_admin(db)
            if seeded_admin:
                await audit(
                    db,
                    action="setup.completed",
                    actor=seeded_admin,
                    target=seeded_admin.id,
                    detail={"method": "environment_seed"},
                )
                log.info(
                    "Created one-time environment superadmin %s", seeded_admin.email
                )
            seeded_routes = await seed_environment_providers(db)
            if seeded_routes:
                log.info(
                    "Seeded %s environment LLM provider/model records", seeded_routes
                )
        await sync_tool_definitions()
    except Exception as exc:  # pragma: no cover - e.g. migrations not applied yet
        if settings.ENV == "production":
            raise
        log.warning("Could not synchronize startup records: %s", exc)

    if settings.ENV != "test":
        async with SessionLocal() as db:
            status = await provider_status_async(db)
        if not status["live"]:
            log.warning(
                "No live LLM model is enabled; using the labelled offline planner"
            )

    sync_task = (
        asyncio.create_task(_turso_sync_loop()) if settings.turso_enabled else None
    )
    worker_task = asyncio.create_task(run_worker())
    try:
        yield
    finally:
        tasks = [task for task in (sync_task, worker_task) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.APP_NAME} API",
        version="3.0.0",
        description=(
            "Multi-provider assistant platform. Models are untrusted planners: they may request "
            "registered tools, but only the Security Gateway authorises and executes them."
        ),
        lifespan=lifespan,
        docs_url="/docs" if settings.ENV != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.ENV != "production" else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Device-Id",
            "X-Device-Token",
            "X-Request-ID",
        ],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # A short opaque correlation ID is safe to show in UI error messages and
        # lets operators find the exact request without exposing stack traces.
        request_id = secrets.token_hex(8)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request_id)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), camera=(), microphone=(self)"
        )
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.exception_handler(GatewayError)
    async def gateway_error_handler(
        _request: Request, exc: GatewayError
    ) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.payload())

    # Provider webhooks are public by design but authenticate every callback
    # with provider-specific challenge/signature checks.
    app.include_router(webhooks.router, prefix=settings.API_PREFIX)
    app.include_router(setup.router, prefix=settings.API_PREFIX)
    app.include_router(auth.router, prefix=settings.API_PREFIX)
    app.include_router(assistant.router, prefix=settings.API_PREFIX)
    app.include_router(devices.router, prefix=settings.API_PREFIX)
    app.include_router(device_management.router, prefix=settings.API_PREFIX)
    app.include_router(admin.router, prefix=settings.API_PREFIX)
    app.include_router(device_management.admin_router, prefix=settings.API_PREFIX)
    app.include_router(llm_admin.router, prefix=settings.API_PREFIX)
    app.include_router(misc.router, prefix=settings.API_PREFIX)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.APP_NAME,
            "docs": "/docs",
            "health": f"{settings.API_PREFIX}/health",
        }

    return app


app = create_app()
