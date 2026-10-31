"""Build pipeline: generation, design lint, sandbox paths, destination allowlist."""
from __future__ import annotations

import json

import pytest

from app.builder import generator, lint
from app.builder.preview import issue, verify
from app.integrations.github_vercel import DestinationDenied, deploy_project, ensure_destination_allowed, repo_slug


GOOD_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Test</title><script src="https://cdn.tailwindcss.com"></script>
<style>body{font-family:Inter,sans-serif}@media(max-width:600px){.x{display:none}}</style></head>
<body class="bg-[#0B1220] text-[#F4F6FB]"><h1 class="text-4xl">Hello</h1>
<button class="bg-[#5B8CFF] px-4 py-3">Go</button></body></html>"""

BAD_PAGE = """<html><body><h1>Lorem ipsum</h1><img src="a.png">
<button></button><p style="color:#ff00aa;background:#123456;border-color:#abcdef">x</p></body></html>"""


def test_template_output_passes_the_design_lint():
    files, _summary = generator.template_site("build a website for a coffee shop in Dhaka", "coffee")
    report = lint.lint_project(files)
    assert report.ok is True, report.as_dict()
    assert report.score == 100
    assert "index.html" in files


def test_lint_catches_design_and_accessibility_failures():
    report = lint.lint_html("bad.html", BAD_PAGE)
    rules = {f.rule for f in report.findings}
    assert report.ok is False
    assert {"doctype", "viewport", "design-system", "a11y", "placeholder-content"} & rules
    errors = [f for f in report.findings if f.severity == "error"]
    assert len(errors) >= 3


def test_lint_passes_a_clean_page():
    report = lint.lint_html("good.html", GOOD_PAGE)
    assert report.ok is True, report.as_dict()


def test_lint_flags_accent_pairing_on_one_element():
    page = GOOD_PAGE.replace(
        '</body>', '<div class="bg-[#5B8CFF] border-[#8B5CF6]">x</div></body>'
    )
    report = lint.lint_html("pair.html", page)
    assert any(f.rule == "accent-pairing" for f in report.findings)


def test_generated_files_reject_path_traversal():
    files = generator.sanitise_files(
        {"index.html": "<html></html>", "../../etc/passwd": "root:x", "/abs/path.html": "x", "a/../b": "x"}
    )
    assert set(files) == {"index.html"}


def test_sanitise_enforces_size_cap():
    big = "x" * (generator.MAX_FILE_BYTES + 1000)
    files = generator.sanitise_files({"index.html": big})
    assert len(files["index.html"]) == generator.MAX_FILE_BYTES


def test_workspace_paths_cannot_escape(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PROJECT_WORKSPACE", str(tmp_path))
    with pytest.raises(ValueError):
        generator.workspace_for("abc", "../../escape")


def test_preview_tokens_are_scoped_and_expire():
    token = issue("project-1", ttl=60)
    assert verify(token) == "project-1"
    assert verify(token + "x") is None
    assert verify(issue("project-2", ttl=60)) == "project-2"
    expired = issue("project-1", ttl=-5)
    assert verify(expired) is None


def test_repo_slug_is_unique_per_user():
    a = repo_slug("My Site", "a" * 32)
    b = repo_slug("My Site", "b" * 32)
    assert a != b
    assert a.startswith("my-site-")


def test_destination_allowlist_blocks_unknown_repos(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "GITHUB_ALLOWED_TARGETS", "armx-projects")
    monkeypatch.setattr(settings, "GITHUB_DEFAULT_ORG", "armx-projects")
    ensure_destination_allowed("armx-projects", "some-repo")
    with pytest.raises(DestinationDenied):
        ensure_destination_allowed("attacker", "some-repo")


async def test_simulated_deploy_marks_itself_simulated():
    files = {"index.html": GOOD_PAGE}
    result = await deploy_project(name="Demo", slug="demo", user_id="u" * 32, files=files)
    assert result.ok is True
    assert result.simulated is True
    assert result.url.endswith(".vercel.app")
    assert result.repo_is_platform_owned is True


async def test_deploy_requires_approval_then_goes_live(client, auth_headers):
    # Generate through the assistant (approval), then deploy (approval).
    first = await client.post(
        "/api/assistant/chat", headers=auth_headers,
        json={"message": "build a website for a coffee shop in Dhaka"},
    )
    body = first.json()
    assert body["status"] == "awaiting_approval"
    approved = await client.post(
        f"/api/assistant/runs/{body['run_id']}/approve",
        headers=auth_headers,
        json={"approval_id": body["approval"]["id"], "decision": "approve"},
    )
    assert approved.status_code == 200

    second = await client.post(
        "/api/assistant/chat", headers=auth_headers, json={"message": "deploy it to production"}
    )
    deploy = second.json()
    assert deploy["status"] == "awaiting_approval"
    assert deploy["approval"]["tool"] == "web_deploy"

    final = await client.post(
        f"/api/assistant/runs/{deploy['run_id']}/approve",
        headers=auth_headers,
        json={"approval_id": deploy["approval"]["id"], "decision": "approve"},
    )
    payload = final.json()
    assert payload["status"] == "complete"
    deploy_events = [e for e in payload["tool_events"] if e["tool"] == "web_deploy"]
    assert deploy_events and deploy_events[0]["result"]["data"]["simulated"] is True

    projects = await client.get("/api/projects", headers=auth_headers)
    assert projects.json()[0]["status"] == "deployed"


async def test_rejected_approval_executes_nothing(client, auth_headers):
    first = await client.post(
        "/api/assistant/chat", headers=auth_headers,
        json={"message": "build a website for a coffee shop in Dhaka"},
    )
    body = first.json()
    rejected = await client.post(
        f"/api/assistant/runs/{body['run_id']}/approve",
        headers=auth_headers,
        json={"approval_id": body["approval"]["id"], "decision": "reject"},
    )
    assert rejected.json()["status"] == "rejected"
    projects = await client.get("/api/projects", headers=auth_headers)
    assert projects.json() == []
