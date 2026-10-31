"""Health, tool catalogue, integrations, media, projects, previews, messaging profiles."""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.builder import preview as preview_tokens
from app.builder.generator import workspace_for
from app.core import media
from app.core.config import settings
from app.core.db import get_db
from app.core.deps import AuthContext, get_auth_context
from app.integrations import health
from app.llm.factory import provider_status
from app.models import GeneratedProject, MessagingProfile, User
from app.registry import registry
from app.security import kill_switch_engaged

router = APIRouter(tags=["platform"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Liveness + the state of the things a stranger needs to know."""
    from sqlalchemy import text

    db_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.APP_NAME,
        "env": settings.ENV,
        "database": "ok" if db_ok else "error",
        "planner": provider_status(),
        "kill_switch": "on" if await kill_switch_engaged(db) else "off",
        "tools": len(registry.all()),
        "pipeline_mode": settings.PIPELINE_MODE,
    }


@router.get("/tools")
async def tool_catalogue(ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    from app.security import tool_enabled

    out = []
    for spec in registry.all():
        allowed, why = await tool_enabled(db, spec, ctx.user)
        out.append(
            {
                "name": spec.name,
                "description": spec.description,
                "risk": spec.risk.value,
                "category": spec.category,
                "scopes": list(spec.scopes),
                "confirm": spec.confirm or spec.risk.needs_approval,
                "dry_run_supported": spec.dry_run_supported,
                "enabled": allowed,
                "reason": why,
            }
        )
    return out


@router.get("/integrations")
async def integrations(ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return {
        "integrations": health.snapshot(),
        "kill_switch": "on" if await kill_switch_engaged(db) else "off",
        "planner": provider_status(),
    }


# --------------------------------------------------------------------------
# media
# --------------------------------------------------------------------------
@router.post("/media/upload", status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, Any]:
    content_type = (file.content_type or "").lower()
    if content_type not in media.ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Upload PNG, JPEG or WebP")
    blob = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(blob) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    try:
        record = media.save_bytes(ctx.user.id, blob, content_type, {"filename": (file.filename or "")[:120]})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"asset_id": record["asset_id"], "url": f"/api/media/{record['asset_id']}", "bytes": record["bytes"]}


@router.get("/media/{asset_id}")
async def get_media(
    asset_id: str, ctx: AuthContext = Depends(get_auth_context)
) -> Response:
    loaded = media.read(ctx.user.id, asset_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    record, blob = loaded
    return Response(content=blob, media_type=record["content_type"], headers={"Cache-Control": "private, max-age=60"})


# --------------------------------------------------------------------------
# generated projects
# --------------------------------------------------------------------------
@router.get("/projects")
async def list_projects(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(GeneratedProject)
            .where(GeneratedProject.user_id == ctx.user.id)
            .order_by(GeneratedProject.updated_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "slug": p.slug,
            "status": p.status,
            "lint_status": p.lint_status,
            "repo_url": p.repo_url,
            "repo_is_platform_owned": p.repo_is_platform_owned,
            "vercel_url": p.vercel_url,
            "deploy_status": p.deploy_status,
            "turso_db_ref": p.turso_db_ref,
            "updated_at": p.updated_at.isoformat(),
        }
        for p in rows
    ]


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str, ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    project = await db.get(GeneratedProject, project_id)
    if project is None or project.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    token = preview_tokens.issue(project.id)
    return {
        "id": project.id,
        "name": project.name,
        "slug": project.slug,
        "description": project.description,
        "status": project.status,
        "files": sorted(json.loads(project.files or "{}").keys()),
        "lint": json.loads(project.lint_report or "{}"),
        "repo_url": project.repo_url,
        "vercel_url": project.vercel_url,
        "repo_is_platform_owned": project.repo_is_platform_owned,
        "turso_db_ref": project.turso_db_ref,
        "preview_url": f"/api/preview/{project.id}/index.html?t={token}",
    }


@router.get("/projects/{project_id}/file/{path:path}")
async def get_project_file(
    project_id: str, path: str, ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> Response:
    project = await db.get(GeneratedProject, project_id)
    if project is None or project.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    files = json.loads(project.files or "{}")
    if path not in files:
        raise HTTPException(status_code=404, detail="File not found")
    media_type = mimetypes.guess_type(path)[0] or "text/plain"
    return Response(content=files[path], media_type=media_type)


# --------------------------------------------------------------------------
# preview (signed capability URL, no bearer token needed)
# --------------------------------------------------------------------------
@router.get("/preview/{project_id}/{path:path}")
async def serve_preview(project_id: str, path: str, t: str = "", db: AsyncSession = Depends(get_db)) -> Response:
    if preview_tokens.verify(t) != project_id:
        raise HTTPException(status_code=403, detail="Preview link is invalid or expired")
    project = await db.get(GeneratedProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Preview not found")
    files = json.loads(project.files or "{}")
    requested = path or "index.html"
    if requested not in files:
        # Serve the sandboxed copy if the project was materialised (static assets).
        try:
            root = workspace_for(project.user_id, project.slug) / "public"
            target = (root / requested).resolve()
            if str(target).startswith(str(root)) and target.is_file():
                return FileResponse(target)
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="File not found in preview")

    media_type = mimetypes.guess_type(requested)[0] or "text/html"
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        # Previews are untrusted generated content: isolate them from the platform origin.
        "Content-Security-Policy": "sandbox allow-scripts allow-forms allow-popups allow-same-origin",
        "X-Frame-Options": "SAMEORIGIN",
    }
    return Response(content=files[requested], media_type=media_type, headers=headers)


# --------------------------------------------------------------------------
# messaging profiles
# --------------------------------------------------------------------------
class MessagingProfileIn(BaseModel):
    channel: str = Field(default="whatsapp", pattern="^(whatsapp|messenger)$")
    contact_id: str = Field(min_length=3, max_length=40)
    display_name: str = Field(default="", max_length=120)
    personality: str = Field(default="", max_length=1000)
    auto_send: bool = False


@router.get("/messaging/profiles")
async def list_profiles(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(MessagingProfile).where(MessagingProfile.user_id == ctx.user.id).order_by(MessagingProfile.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": p.id,
            "channel": p.channel,
            "contact_id": p.contact_id,
            "display_name": p.display_name,
            "personality": p.personality,
            "auto_send": p.auto_send,
        }
        for p in rows
    ]


@router.post("/messaging/profiles", status_code=201)
async def create_profile(
    payload: MessagingProfileIn,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    existing = (
        await db.execute(
            select(MessagingProfile).where(
                MessagingProfile.user_id == ctx.user.id,
                MessagingProfile.channel == payload.channel,
                MessagingProfile.contact_id == payload.contact_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.display_name = payload.display_name or existing.display_name
        existing.personality = payload.personality
        existing.auto_send = payload.auto_send
        await db.commit()
        return {"id": existing.id, "updated": True}
    row = MessagingProfile(
        user_id=ctx.user.id,
        channel=payload.channel,
        contact_id=payload.contact_id,
        display_name=payload.display_name,
        personality=payload.personality,
        auto_send=payload.auto_send,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "updated": False}


@router.delete("/messaging/profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str, ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
):
    row = await db.get(MessagingProfile, profile_id)
    if row is None or row.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    await db.delete(row)
    await db.commit()
    return None


# --------------------------------------------------------------------------
# web-facing config
# --------------------------------------------------------------------------
@router.get("/config")
async def public_config() -> JSONResponse:
    """Non-secret capability flags so the UI can be honest about what works."""
    return JSONResponse(
        {
            "app_name": settings.APP_NAME,
            "env": settings.ENV,
            "features": {
                "google_login": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
                "email_verification_required": settings.REQUIRE_EMAIL_VERIFICATION,
                "wake_word": False,
                "background_listening": False,
                "push_to_talk": True,
                "pipeline_mode": settings.PIPELINE_MODE,
                "messaging_mode": settings.MESSAGING_MODE,
            },
            "planner": provider_status(),
        }
    )
