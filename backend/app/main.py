"""A.R.M.X AI - FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api import admin, assistant, auth, devices, misc
from app.core.config import settings
from app.core.db import SessionLocal, init_models
from app.models import ToolDefinition
from app.registry import registry
from app.security import GatewayError

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
)
log = logging.getLogger("armx")


async def sync_tool_definitions() -> None:
    """Mirror the code registry into the DB so admins can toggle tools."""
    async with SessionLocal() as db:
        existing = {
            d.name: d for d in (await db.execute(select(ToolDefinition))).scalars().all()
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    registry.load()
    log.info("Loaded %s tools", len(registry.all()))
    if settings.AUTO_CREATE_TABLES:
        await init_models()
    try:
        await sync_tool_definitions()
    except Exception as exc:  # pragma: no cover - e.g. migrations not applied yet
        log.warning("Could not sync tool definitions: %s", exc)

    if settings.LLM_PROVIDER in ("claude", "openai") and settings.ENV != "test":
        from app.llm.factory import provider_status

        status = provider_status()
        if not status["live"]:
            log.warning(
                "LLM_PROVIDER=%s but no usable key was found - falling back to the offline planner.",
                settings.LLM_PROVIDER,
            )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.APP_NAME} API",
        version="3.0.0",
        description=(
            "Claude-powered assistant platform. The model is an untrusted planner: it may request "
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
        allow_headers=["Authorization", "Content-Type", "X-Device-Id", "X-Device-Token"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=(self)")
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.exception_handler(GatewayError)
    async def gateway_error_handler(_request: Request, exc: GatewayError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.payload())

    app.include_router(auth.router, prefix=settings.API_PREFIX)
    app.include_router(assistant.router, prefix=settings.API_PREFIX)
    app.include_router(devices.router, prefix=settings.API_PREFIX)
    app.include_router(admin.router, prefix=settings.API_PREFIX)
    app.include_router(misc.router, prefix=settings.API_PREFIX)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": settings.APP_NAME, "docs": "/docs", "health": f"{settings.API_PREFIX}/health"}

    return app


app = create_app()
