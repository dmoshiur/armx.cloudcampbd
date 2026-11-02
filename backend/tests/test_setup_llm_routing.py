from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.net import UnsafeProviderURL, validate_provider_url
from app.core.secrets import decrypt_secret, encrypt_secret, secret_hint
from app.llm.base import FinishReason, LLMMessage, LLMResponse
from app.llm.router import RoutingAdapter, seed_environment_providers
from app.models import AuditEvent, LLMModelConfig, LLMProvider, User


async def test_protected_setup_is_one_shot_and_audited(client, db, monkeypatch):
    token = "setup-token-with-at-least-thirty-two-random-characters"
    monkeypatch.setattr(settings, "INITIAL_SETUP_TOKEN", token)

    denied = await client.post(
        "/api/setup/complete",
        json={
            "setup_token": "wrong-token-that-is-still-at-least-thirty-two-chars",
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": "VeryStrong!Pass1",
        },
    )
    assert denied.status_code == 403

    created = await client.post(
        "/api/setup/complete",
        json={
            "setup_token": token,
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": "VeryStrong!Pass1",
        },
    )
    assert created.status_code == 201
    assert created.json()["next"] == "/login"
    assert "token" not in created.text.lower()

    duplicate = await client.post(
        "/api/setup/complete",
        json={
            "setup_token": token,
            "email": "second@example.com",
            "display_name": "Second",
            "password": "VeryStrong!Pass2",
        },
    )
    assert duplicate.status_code == 409

    owner = (await db.execute(select(User).where(User.email == "owner@example.com"))).scalar_one()
    assert owner.role == "admin"
    actions = (await db.execute(select(AuditEvent.action).order_by(AuditEvent.id))).scalars().all()
    assert "setup.denied" in actions
    assert "setup.completed" in actions


@pytest.mark.parametrize(
    "url",
    ["http://api.example.com/v1", "https://localhost/v1", "https://127.0.0.1/v1", "https://169.254.169.254/latest"],
)
async def test_provider_url_rejects_insecure_and_private_destinations(url):
    with pytest.raises(UnsafeProviderURL):
        await validate_provider_url(url, resolve=False)


def test_provider_secrets_encrypt_and_redact():
    ciphertext = encrypt_secret("gsk_test-secret-value")
    assert "gsk_test-secret-value" not in ciphertext
    assert decrypt_secret(ciphertext) == "gsk_test-secret-value"
    assert secret_hint("gsk_test-secret-value") == "••••alue"


async def test_environment_groq_route_is_encrypted_and_tracks_model_changes(db, monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_environment-secret")
    monkeypatch.setattr(settings, "GROQ_MODEL", "llama-primary")
    await seed_environment_providers(db)

    provider = (await db.execute(select(LLMProvider).where(LLMProvider.name == "groq"))).scalar_one()
    assert provider.source == "environment"
    assert "gsk_environment-secret" not in provider.api_key_encrypted
    assert decrypt_secret(provider.api_key_encrypted) == "gsk_environment-secret"

    monkeypatch.setattr(settings, "GROQ_MODEL", "llama-replacement")
    await seed_environment_providers(db)
    models = (
        await db.execute(select(LLMModelConfig).where(LLMModelConfig.provider_id == provider.id))
    ).scalars().all()
    assert {model.model_id for model in models if model.enabled} == {"llama-replacement"}


async def test_admin_provider_and_model_crud_never_returns_secret(
    client, admin_headers, monkeypatch
):
    async def safe_url(value: str, *, resolve: bool = True) -> str:
        return value.rstrip("/")

    monkeypatch.setattr("app.api.llm_admin.validate_provider_url", safe_url)
    secret = "gsk_this-must-never-be-returned"
    provider = await client.post(
        "/api/admin/llm/providers",
        headers=admin_headers,
        json={
            "name": "groq-test",
            "display_name": "Groq test",
            "kind": "openai_compatible",
            "base_url": "https://api.groq.com/openai/v1",
            "api_key": secret,
        },
    )
    assert provider.status_code == 201, provider.text
    assert secret not in provider.text
    provider_id = provider.json()["id"]

    model = await client.post(
        "/api/admin/llm/models",
        headers=admin_headers,
        json={
            "provider_id": provider_id,
            "model_id": "llama-3.3-70b-versatile",
            "priority": 10,
            "weight": 100,
        },
    )
    assert model.status_code == 201, model.text
    model_pk = model.json()["id"]

    listing = await client.get("/api/admin/llm", headers=admin_headers)
    assert listing.status_code == 200
    assert secret not in listing.text
    assert listing.json()["providers"][0]["models"][0]["model_id"] == "llama-3.3-70b-versatile"

    assert (await client.delete(f"/api/admin/llm/models/{model_pk}", headers=admin_headers)).status_code == 204
    assert (await client.delete(f"/api/admin/llm/providers/{provider_id}", headers=admin_headers)).status_code == 204


class _FakeAdapter:
    def __init__(self, name: str, ok: bool) -> None:
        self.name = name
        self.model = name
        self.ok = ok

    async def complete(self, messages, tool_schemas):
        if self.ok:
            return LLMResponse(text="routed", finish_reason=FinishReason.STOP, model=self.model)
        return LLMResponse(
            finish_reason=FinishReason.ERROR,
            error="synthetic provider failure",
            model=self.model,
        )


async def test_router_fails_over_and_opens_circuit(db, monkeypatch):
    providers = []
    for name in ("primary", "fallback"):
        provider = LLMProvider(
            name=name,
            display_name=name.title(),
            kind="openai_compatible",
            base_url=f"https://{name}.example.com/v1",
            api_key_encrypted=encrypt_secret(f"key-{name}-12345678"),
            api_key_hint="key…5678",
            enabled=True,
        )
        db.add(provider)
        await db.flush()
        db.add(
            LLMModelConfig(
                provider_id=provider.id,
                model_id=f"model-{name}",
                display_name=name,
                enabled=True,
                priority=10 if name == "primary" else 20,
                weight=100,
                max_tokens=128,
            )
        )
        providers.append(provider)
    await db.commit()

    async def safe_url(value: str, *, resolve: bool = True) -> str:
        return value

    calls: list[str] = []

    def fake_adapter(candidate):
        calls.append(candidate.provider_name)
        return _FakeAdapter(candidate.provider_name, candidate.provider_name == "fallback")

    monkeypatch.setattr("app.llm.router.validate_provider_url", safe_url)
    monkeypatch.setattr("app.llm.router._adapter", fake_adapter)
    router = RoutingAdapter(db)

    for _ in range(settings.LLM_FAILURE_THRESHOLD + 1):
        response = await router.complete([LLMMessage(role="user", content="hello")], [])
        assert response.ok
        assert response.provider == "fallback"

    # The primary is tried until its failure threshold, then skipped while the
    # circuit cools down; the fallback remains routable.
    assert calls.count("primary") == settings.LLM_FAILURE_THRESHOLD
    assert calls.count("fallback") == settings.LLM_FAILURE_THRESHOLD + 1
    primary_model = (
        await db.execute(select(LLMModelConfig).where(LLMModelConfig.model_id == "model-primary"))
    ).scalar_one()
    await db.refresh(primary_model)
    assert primary_model.status == "circuit_open"
    assert primary_model.circuit_open_until is not None
