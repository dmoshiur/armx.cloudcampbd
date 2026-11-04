"""Workspace APIs: preferences, memory, automations, activity, registry, projects.

Everything here is database-backed and server-authorised. No endpoint returns a
decorative placeholder: unavailable integrations report exactly what is missing.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from html import escape
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.builder import generator, lint as design_lint, preview
from app.core.config import settings
from app.core.db import as_utc, get_db
from app.core.deps import AuthContext, client_ip, get_auth_context, require_admin
from app.core.errors import api_error
from app.core.mailer import email_health
from app.integrations import github_vercel, health as integrations_health, telecom
from app.llm.factory import provider_status_async
from app.memory import CATEGORIES, content_hash, keywords, normalise, retrieve, save_memory
from app.models import (
    AuditEvent,
    AutomationRule,
    GeneratedProject,
    LLMModelConfig,
    LLMProvider,
    LLMRequestLog,
    MemoryItem,
    Message,
    ProjectVersion,
    ToolDefinition,
    User,
    UserPreference,
)
from app.registry import registry
from app.security import execute, tool_enabled

router = APIRouter(tags=["workspace"])

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "dark",
    "sidebar_collapsed": False,
    "matrix": {
        "enabled": True,
        "speed": 5,
        "density": 5,
        "opacity": 0.22,
        "respect_reduced_motion": True,
        "renderer": "auto",
    },
    "default_model": "",
    "streaming": True,
    "voice_enabled": True,
    "memory_enabled": True,
    "notifications": True,
    "privacy": {"save_explicit_instructions": True},
}


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if key not in DEFAULT_SETTINGS:
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _sanitise_settings(raw: dict[str, Any]) -> dict[str, Any]:
    merged = _merge(DEFAULT_SETTINGS, raw)
    merged["theme"] = "light" if merged.get("theme") == "light" else "dark"
    merged["sidebar_collapsed"] = bool(merged.get("sidebar_collapsed"))
    matrix = merged["matrix"]
    matrix["enabled"] = bool(matrix.get("enabled"))
    matrix["speed"] = max(1, min(10, int(matrix.get("speed", 5))))
    matrix["density"] = max(1, min(10, int(matrix.get("density", 5))))
    matrix["opacity"] = max(0.0, min(0.6, float(matrix.get("opacity", 0.22))))
    matrix["respect_reduced_motion"] = bool(matrix.get("respect_reduced_motion", True))
    matrix["renderer"] = matrix.get("renderer") if matrix.get("renderer") in {"auto", "pty", "port"} else "auto"
    merged["default_model"] = str(merged.get("default_model") or "")[:160]
    for flag in ("streaming", "voice_enabled", "memory_enabled", "notifications"):
        merged[flag] = bool(merged.get(flag, True))
    return merged


async def _preferences(db: AsyncSession, user_id: str) -> tuple[UserPreference, dict[str, Any]]:
    row = (
        await db.execute(select(UserPreference).where(UserPreference.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = UserPreference(user_id=user_id, settings=json.dumps(DEFAULT_SETTINGS))
        db.add(row)
        await db.commit()
        await db.refresh(row)
    try:
        current = _sanitise_settings(json.loads(row.settings or "{}"))
    except json.JSONDecodeError:
        current = dict(DEFAULT_SETTINGS)
    return row, current


# ---------------------------------------------------------------------------
# preferences (server-side, not localStorage)
# ---------------------------------------------------------------------------
class PreferencesPatch(BaseModel):
    settings: dict[str, Any]


@router.get("/preferences")
async def get_preferences(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    _row, current = await _preferences(db, ctx.user.id)
    return {"settings": current, "defaults": DEFAULT_SETTINGS}


@router.patch("/preferences")
async def patch_preferences(
    payload: PreferencesPatch,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row, current = await _preferences(db, ctx.user.id)
    updated = _sanitise_settings(_merge(current, payload.settings))
    row.settings = json.dumps(updated)
    await db.commit()
    return {"settings": updated}


# ---------------------------------------------------------------------------
# long-term memory
# ---------------------------------------------------------------------------
class MemoryCreate(BaseModel):
    content: str = Field(min_length=8, max_length=4000)
    category: str = Field(default="explicit_instruction")
    importance: int = Field(default=3, ge=1, le=5)
    pinned: bool = False


class MemoryPatch(BaseModel):
    content: str | None = Field(default=None, min_length=8, max_length=4000)
    category: str | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    pinned: bool | None = None
    active: bool | None = None


class MemorySearch(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=6, ge=1, le=20)


def _memory_out(row: MemoryItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "category": row.category,
        "content": row.content,
        "source": row.source,
        "source_conversation_id": row.source_conversation_id,
        "importance": row.importance,
        "keywords": json.loads(row.keywords or "[]"),
        "use_count": row.use_count,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "active": row.active,
        "pinned": row.pinned,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@router.get("/memory")
async def list_memory(
    include_inactive: bool = False,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(MemoryItem).where(MemoryItem.user_id == ctx.user.id)
    if not include_inactive:
        stmt = stmt.where(MemoryItem.active.is_(True))
    rows = (await db.execute(stmt.order_by(MemoryItem.pinned.desc(), MemoryItem.updated_at.desc()))).scalars().all()
    return {"items": [_memory_out(r) for r in rows], "categories": list(CATEGORIES)}


@router.post("/memory", status_code=201)
async def create_memory(
    payload: MemoryCreate,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    category = payload.category if payload.category in CATEGORIES else "explicit_instruction"
    row, created = await save_memory(
        db,
        user_id=ctx.user.id,
        content=payload.content,
        category=category,
        source="user",
        importance=payload.importance,
    )
    row.pinned = payload.pinned
    await db.commit()
    await audit(
        db,
        action="memory.created" if created else "memory.deduplicated",
        actor=ctx.user,
        status="ok",
        detail={"memory_id": row.id, "category": category},
    )
    return {**_memory_out(row), "created": created}


@router.post("/memory/search")
async def search_memory(
    payload: MemorySearch,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = await retrieve(db, user_id=ctx.user.id, query=payload.query, limit=payload.limit, commit=True)
    terms = set(keywords(payload.query))
    return {
        "query": payload.query,
        "items": [
            {
                **_memory_out(row),
                "score": round(
                    len(terms & set(json.loads(row.keywords or "[]"))) / max(1, len(terms))
                    + row.importance / 10,
                    3,
                ),
            }
            for row in rows
        ],
    }


@router.post("/memory/capture/{message_id}", status_code=201)
async def capture_message_memory(
    message_id: str,
    payload: MemoryPatch,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """User-controlled: save one specific chat message as structured memory."""
    from app.models import Conversation

    message = await db.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    convo = await db.get(Conversation, message.conversation_id)
    if convo is None or convo.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Message not found")
    category = payload.category if payload.category in CATEGORIES else "knowledge_summary"
    row, created = await save_memory(
        db,
        user_id=ctx.user.id,
        content=payload.content or message.content,
        category=category,
        source="captured_message",
        conversation_id=convo.id,
        importance=payload.importance or 3,
    )
    await audit(
        db,
        action="memory.captured",
        actor=ctx.user,
        status="ok",
        detail={"message_id": message_id, "memory_id": row.id},
    )
    return {**_memory_out(row), "created": created}


@router.patch("/memory/{memory_id}")
async def patch_memory(
    memory_id: str,
    payload: MemoryPatch,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(MemoryItem, memory_id)
    if row is None or row.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Memory not found")
    if payload.content is not None:
        row.content = normalise(payload.content)
        row.content_hash = content_hash(row.category, row.content)
        row.keywords = json.dumps(keywords(row.content))
    if payload.category in CATEGORIES:
        row.category = payload.category
    if payload.importance is not None:
        row.importance = payload.importance
    if payload.pinned is not None:
        row.pinned = payload.pinned
    if payload.active is not None:
        row.active = payload.active
    await db.commit()
    return _memory_out(row)


@router.delete("/memory/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(MemoryItem, memory_id)
    if row is None or row.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Memory not found")
    await db.delete(row)
    await db.commit()
    await audit(
        db,
        action="memory.deleted",
        actor=ctx.user,
        status="ok",
        detail={"memory_id": memory_id},
    )
    return None


# ---------------------------------------------------------------------------
# automations
# ---------------------------------------------------------------------------
TRIGGERS = re.compile(r"^(manual|time:([01]\d|2[0-3]):[0-5]\d|event:device_offline)$")
ACTIONS = {"alarm", "health_check", "notify"}


class AutomationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    trigger: str = Field(default="manual", max_length=200)
    action: str = Field(default="health_check", max_length=200)
    enabled: bool = True


class AutomationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    trigger: str | None = Field(default=None, max_length=200)
    action: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


def _automation_out(row: AutomationRule) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "trigger": row.trigger,
        "action": row.action,
        "enabled": row.enabled,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


async def _owned_automation(db: AsyncSession, user_id: str, rule_id: str) -> AutomationRule:
    row = await db.get(AutomationRule, rule_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Automation not found")
    return row


@router.get("/automations")
async def list_automations(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(AutomationRule)
            .where(AutomationRule.user_id == ctx.user.id)
            .order_by(AutomationRule.created_at.desc())
        )
    ).scalars().all()
    return [_automation_out(r) for r in rows]


@router.post("/automations", status_code=201)
async def create_automation(
    payload: AutomationCreate,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not TRIGGERS.match(payload.trigger) or payload.action not in ACTIONS:
        raise HTTPException(
            status_code=400,
            detail="Use trigger manual | time:HH:MM | event:device_offline and action alarm | health_check | notify",
        )
    row = AutomationRule(
        user_id=ctx.user.id,
        name=payload.name,
        trigger=payload.trigger,
        action=payload.action,
        enabled=payload.enabled,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _automation_out(row)


@router.patch("/automations/{rule_id}")
async def patch_automation(
    rule_id: str,
    payload: AutomationPatch,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await _owned_automation(db, ctx.user.id, rule_id)
    if payload.trigger is not None and not TRIGGERS.match(payload.trigger):
        raise HTTPException(status_code=400, detail="Invalid trigger")
    if payload.action is not None and payload.action not in ACTIONS:
        raise HTTPException(status_code=400, detail="Invalid action")
    for field in ("name", "trigger", "action", "enabled"):
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, value)
    await db.commit()
    return _automation_out(row)


@router.delete("/automations/{rule_id}", status_code=204)
async def delete_automation(
    rule_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    row = await _owned_automation(db, ctx.user.id, rule_id)
    await db.delete(row)
    await db.commit()
    return None


@router.post("/automations/{rule_id}/run")
async def run_automation(
    rule_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Execute only allowlisted actions. Never run an arbitrary command."""
    rule = await _owned_automation(db, ctx.user.id, rule_id)
    if rule.action == "health_check":
        try:
            result = await execute(
                db,
                user=ctx.user,
                session_id=ctx.session.id,
                tool_name="health_status",
                args={},
                ip_address=client_ip(request),
            )
            detail = result.to_payload()
            ok, message = result.ok, result.message or result.error or "Health check completed"
        except Exception as exc:
            ok, message, detail = False, f"Health check was blocked: {exc}", {"error": str(exc)[:300]}
    elif rule.action == "alarm":
        device = await telecom.pick_device(db, ctx.user.id)
        if device is None:
            ok, message, detail = False, "No active paired device. Nothing was queued.", {"device": None}
        else:
            now = datetime.now().strftime("%H:%M")
            command = await telecom.queue_command(
                db,
                user_id=ctx.user.id,
                device=device,
                command="set_alarm",
                payload={"time": now, "label": rule.name},
            )
            ok, message, detail = True, f"Queued a visible alarm command for {device.name}.", {"command_id": command.id}
    else:
        ok = True
        message = "Notification recorded in the activity log; no external notification provider is configured."
        detail = {"provider": None, "configured": False}
    await audit(
        db,
        action="automation.run",
        actor=ctx.user,
        status="ok" if ok else "error",
        detail={"rule_id": rule.id, "action": rule.action, "result": detail},
        ip_address=client_ip(request),
    )
    return {"ok": ok, "message": message, "detail": detail, "rule": _automation_out(rule)}


# ---------------------------------------------------------------------------
# activity logs + usage analytics
# ---------------------------------------------------------------------------
@router.get("/activity")
async def activity(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = 0,
    source: str = Query(default="all", pattern="^(all|audit|llm)$"),
    q: str = "",
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    is_admin = ctx.user.role == "admin"
    if source in {"all", "audit"}:
        stmt = select(AuditEvent)
        if not is_admin:
            stmt = stmt.where(AuditEvent.actor_id == ctx.user.id)
        if q:
            stmt = stmt.where(AuditEvent.action.ilike(f"%{q[:100]}%"))
        rows = (await db.execute(stmt.order_by(AuditEvent.ts.desc()).limit(limit).offset(offset))).scalars().all()
        for row in rows:
            try:
                detail = json.loads(row.detail or "{}")
            except json.JSONDecodeError:
                detail = {"raw": row.detail}
            items.append(
                {
                    "id": row.id,
                    "ts": row.ts.isoformat(),
                    "source": "audit",
                    "kind": row.action,
                    "status": row.status,
                    "tool": row.tool_name,
                    "risk": row.risk_tier,
                    "actor": row.actor_email or ctx.user.email,
                    "detail": detail,
                }
            )
    if source in {"all", "llm"}:
        stmt = select(LLMRequestLog)
        if not is_admin:
            stmt = stmt.where(LLMRequestLog.user_id == ctx.user.id)
        rows = (await db.execute(stmt.order_by(LLMRequestLog.created_at.desc()).limit(limit).offset(offset))).scalars().all()
        for row in rows:
            items.append(
                {
                    "id": row.id,
                    "ts": row.created_at.isoformat(),
                    "source": "llm",
                    "kind": "llm.request",
                    "status": row.status,
                    "provider": row.provider,
                    "model": row.model,
                    "latency_ms": row.latency_ms,
                    "tokens": row.input_tokens + row.output_tokens,
                    "error_code": row.error_code,
                    "detail": {"error": row.error, "request_id": row.request_id, "streamed": row.streamed},
                }
            )
    items.sort(key=lambda item: item["ts"], reverse=True)
    return {"items": items[:limit], "total": len(items), "viewer_role": ctx.user.role}


@router.get("/analytics/usage")
async def usage_analytics(
    days: int = Query(default=7, ge=1, le=90),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = select(LLMRequestLog).where(LLMRequestLog.created_at >= since)
    if ctx.user.role != "admin":
        stmt = stmt.where(LLMRequestLog.user_id == ctx.user.id)
    rows = (await db.execute(stmt)).scalars().all()
    by_model: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row.provider}/{row.model}"
        entry = by_model.setdefault(
            key, {"provider": row.provider, "model": row.model, "requests": 0, "errors": 0, "tokens": 0, "latency_ms": 0}
        )
        entry["requests"] += 1
        entry["errors"] += 1 if row.status == "error" else 0
        entry["tokens"] += row.input_tokens + row.output_tokens
        entry["latency_ms"] += row.latency_ms
    for entry in by_model.values():
        entry["avg_latency_ms"] = round(entry.pop("latency_ms") / max(1, entry["requests"]))
    return {
        "days": days,
        "total_requests": len(rows),
        "total_tokens": sum(r.input_tokens + r.output_tokens for r in rows),
        "error_rate": round(sum(1 for r in rows if r.status == "error") / max(1, len(rows)), 3),
        "models": sorted(by_model.values(), key=lambda x: -x["requests"]),
    }


# ---------------------------------------------------------------------------
# tool registry (real input/output schemas and permissions)
# ---------------------------------------------------------------------------
@router.get("/tools/registry")
async def tool_registry(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    definitions = {
        row.name: row
        for row in (await db.execute(select(ToolDefinition))).scalars().all()
    }
    items = []
    for spec in registry.all():
        allowed, reason = await tool_enabled(db, spec, ctx.user)
        items.append(
            {
                "id": spec.name,
                "name": spec.name,
                "description": spec.description,
                "category": spec.category,
                "risk": spec.risk.value,
                "permissions": list(spec.scopes),
                "input_schema": spec.json_schema(),
                "output_schema": spec.output_schema(),
                "requires_approval": spec.confirm or spec.risk.needs_approval,
                "timeout_seconds": spec.timeout_seconds,
                "rate_limit_per_minute": spec.rate_limit_per_minute,
                "dry_run_supported": spec.dry_run_supported,
                "enabled": allowed,
                "reason": reason,
                "status": definitions[spec.name].status if spec.name in definitions and hasattr(definitions[spec.name], "status") else ("enabled" if allowed else "disabled"),
            }
        )
    return {"items": items, "total": len(items), "kill_switch_safe": ["health_status"]}


# ---------------------------------------------------------------------------
# generated projects: files, edit, versions, download, deploy status
# ---------------------------------------------------------------------------
class FileEdit(BaseModel):
    content: str = Field(max_length=320_000)


class VersionNote(BaseModel):
    note: str = Field(default="", max_length=300)


class GenerateProjectRequest(BaseModel):
    prompt: str = Field(min_length=10, max_length=4000)
    name: str = Field(default="", max_length=60)


class RegenerateComponentRequest(BaseModel):
    component: str = Field(pattern="^(hero|features|pricing|contact|styles)$")
    prompt: str = Field(min_length=4, max_length=1000)


async def _owned_project(db: AsyncSession, user_id: str, project_id: str) -> GeneratedProject:
    project = await db.get(GeneratedProject, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _snapshot(db: AsyncSession, project: GeneratedProject, user_id: str, note: str) -> ProjectVersion:
    count = int(
        (
            await db.execute(
                select(func.count(ProjectVersion.id)).where(ProjectVersion.project_id == project.id)
            )
        ).scalar_one()
    )
    version = ProjectVersion(
        project_id=project.id,
        version=count + 1,
        files_json=project.files,
        note=note[:300],
        created_by=user_id,
    )
    db.add(version)
    await db.flush()
    return version


@router.post("/projects/generate", status_code=201)
async def generate_project(
    payload: GenerateProjectRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate real, sandboxed HTML/CSS/JS files from a direct user action."""
    name = payload.name.strip() or re.sub(r"\s+", " ", payload.prompt.strip())[:40]
    slug = generator.slugify(name)
    result = await generator.generate(payload.prompt, name, db)
    files = generator.sanitise_files(result.files)
    if not files:
        raise HTTPException(status_code=422, detail="The generator produced no safe files.")
    files_json = json.dumps(files)
    lint_json = json.dumps(result.lint.as_dict())
    existing = (
        await db.execute(
            select(GeneratedProject)
            .where(GeneratedProject.user_id == ctx.user.id, GeneratedProject.slug == slug)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is None:
        project = GeneratedProject(
            user_id=ctx.user.id,
            name=name,
            slug=slug,
            description=payload.prompt[:2000],
            files=files_json,
            lint_report=lint_json,
            lint_status="pass" if result.lint.ok else "fail",
            status="preview",
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
    else:
        project = existing
        await _snapshot(db, project, ctx.user.id, f"Before regenerating from brief: {payload.prompt[:80]}")
        project.files = files_json
        project.lint_report = lint_json
        project.lint_status = "pass" if result.lint.ok else "fail"
        project.description = payload.prompt[:2000]
        project.status = "preview"
        await db.commit()
    await _snapshot(db, project, ctx.user.id, f"Generated {len(files)} files ({result.mode} mode)")
    await db.commit()
    generator.write_project(ctx.user.id, project.slug, files)
    token = preview.issue(project.id)
    await audit(
        db,
        action="builder.generated",
        actor=ctx.user,
        status="ok",
        target=project.id,
        detail={"mode": result.mode, "files": len(files), "lint_ok": result.lint.ok},
    )
    return {
        "id": project.id,
        "name": project.name,
        "slug": project.slug,
        "mode": result.mode,
        "summary": result.summary,
        "status": project.status,
        "files": sorted(files),
        "lint": result.lint.as_dict(),
        "preview_url": f"/api/preview/{project.id}/index.html?t={token}",
        "preview_token": token,
        "deploy_status": project.deploy_status or "not_started",
    }


@router.post("/projects/{project_id}/regenerate-component")
async def regenerate_component(
    project_id: str,
    payload: RegenerateComponentRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Replace one bounded, escaped component block; never execute model output."""
    project = await _owned_project(db, ctx.user.id, project_id)
    files = generator.sanitise_files(json.loads(project.files or "{}"))
    if "index.html" not in files:
        raise HTTPException(status_code=422, detail="This project has no index.html to regenerate")
    await _snapshot(db, project, ctx.user.id, f"Before regenerating {payload.component}")
    brief = escape(payload.prompt.strip())
    component = payload.component
    start = f"<!-- armx:regenerated:{component} -->"
    end = f"<!-- /armx:regenerated:{component} -->"
    pattern = re.compile(re.escape(start) + r"[\s\S]*?" + re.escape(end))

    if component == "styles":
        css = pattern.sub("", files.get("styles.css", ""))
        css += (
            f"\n/* armx:regenerated:styles */\n"
            f"/* Brief: {brief[:300]} */\n"
            ":root { --armx-regenerated-accent: #00ff41; }\n"
            ".armx-regenerated { border-color: var(--armx-regenerated-accent); }\n"
            f"/* /armx:regenerated:styles */\n"
        )
        files["styles.css"] = css[:320_000]
    else:
        page = pattern.sub("", files["index.html"])
        block = (
            f"{start}\n"
            f'<section id="armx-{component}" aria-label="Regenerated {escape(component)}" '
            'class="mx-auto max-w-[1200px] px-6 py-16 border-t border-white/10">\n'
            f'  <p class="text-xs font-semibold uppercase tracking-[0.2em] text-accent">Regenerated {escape(component)}</p>\n'
            f'  <h2 class="mt-3 text-3xl font-bold text-fog md:text-4xl">{brief[:140]}</h2>\n'
            f'  <p class="mt-4 max-w-2xl text-base leading-7 text-fog/70">{brief[:400]}</p>\n'
            "</section>\n"
            f"{end}"
        )
        page = page.replace("</main>", f"{block}\n</main>", 1)
        if start not in page:
            page = page.replace("</body>", f"{block}\n</body>", 1)
        files["index.html"] = page[:320_000]

    files = generator.sanitise_files(files)
    report = design_lint.lint_project(files)
    project.files = json.dumps(files)
    project.lint_report = json.dumps(report.as_dict())
    project.lint_status = "pass" if report.ok else "fail"
    project.status = "preview"
    await db.commit()
    generator.write_project(ctx.user.id, project.slug, files)
    token = preview.issue(project.id)
    await audit(
        db,
        action="builder.component_regenerated",
        actor=ctx.user,
        status="ok",
        target=project.id,
        detail={"component": component, "lint_ok": report.ok},
    )
    return {
        "component": component,
        "files": sorted(files),
        "lint": report.as_dict(),
        "preview_url": f"/api/preview/{project.id}/index.html?t={token}",
    }


@router.get("/projects/{project_id}/files")
async def project_files(
    project_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await _owned_project(db, ctx.user.id, project_id)
    files = json.loads(project.files or "{}")
    return {"files": files, "count": len(files), "status": project.status}


@router.put("/projects/{project_id}/file/{path:path}")
async def edit_project_file(
    project_id: str,
    path: str,
    payload: FileEdit,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await _owned_project(db, ctx.user.id, project_id)
    if not generator._safe_path(path):
        raise HTTPException(status_code=400, detail="Unsafe project path")
    files = generator.sanitise_files(json.loads(project.files or "{}"))
    if path not in files:
        raise HTTPException(status_code=404, detail="File not found")
    await _snapshot(db, project, ctx.user.id, f"Before editing {path}")
    files[path] = payload.content
    report = design_lint.lint_project(files)
    project.files = json.dumps(files)
    project.lint_report = json.dumps(report.as_dict())
    project.lint_status = "pass" if report.ok else "fail"
    await db.commit()
    generator.write_project(ctx.user.id, project.slug, files)
    return {"path": path, "lint": report.as_dict(), "bytes": len(payload.content)}


@router.get("/projects/{project_id}/versions")
async def project_versions(
    project_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    await _owned_project(db, ctx.user.id, project_id)
    rows = (
        await db.execute(
            select(ProjectVersion)
            .where(ProjectVersion.project_id == project_id)
            .order_by(ProjectVersion.version.desc())
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "version": row.version,
            "note": row.note,
            "files": sorted(json.loads(row.files_json or "{}").keys()),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/projects/{project_id}/versions", status_code=201)
async def create_project_version(
    project_id: str,
    payload: VersionNote,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await _owned_project(db, ctx.user.id, project_id)
    row = await _snapshot(db, project, ctx.user.id, payload.note or "Manual snapshot")
    await db.commit()
    return {"id": row.id, "version": row.version, "note": row.note}


@router.post("/projects/{project_id}/versions/{version}/restore")
async def restore_project_version(
    project_id: str,
    version: int,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await _owned_project(db, ctx.user.id, project_id)
    row = (
        await db.execute(
            select(ProjectVersion).where(
                ProjectVersion.project_id == project_id, ProjectVersion.version == version
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found")
    await _snapshot(db, project, ctx.user.id, f"Before restoring version {version}")
    files = generator.sanitise_files(json.loads(row.files_json or "{}"))
    report = design_lint.lint_project(files)
    project.files = json.dumps(files)
    project.lint_report = json.dumps(report.as_dict())
    project.lint_status = "pass" if report.ok else "fail"
    await db.commit()
    generator.write_project(ctx.user.id, project.slug, files)
    return {"restored": version, "files": sorted(files), "lint": report.as_dict()}


@router.get("/projects/{project_id}/download")
async def download_project(
    project_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    project = await _owned_project(db, ctx.user.id, project_id)
    files = generator.sanitise_files(json.loads(project.files or "{}"))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{project.slug}.zip"'},
    )


@router.get("/projects/{project_id}/deploy-status")
async def deploy_status(
    project_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Only a provider API response can set ``confirmed: true``."""
    project = await _owned_project(db, ctx.user.id, project_id)
    configured = bool(settings.VERCEL_TOKEN and settings.GITHUB_TOKEN and settings.PIPELINE_MODE == "live")
    base = {
        "project_id": project.id,
        "local_status": project.deploy_status or "not_started",
        "provider": project.deploy_provider or "none",
        "configured": configured,
        "simulated": project.simulated,
        "deployment_id": project.deployment_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if not project.deployment_id or not configured:
        return {
            **base,
            "confirmed": False,
            "state": "not_configured",
            "url": "",
            "detail": (
                "No deployment provider has confirmed a deployment for this project. "
                "Set PIPELINE_MODE=live, GITHUB_TOKEN, VERCEL_TOKEN and GITHUB_ALLOWED_TARGETS, "
                "then approve a new deployment in the assistant."
            ),
        }
    state = await github_vercel.deployment_state(project.deployment_id)
    return {**base, **state}


# ---------------------------------------------------------------------------
# health / system
# ---------------------------------------------------------------------------
@router.get("/models")
async def available_models(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Enabled model routes for the model picker. Never returns credentials."""
    rows = (
        await db.execute(
            select(LLMModelConfig, LLMProvider)
            .join(LLMProvider, LLMProvider.id == LLMModelConfig.provider_id)
            .where(LLMModelConfig.enabled.is_(True), LLMProvider.enabled.is_(True))
            .order_by(LLMModelConfig.priority, LLMModelConfig.model_id)
        )
    ).all()
    return {
        "items": [
            {
                "id": model.model_id,
                "display_name": model.display_name or model.model_id,
                "provider": provider.name,
                "provider_display_name": provider.display_name,
                "status": model.status,
                "last_error": model.last_error,
                "supports_tools": model.supports_tools,
                "max_tokens": model.max_tokens,
            }
            for model, provider in rows
        ],
        "user_role": ctx.user.role,
    }


@router.get("/health/providers")
async def provider_health(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    status = await provider_status_async(db)
    stmt = select(LLMRequestLog).order_by(LLMRequestLog.created_at.desc()).limit(20)
    if ctx.user.role != "admin":
        stmt = stmt.where(LLMRequestLog.user_id == ctx.user.id)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        **status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "recent_attempts": [
            {
                "provider": r.provider,
                "model": r.model,
                "status": r.status,
                "error_code": r.error_code,
                "latency_ms": r.latency_ms,
                "tokens": r.input_tokens + r.output_tokens,
                "streamed": r.streamed,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "integrations": integrations_health.snapshot(),
        "email": await email_health(db),
    }


@router.get("/health/system")
async def system_health(
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    db_ok = True
    migration = "unknown"
    try:
        await db.execute(text("SELECT 1"))
        row = (await db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))).first()
        migration = row[0] if row else "create_all (development)"
    except Exception as exc:
        db_ok = False
        migration = f"error: {exc}"[:200]
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    errors = int(
        (
            await db.execute(
                select(func.count(LLMRequestLog.id)).where(
                    LLMRequestLog.status == "error", LLMRequestLog.created_at >= since
                )
            )
        ).scalar_one()
    )
    return {
        "database": "ok" if db_ok else "error",
        "migration": migration,
        "worker": "in-process (FastAPI lifespan)",
        "background_jobs": ["turso_replica_sync", "housekeeping", "scheduled_automations"],
        "provider_errors_24h": errors,
        "pipeline_mode": settings.PIPELINE_MODE,
        "matrix_pty": "cmatrix binary managed by /api/matrix/status",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
