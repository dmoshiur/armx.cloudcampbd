"""WhatsApp Business API / Messenger Platform replies.

Policy encoded here:
  * Sending to a contact with ``auto_send`` enabled and a stored personality profile
    is MEDIUM risk (the gateway still asks once per action).
  * Sending to a NEW/unapproved contact is HIGH risk.
  * The platform never messages anyone the owner has not explicitly added.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.integrations.base import IntegrationNotConfigured, IntegrationStatus

GRAPH = "https://graph.facebook.com/v21.0"


def status() -> list[IntegrationStatus]:
    sim = settings.MESSAGING_MODE == "simulated"
    return [
        IntegrationStatus("whatsapp", bool(settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_ID) or sim,
                          "simulated" if sim else "live"),
        IntegrationStatus("messenger", bool(settings.MESSENGER_TOKEN and settings.MESSENGER_PAGE_ID) or sim,
                          "simulated" if sim else "live"),
    ]


async def send_whatsapp(to: str, text: str) -> dict[str, Any]:
    if settings.MESSAGING_MODE == "simulated":
        return {
            "ok": True,
            "simulated": True,
            "channel": "whatsapp",
            "to": to,
            "preview": text[:140],
            "message_id": f"sim_{abs(hash((to, text))) % 10_000_000}",
        }
    if not (settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_ID):
        raise IntegrationNotConfigured("whatsapp", "Set WHATSAPP_TOKEN and WHATSAPP_PHONE_ID.")
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    body = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text[:4000]},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(f"{GRAPH}/{settings.WHATSAPP_PHONE_ID}/messages", json=body, headers=headers)
    if resp.status_code >= 400:
        return {"ok": False, "error": f"WhatsApp {resp.status_code}: {resp.text[:200]}"}
    data = resp.json()
    messages = data.get("messages") or [{}]
    return {"ok": True, "channel": "whatsapp", "to": to, "message_id": messages[0].get("id", "")}


async def send_messenger(psid: str, text: str) -> dict[str, Any]:
    if settings.MESSAGING_MODE == "simulated":
        return {"ok": True, "simulated": True, "channel": "messenger", "to": psid, "preview": text[:140]}
    if not (settings.MESSENGER_TOKEN and settings.MESSENGER_PAGE_ID):
        raise IntegrationNotConfigured("messenger", "Set MESSENGER_TOKEN and MESSENGER_PAGE_ID.")
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{GRAPH}/{settings.MESSENGER_PAGE_ID}/messages",
            params={"access_token": settings.MESSENGER_TOKEN},
            json={"recipient": {"id": psid}, "message": {"text": text[:2000]}},
        )
    if resp.status_code >= 400:
        return {"ok": False, "error": f"Messenger {resp.status_code}: {resp.text[:200]}"}
    return {"ok": True, "channel": "messenger", "to": psid, "message_id": resp.json().get("message_id", "")}
