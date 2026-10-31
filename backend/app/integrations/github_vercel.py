"""GitHub + Vercel + Turso deploy pipeline behind per-user destination allowlists.

Two modes:
  * ``PIPELINE_MODE=live``      - real API calls with the owner's tokens.
  * ``PIPELINE_MODE=simulated`` - deterministic, clearly-labelled dry runs so the
    full flow is testable without credentials. Every response carries
    ``simulated: true`` which the UI surfaces next to the URL.

The LLM can never invent a destination: repo owners and Vercel project names must
match the allowlists below, and the repo is always derived server-side from the
project slug.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.integrations.base import IntegrationNotConfigured, IntegrationStatus

GH_API = "https://api.github.com"
VCL_API = "https://api.vercel.com"


class DestinationDenied(Exception):
    pass


def status() -> list[IntegrationStatus]:
    sim = settings.PIPELINE_MODE == "simulated"
    return [
        IntegrationStatus("github", bool(settings.GITHUB_TOKEN) or sim, "simulated" if sim else "live"),
        IntegrationStatus("vercel", bool(settings.VERCEL_TOKEN) or sim, "simulated" if sim else "live"),
        IntegrationStatus("turso", bool(settings.TURSO_API_TOKEN) or sim, "simulated" if sim else "live"),
    ]


def repo_slug(name: str, user_id: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "site"
    # Suffix keeps repos unique per user without exposing the raw user id.
    return f"{base}-{hashlib.sha256(user_id.encode()).hexdigest()[:6]}"


def vercel_project_name(slug: str) -> str:
    prefix = settings.VERCEL_ALLOWED_PROJECT_PREFIX
    name = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")[:50]
    return name if name.startswith(prefix) else f"{prefix}{name}"[:60]


def ensure_destination_allowed(owner: str, repo: str) -> None:
    """Allowlist check for the GitHub destination."""
    full = f"{owner}/{repo}".lower()
    allowed = settings.github_target_allowlist
    platform_owner = (settings.GITHUB_DEFAULT_ORG or "").lower()
    if allowed and not any(full.startswith(prefix) or full.split("/")[0] == prefix for prefix in allowed):
        raise DestinationDenied(f"Repository destination {full} is not in the allowlist")
    if not allowed and platform_owner and owner.lower() != platform_owner:
        raise DestinationDenied(
            "No GITHUB_ALLOWED_TARGETS configured: only the platform default account is permitted"
        )
    if not allowed and not platform_owner:
        raise DestinationDenied(
            "Deploy destinations are not configured (set GITHUB_ALLOWED_TARGETS or GITHUB_DEFAULT_ORG)"
        )


def _gh_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def github_whoami() -> str:
    if settings.GITHUB_DEFAULT_ORG:
        return settings.GITHUB_DEFAULT_ORG
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{GH_API}/user", headers=_gh_headers())
    resp.raise_for_status()
    return resp.json().get("login", "")


async def create_repo(owner: str, repo: str, description: str) -> dict[str, Any]:
    payload = {"name": repo, "description": description[:300], "private": False, "auto_init": True}
    url = f"{GH_API}/orgs/{owner}/repos" if settings.GITHUB_DEFAULT_ORG else f"{GH_API}/user/repos"
    async with httpx.AsyncClient(timeout=25) as client:
        resp = await client.post(url, json=payload, headers=_gh_headers())
        if resp.status_code == 422:
            existing = await client.get(f"{GH_API}/repos/{owner}/{repo}", headers=_gh_headers())
            if existing.status_code == 200:
                return existing.json()
        resp.raise_for_status()
        return resp.json()


async def push_files(owner: str, repo: str, files: dict[str, str], message: str = "A.R.M.X AI: initial site") -> int:
    """Commit each file to the default branch via the Contents API."""
    pushed = 0
    async with httpx.AsyncClient(timeout=30) as client:
        repo_resp = await client.get(f"{GH_API}/repos/{owner}/{repo}", headers=_gh_headers())
        repo_resp.raise_for_status()
        branch = repo_resp.json().get("default_branch", "main")

        for path, content in files.items():
            api = f"{GH_API}/repos/{owner}/{repo}/contents/{path}"
            existing_sha = None
            head = await client.get(api, params={"ref": branch}, headers=_gh_headers())
            if head.status_code == 200:
                existing_sha = head.json().get("sha")
            body = {
                "message": f"{message} ({path})",
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": branch,
            }
            if existing_sha:
                body["sha"] = existing_sha
            put = await client.put(api, json=body, headers=_gh_headers())
            if put.status_code >= 400:
                raise RuntimeError(f"GitHub rejected {path}: {put.status_code} {put.text[:200]}")
            pushed += 1
    return pushed


async def ensure_vercel_project(name: str) -> dict[str, Any]:
    params = {"teamId": settings.VERCEL_TEAM_ID} if settings.VERCEL_TEAM_ID else {}
    headers = {"Authorization": f"Bearer {settings.VERCEL_TOKEN}"}
    async with httpx.AsyncClient(timeout=25) as client:
        resp = await client.post(
            f"{VCL_API}/v10/projects", json={"name": name, "framework": None}, params=params, headers=headers
        )
        if resp.status_code in (409, 400) and "already exists" in resp.text.lower():
            got = await client.get(f"{VCL_API}/v9/projects/{name}", params=params, headers=headers)
            got.raise_for_status()
            return got.json()
        resp.raise_for_status()
        return resp.json()


async def trigger_deploy(project: str, owner: str, repo: str) -> dict[str, Any]:
    params = {"teamId": settings.VERCEL_TEAM_ID} if settings.VERCEL_TEAM_ID else {}
    headers = {"Authorization": f"Bearer {settings.VERCEL_TOKEN}"}
    body = {
        "name": project,
        "project": project,
        "target": "production",
        "gitSource": {"type": "github", "repo": f"{owner}/{repo}", "ref": "main"},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{VCL_API}/v13/deployments", json=body, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json()


async def poll_deployment(deployment_id: str, timeout_seconds: int = 180) -> dict[str, Any]:
    params: dict[str, str] = {"teamId": settings.VERCEL_TEAM_ID} if settings.VERCEL_TEAM_ID else {}
    headers = {"Authorization": f"Bearer {settings.VERCEL_TOKEN}"}
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=20) as client:
        while time.monotonic() < deadline:
            resp = await client.get(f"{VCL_API}/v13/deployments/{deployment_id}", params=params, headers=headers)
            if resp.status_code == 200:
                last = resp.json()
                state = last.get("readyState") or last.get("state")
                if state in ("READY", "ERROR", "CANCELED"):
                    return last
            await asyncio.sleep(3)
    return last or {"readyState": "TIMEOUT"}


async def create_turso_database(name: str) -> dict[str, Any]:
    if not settings.TURSO_ORG:
        raise IntegrationNotConfigured("turso", "Set TURSO_ORG and TURSO_API_TOKEN.")
    headers = {"Authorization": f"Bearer {settings.TURSO_API_TOKEN}"}
    body = {"name": re.sub(r"[^a-z0-9-]", "-", name.lower())[:48], "group": "default"}
    async with httpx.AsyncClient(timeout=25) as client:
        resp = await client.post(
            f"{settings.TURSO_BASE_URL}/v1/organizations/{settings.TURSO_ORG}/databases",
            json=body,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Turso {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    db = data.get("database", data)
    return {"name": db.get("Name") or db.get("name", body["name"]), "hostname": db.get("Hostname", "")}


# --------------------------------------------------------------------------
# High-level orchestration (shared by live and simulated modes)
# --------------------------------------------------------------------------
@dataclass(slots=True)
class DeployResult:
    ok: bool
    simulated: bool
    owner: str = ""
    repo: str = ""
    repo_url: str = ""
    repo_is_platform_owned: bool = False
    vercel_project: str = ""
    url: str = ""
    status: str = ""
    log: list[str] = None  # type: ignore[assignment]
    error: str = ""
    turso_db: str = ""

    def __post_init__(self) -> None:
        if self.log is None:
            self.log = []

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "simulated": self.simulated,
            "repo_owner": self.owner,
            "repo": self.repo,
            "repo_url": self.repo_url,
            "repo_is_platform_owned": self.repo_is_platform_owned,
            "vercel_project": self.vercel_project,
            "url": self.url,
            "status": self.status,
            "turso_db": self.turso_db,
            "log": self.log,
            "error": self.error,
        }


async def deploy_project(
    *,
    name: str,
    slug: str,
    user_id: str,
    files: dict[str, str],
    user_github_owner: str | None = None,
    with_database: bool = False,
) -> DeployResult:
    simulated = settings.PIPELINE_MODE == "simulated"
    repo = repo_slug(name, user_id)
    project = vercel_project_name(slug)

    if simulated:
        owner = user_github_owner or settings.GITHUB_DEFAULT_ORG or "armx-projects"
        platform_owned = user_github_owner is None
        result = DeployResult(
            ok=True,
            simulated=True,
            owner=owner,
            repo=repo,
            repo_url=f"https://github.com/{owner}/{repo}",
            repo_is_platform_owned=platform_owned,
            vercel_project=project,
            url=f"https://{project}.vercel.app",
            status="READY",
            turso_db=f"{repo}-db" if with_database else "",
        )
        result.log = [
            f"[simulated] destination allowlist check for {owner}/{repo}",
            f"[simulated] created public repository {owner}/{repo} ({len(files)} files)",
            f"[simulated] pushed commit to main",
            f"[simulated] created Vercel project {project}",
            f"[simulated] deployment READY at {result.url}",
        ]
        if with_database:
            result.log.append(f"[simulated] provisioned Turso database {repo}-db (project-scoped)")
        return result

    if not settings.GITHUB_TOKEN or not settings.VERCEL_TOKEN:
        raise IntegrationNotConfigured(
            "github_vercel", "Set GITHUB_TOKEN and VERCEL_TOKEN, or run with PIPELINE_MODE=simulated."
        )

    owner = user_github_owner or await github_whoami()
    if not owner:
        return DeployResult(ok=False, simulated=False, error="Could not resolve a GitHub owner")
    ensure_destination_allowed(owner, repo)

    log: list[str] = [f"destination {owner}/{repo} passed the allowlist"]
    try:
        repo_data = await create_repo(owner, repo, f"{name} - generated with A.R.M.X AI")
        log.append(f"repository ready: {repo_data.get('html_url', '')}")
        pushed = await push_files(owner, repo, files)
        log.append(f"pushed {pushed} files to main")

        vp = await ensure_vercel_project(project)
        log.append(f"Vercel project ready: {vp.get('name', project)}")

        deployment = await trigger_deploy(project, owner, repo)
        dep_id = deployment.get("id") or deployment.get("uid")
        log.append(f"deployment triggered: {dep_id}")
        final = await poll_deployment(dep_id) if dep_id else {}
        state = final.get("readyState") or final.get("state") or "UNKNOWN"
        url = f"https://{final.get('url')}" if final.get("url") else f"https://{project}.vercel.app"
        log.append(f"deployment state: {state}")

        turso_db = ""
        if with_database:
            try:
                db = await create_turso_database(repo)
                turso_db = db["name"]
                log.append(f"Turso database provisioned: {turso_db}")
            except Exception as exc:
                log.append(f"Turso skipped: {exc}"[:200])

        return DeployResult(
            ok=state == "READY",
            simulated=False,
            owner=owner,
            repo=repo,
            repo_url=f"https://github.com/{owner}/{repo}",
            repo_is_platform_owned=user_github_owner is None,
            vercel_project=project,
            url=url,
            status=state,
            log=log,
            turso_db=turso_db,
            error="" if state == "READY" else f"Deployment ended in state {state}",
        )
    except Exception as exc:
        log.append(f"failed: {exc}"[:300])
        return DeployResult(
            ok=False, simulated=False, owner=owner, repo=repo, vercel_project=project,
            status="FAILED", log=log, error=str(exc)[:400],
        )
