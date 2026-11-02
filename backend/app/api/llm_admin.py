"""Administrator-managed LLM providers, models, health and routing order."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.core.db import get_db
from app.core.deps import client_ip, require_admin
from app.core.net import UnsafeProviderURL, validate_provider_url
from app.core.secrets import SecretConfigurationError, encrypt_secret, secret_hint
from app.llm.router import probe_model, provider_status_async
from app.models import LLMModelConfig, LLMProvider, User

router = APIRouter(prefix="/admin/llm", tags=["admin", "llm"])


class ProviderCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(min_length=2, max_length=120)
    kind: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str = Field(min_length=8, max_length=1000)
    enabled: bool = True


class ProviderUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    kind: Literal["openai_compatible", "anthropic"] | None = None
    base_url: str | None = Field(default=None, min_length=8, max_length=500)
    api_key: str | None = Field(default=None, min_length=8, max_length=1000)
    enabled: bool | None = None


class ModelCreate(BaseModel):
    provider_id: str = Field(min_length=32, max_length=32)
    model_id: str = Field(min_length=2, max_length=160)
    display_name: str = Field(default="", max_length=160)
    enabled: bool = True
    priority: int = Field(default=100, ge=1, le=1000)
    weight: int = Field(default=100, ge=1, le=1000)
    supports_tools: bool = True
    max_tokens: int = Field(default=4096, ge=16, le=131072)


class ModelUpdate(BaseModel):
    model_id: str | None = Field(default=None, min_length=2, max_length=160)
    display_name: str | None = Field(default=None, max_length=160)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    weight: int | None = Field(default=None, ge=1, le=1000)
    supports_tools: bool | None = None
    max_tokens: int | None = Field(default=None, ge=16, le=131072)


def _model_payload(model: LLMModelConfig) -> dict[str, Any]:
    return {
        "id": model.id,
        "provider_id": model.provider_id,
        "model_id": model.model_id,
        "display_name": model.display_name,
        "enabled": model.enabled,
        "priority": model.priority,
        "weight": model.weight,
        "supports_tools": model.supports_tools,
        "max_tokens": model.max_tokens,
        "status": model.status,
        "consecutive_failures": model.consecutive_failures,
        "circuit_open_until": model.circuit_open_until.isoformat() if model.circuit_open_until else None,
        "last_error": model.last_error,
        "last_used_at": model.last_used_at.isoformat() if model.last_used_at else None,
        "last_success_at": model.last_success_at.isoformat() if model.last_success_at else None,
    }


@router.get("")
async def llm_configuration(
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    providers = (await db.execute(select(LLMProvider).order_by(LLMProvider.name))).scalars().all()
    models = (await db.execute(select(LLMModelConfig).order_by(LLMModelConfig.priority))).scalars().all()
    by_provider: dict[str, list[dict[str, Any]]] = {}
    for model in models:
        by_provider.setdefault(model.provider_id, []).append(_model_payload(model))
    return {
        "routing": await provider_status_async(db),
        "providers": [
            {
                "id": provider.id,
                "name": provider.name,
                "display_name": provider.display_name,
                "kind": provider.kind,
                "base_url": provider.base_url,
                "api_key_hint": provider.api_key_hint,
                "enabled": provider.enabled,
                "source": provider.source,
                "status": provider.status,
                "last_error": provider.last_error,
                "last_checked_at": provider.last_checked_at.isoformat() if provider.last_checked_at else None,
                "last_success_at": provider.last_success_at.isoformat() if provider.last_success_at else None,
                "models": by_provider.get(provider.id, []),
            }
            for provider in providers
        ],
    }


@router.post("/providers", status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: ProviderCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        base_url = await validate_provider_url(payload.base_url)
        encrypted = encrypt_secret(payload.api_key)
    except (UnsafeProviderURL, SecretConfigurationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    provider = LLMProvider(
        name=payload.name,
        display_name=payload.display_name,
        kind=payload.kind,
        base_url=base_url,
        api_key_encrypted=encrypted,
        api_key_hint=secret_hint(payload.api_key),
        enabled=payload.enabled,
        source="admin",
    )
    db.add(provider)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Provider name already exists") from exc
    await db.refresh(provider)
    await audit(
        db,
        action="admin.llm_provider_created",
        actor=admin,
        target=provider.id,
        detail={"name": provider.name, "kind": provider.kind},
        ip_address=client_ip(request),
    )
    return {"id": provider.id, "name": provider.name, "api_key_hint": provider.api_key_hint}


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: str,
    payload: ProviderUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    provider = await db.get(LLMProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    values = payload.model_dump(exclude_unset=True)
    if "base_url" in values:
        try:
            provider.base_url = await validate_provider_url(values.pop("base_url"))
        except UnsafeProviderURL as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "api_key" in values:
        key = values.pop("api_key") or ""
        try:
            provider.api_key_encrypted = encrypt_secret(key)
        except SecretConfigurationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        provider.api_key_hint = secret_hint(key)
    for name, value in values.items():
        setattr(provider, name, value)
    provider.status = "unknown"
    provider.last_error = ""
    await db.commit()
    await audit(
        db,
        action="admin.llm_provider_updated",
        actor=admin,
        target=provider.id,
        detail={"fields": sorted(payload.model_fields_set)},
        ip_address=client_ip(request),
    )
    return {"id": provider.id, "enabled": provider.enabled, "api_key_hint": provider.api_key_hint}


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    provider = await db.get(LLMProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if provider.source == "environment":
        raise HTTPException(status_code=409, detail="Remove this provider's key from Render environment variables")
    name = provider.name
    await db.delete(provider)
    await db.commit()
    await audit(
        db,
        action="admin.llm_provider_deleted",
        actor=admin,
        target=provider_id,
        detail={"name": name},
        ip_address=client_ip(request),
    )
    return Response(status_code=204)


@router.post("/models", status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: ModelCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if await db.get(LLMProvider, payload.provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    model = LLMModelConfig(
        provider_id=payload.provider_id,
        model_id=payload.model_id,
        display_name=payload.display_name or payload.model_id,
        enabled=payload.enabled,
        priority=payload.priority,
        weight=payload.weight,
        supports_tools=payload.supports_tools,
        max_tokens=payload.max_tokens,
    )
    db.add(model)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="This model already exists for the provider") from exc
    await db.refresh(model)
    await audit(
        db,
        action="admin.llm_model_created",
        actor=admin,
        target=model.id,
        detail={"model": model.model_id, "provider_id": model.provider_id},
        ip_address=client_ip(request),
    )
    return _model_payload(model)


@router.patch("/models/{model_pk}")
async def update_model(
    model_pk: str,
    payload: ModelUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    model = await db.get(LLMModelConfig, model_pk)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    for name, value in payload.model_dump(exclude_unset=True).items():
        setattr(model, name, value)
    if payload.enabled is True:
        model.circuit_open_until = None
        model.consecutive_failures = 0
        model.status = "unknown"
        model.last_error = ""
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="This model already exists for the provider") from exc
    await audit(
        db,
        action="admin.llm_model_updated",
        actor=admin,
        target=model.id,
        detail={"fields": sorted(payload.model_fields_set)},
        ip_address=client_ip(request),
    )
    return _model_payload(model)


@router.delete("/models/{model_pk}", status_code=204)
async def delete_model(
    model_pk: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    model = await db.get(LLMModelConfig, model_pk)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    model_name = model.model_id
    await db.delete(model)
    await db.commit()
    await audit(
        db,
        action="admin.llm_model_deleted",
        actor=admin,
        target=model_pk,
        detail={"model": model_name},
        ip_address=client_ip(request),
    )
    return Response(status_code=204)


@router.post("/models/{model_pk}/test")
async def test_model(
    model_pk: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        response = await probe_model(db, model_pk)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await audit(
        db,
        action="admin.llm_model_tested",
        actor=admin,
        target=model_pk,
        status="ok" if response.ok else "error",
        detail={"provider": response.provider, "model": response.model, "error": response.error[:200]},
        ip_address=client_ip(request),
    )
    return {
        "ok": response.ok,
        "provider": response.provider,
        "model": response.model,
        "error": response.error,
    }
