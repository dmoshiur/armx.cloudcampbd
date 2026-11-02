from __future__ import annotations

import hashlib
import hmac
import json

from app.core.config import settings


async def test_whatsapp_get_verification_uses_separate_verify_token(client, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_VERIFY_TOKEN", "random-webhook-challenge-token")
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", "meta-app-secret")
    monkeypatch.setattr(settings, "WHATSAPP_TOKEN", "graph-access-token-must-not-work")

    verified = await client.get(
        "/api/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "random-webhook-challenge-token",
            "hub.challenge": "847291",
        },
    )
    assert verified.status_code == 200
    assert verified.text == "847291"
    assert verified.headers["x-request-id"]

    access_token_is_not_verify_token = await client.get(
        "/api/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "graph-access-token-must-not-work",
            "hub.challenge": "847291",
        },
    )
    assert access_token_is_not_verify_token.status_code == 403


async def test_whatsapp_post_requires_exact_body_hmac(client, monkeypatch):
    app_secret = "meta-app-secret"
    monkeypatch.setattr(settings, "WHATSAPP_VERIFY_TOKEN", "verify-token")
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", app_secret)
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {"id": "wamid.1", "from": "15551234567", "type": "text"}
                            ]
                        },
                    }
                ]
            }
        ],
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()

    accepted = await client.post(
        "/api/webhooks/whatsapp",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
    )
    assert accepted.status_code == 200
    assert accepted.json() == {"status": "accepted", "messages": 1}

    tampered = await client.post(
        "/api/webhooks/whatsapp",
        content=body + b" ",
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
    )
    assert tampered.status_code == 401


async def test_whatsapp_webhook_fails_closed_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_VERIFY_TOKEN", "")
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", "")
    response = await client.post("/api/webhooks/whatsapp", content=b"{}")
    assert response.status_code == 503
