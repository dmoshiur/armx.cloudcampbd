"""Home Assistant REST integration with a strict entity allowlist.

Only entities listed in HOME_ASSISTANT_ALLOWED_ENTITIES can ever be read or
written - the LLM cannot reach an arbitrary entity even if it asks.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.integrations.base import IntegrationNotConfigured, IntegrationStatus

DOMAIN_ALLOWLIST = {"light", "switch", "sensor", "binary_sensor", "climate", "scene"}


def status() -> IntegrationStatus:
    return IntegrationStatus(
        provider="home_assistant",
        configured=bool(settings.HOME_ASSISTANT_URL and settings.HOME_ASSISTANT_TOKEN),
        detail=f"{len(settings.allowed_entities)} entities allowlisted" if settings.HOME_ASSISTANT_URL else "",
    )


def _require() -> tuple[str, dict[str, str]]:
    if not settings.HOME_ASSISTANT_URL or not settings.HOME_ASSISTANT_TOKEN:
        raise IntegrationNotConfigured(
            "home_assistant",
            "Set HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN (long-lived token) in .env.",
        )
    return (
        settings.HOME_ASSISTANT_URL.rstrip("/"),
        {"Authorization": f"Bearer {settings.HOME_ASSISTANT_TOKEN}", "Content-Type": "application/json"},
    )


def is_allowed(entity_id: str) -> bool:
    if entity_id not in settings.allowed_entities:
        return False
    domain = entity_id.split(".", 1)[0]
    return domain in DOMAIN_ALLOWLIST


async def get_state(entity_id: str) -> dict[str, Any]:
    if not is_allowed(entity_id):
        raise PermissionError(f"Entity '{entity_id}' is not in the allowlist")
    base, headers = _require()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{base}/api/states/{entity_id}", headers=headers)
    if resp.status_code == 404:
        return {"entity_id": entity_id, "state": "unavailable"}
    resp.raise_for_status()
    data = resp.json()
    return {
        "entity_id": data.get("entity_id"),
        "state": data.get("state"),
        "friendly_name": (data.get("attributes") or {}).get("friendly_name", ""),
        "brightness": (data.get("attributes") or {}).get("brightness"),
    }


async def list_allowed_states() -> list[dict[str, Any]]:
    out = []
    for entity in sorted(settings.allowed_entities):
        try:
            out.append(await get_state(entity))
        except Exception as exc:  # integration failure must not kill the request
            out.append({"entity_id": entity, "state": "error", "error": str(exc)[:120]})
    return out


async def turn_on(entity_id: str, brightness_pct: int | None = None) -> dict[str, Any]:
    if not is_allowed(entity_id):
        raise PermissionError(f"Entity '{entity_id}' is not in the allowlist")
    base, headers = _require()
    domain = entity_id.split(".", 1)[0]
    service = "turn_on" if domain in {"light", "switch"} else "turn_on"
    payload: dict[str, Any] = {"entity_id": entity_id}
    if brightness_pct is not None and domain == "light":
        payload["brightness_pct"] = max(1, min(100, brightness_pct))
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{base}/api/services/{domain}/{service}", headers=headers, json=payload)
    resp.raise_for_status()
    return {"entity_id": entity_id, "state": "on", **({"brightness_pct": payload["brightness_pct"]} if "brightness_pct" in payload else {})}


async def turn_off(entity_id: str) -> dict[str, Any]:
    if not is_allowed(entity_id):
        raise PermissionError(f"Entity '{entity_id}' is not in the allowlist")
    base, headers = _require()
    domain = entity_id.split(".", 1)[0]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{base}/api/services/{domain}/turn_off", headers=headers, json={"entity_id": entity_id}
        )
    resp.raise_for_status()
    return {"entity_id": entity_id, "state": "off"}
