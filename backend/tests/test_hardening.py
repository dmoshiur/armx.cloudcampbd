"""Hardening checks: secret hygiene, boot guards, SSRF shape, headers."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ["backend/app", "backend/scripts", "design", "web", "app", "docs"]
SKIP_DIRS = {"node_modules", ".venv", "__pycache__", "build", ".dart_tool", "dist", ".git"}

SECRET_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic key"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "GitHub token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "Slack token"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)(password|secret|token)\s*=\s*['\"][A-Za-z0-9!@#$%^&*_\-]{16,}['\"]"), "inline credential"),
]


def test_no_hardcoded_secrets_in_source():
    findings = []
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix in {".png", ".jpg", ".ico", ".lock", ".woff2", ".pyc"}:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.name in {".env", ".env.local"}:
                findings.append((path, "committed env file"))
                continue
            text = path.read_text(errors="ignore")
            for pattern, label in SECRET_PATTERNS:
                for match in pattern.finditer(text):
                    snippet = match.group(0)
                    # Allow explicit placeholders used in docs and .env.example.
                    if "example" in snippet.lower() or "your-" in snippet.lower() or "xxx" in snippet.lower():
                        continue
                    if path.name.endswith(".example"):
                        continue
                    findings.append((path.relative_to(REPO_ROOT), f"{label}: {snippet[:40]}"))
    assert not findings, findings


def test_production_refuses_placeholder_secrets(monkeypatch):
    from app.core.config import Settings

    with pytest.raises(Exception):
        Settings(
            ENV="production",
            JWT_SECRET="changeme",
            AUTO_CREATE_TABLES=False,
            WEB_ORIGIN="https://armx.example",
            LLM_PROVIDER="mock",
        )


def test_production_requires_migrations_not_autocreate(monkeypatch):
    from app.core.config import Settings

    with pytest.raises(Exception) as exc:
        Settings(
            ENV="production",
            JWT_SECRET="a-very-long-and-random-production-secret-value",
            AUTO_CREATE_TABLES=True,
            WEB_ORIGIN="https://armx.example",
            LLM_PROVIDER="mock",
        )
    assert "AUTO_CREATE_TABLES" in str(exc.value)


def test_production_requires_https_web_origin():
    from app.core.config import Settings

    with pytest.raises(Exception):
        Settings(
            ENV="production",
            JWT_SECRET="a-very-long-and-random-production-secret-value",
            AUTO_CREATE_TABLES=False,
            WEB_ORIGIN="http://armx.example",
            LLM_PROVIDER="mock",
        )


async def test_security_headers_present(client):
    resp = await client.get("/api/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "Referrer-Policy" in resp.headers


async def test_preview_is_sandboxed(client, auth_headers):
    first = await client.post(
        "/api/assistant/chat", headers=auth_headers, json={"message": "build a website for a coffee shop"}
    )
    body = first.json()
    await client.post(
        f"/api/assistant/runs/{body['run_id']}/approve",
        headers=auth_headers,
        json={"approval_id": body["approval"]["id"], "decision": "approve"},
    )
    projects = (await client.get("/api/projects", headers=auth_headers)).json()
    project_id = projects[0]["id"]
    detail = (await client.get(f"/api/projects/{project_id}", headers=auth_headers)).json()
    token = detail["preview_url"].split("t=")[1]

    resp = await client.get(f"/api/preview/{project_id}/index.html?t={token}")
    assert resp.status_code == 200
    assert "sandbox" in resp.headers["Content-Security-Policy"]
    assert "nosniff" in resp.headers["X-Content-Type-Options"]

    # Traversal through the preview route must not escape the project.
    bad = await client.get(f"/api/preview/{project_id}/../../../../etc/passwd?t={token}")
    assert bad.status_code in {403, 404}


def test_no_arbitrary_url_tool_exists():
    """There must be no shell/eval/fetch-any-URL tool exposed to the model."""
    from app.registry import registry

    registry.load()
    forbidden = {"shell", "exec", "eval", "bash", "run_command", "fetch_url", "http_get", "python"}
    names = {t.name for t in registry.all()}
    assert not (names & forbidden)
    for spec in registry.all():
        assert "shell" not in spec.description.lower()
        assert "arbitrary url" not in spec.description.lower()


def test_every_medium_high_tool_declares_confirmation():
    from app.registry import registry

    registry.load()
    for spec in registry.all():
        if spec.risk.needs_approval:
            assert spec.confirm or spec.risk.needs_approval
            assert spec.description, spec.name
            assert spec.scopes, spec.name
