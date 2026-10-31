"""web_deploy (HIGH) - push to an allowlisted repo and deploy to Vercel."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.builder import generator, lint as design_lint
from app.integrations import github_vercel
from app.models import GeneratedProject, IntegrationConnection
from app.registry import RiskTier, ToolContext, ToolResult, tool


class WebDeployInput(BaseModel):
    project_id: str = Field(default="", max_length=32, description="Project id (omit to use the latest)")
    confirm_repo: str = Field(
        default="",
        max_length=200,
        description=(
            "Optional 'owner/repo'. When supplied it must match the allowlisted destination exactly; "
            "when omitted the single-use human approval is the confirmation and the destination shown "
            "in the dialog is used."
        ),
    )
    with_database: bool = Field(default=False)


@tool(
    name="web_deploy",
    description=(
        "Deploy a generated project: push its files to the allowlisted GitHub repository and trigger a "
        "Vercel production deployment, returning the live URL. High risk - the human must approve the "
        "exact repository and Vercel project first."
    ),
    risk=RiskTier.HIGH,
    input_model=WebDeployInput,
    scopes=("web:deploy",),
    confirm=True,
    rate_limit_per_minute=3,
    category="builder",
)
async def web_deploy(ctx: ToolContext, payload: WebDeployInput) -> ToolResult:
    project: GeneratedProject | None = None
    if payload.project_id:
        project = await ctx.db.get(GeneratedProject, payload.project_id)
        if project is None or project.user_id != ctx.user.id:
            return ToolResult(ok=False, error="Project not found for this account")
    else:
        row = (
            await ctx.db.execute(
                GeneratedProject.__table__.select()
                .where(GeneratedProject.user_id == ctx.user.id)
                .order_by(GeneratedProject.updated_at.desc())
                .limit(1)
            )
        ).first()
        if row:
            project = await ctx.db.get(GeneratedProject, row.id)
    if project is None:
        return ToolResult(ok=False, error="Nothing to deploy: generate a project first.")

    files = json.loads(project.files or "{}")
    if not files:
        return ToolResult(ok=False, error="Project has no files")

    # Quality gate: never ship a design-lint failure silently.
    report = design_lint.lint_project(files)
    project.lint_report = json.dumps(report.as_dict())
    project.lint_status = "pass" if report.ok else "fail"
    await ctx.db.commit()
    if not report.ok:
        errors = [f["message"] for f in report.as_dict()["errors"][:4]]
        return ToolResult(
            ok=False,
            data={"lint": report.as_dict()},
            error="Blocked by the design lint: " + "; ".join(errors),
        )

    expected_repo = github_vercel.repo_slug(project.name, ctx.user.id)
    owner = await _owner_for(ctx)
    approved = f"{owner}/{expected_repo}".lower()
    if payload.confirm_repo.strip() and payload.confirm_repo.strip().lower() != approved:
        return ToolResult(
            ok=False,
            error=(
                f"Deployment destination mismatch. The approved target must be exactly '{approved}'. "
                "Nothing was pushed."
            ),
        )

    if ctx.dry_run:
        return ToolResult(
            ok=True,
            data={"repo": approved, "vercel_project": github_vercel.vercel_project_name(project.slug), "dry_run": True},
        )

    name = project.name
    result = await github_vercel.deploy_project(
        name=name,
        slug=project.slug,
        user_id=ctx.user.id,
        files=files,
        user_github_owner=await _user_github_owner(ctx),
        with_database=payload.with_database,
    )

    project.repo_owner = result.owner
    project.repo_full_name = f"{result.owner}/{result.repo}"
    project.repo_url = result.repo_url
    project.repo_is_platform_owned = result.repo_is_platform_owned
    project.vercel_project = result.vercel_project
    project.vercel_url = result.url if result.ok else ""
    project.deploy_status = result.status
    project.turso_db_ref = result.turso_db
    project.status = "deployed" if result.ok else "failed"
    await ctx.db.commit()

    if not result.ok:
        return ToolResult(ok=False, data=result.as_dict(), error=result.error or "Deployment failed")

    message = f"'{project.name}' is live at {result.url}."
    if result.repo_is_platform_owned:
        message += (
            f" No GitHub account was connected, so it was pushed to the platform account "
            f"({result.repo_url}) - you can connect your own account and redeploy any time."
        )
    if result.simulated:
        message += " (simulated pipeline: no real repository or deployment was created.)"
    return ToolResult(ok=True, data=result.as_dict(), message=message)


async def _user_github_owner(ctx: ToolContext) -> str | None:
    rows = (
        await ctx.db.execute(
            IntegrationConnection.__table__.select().where(
                IntegrationConnection.user_id == ctx.user.id, IntegrationConnection.provider == "github"
            )
        )
    ).first()
    if not rows:
        return None
    conn = await ctx.db.get(IntegrationConnection, rows.id)
    if conn is None or conn.status != "connected":
        return None
    try:
        return json.loads(conn.config or "{}").get("owner") or None
    except json.JSONDecodeError:
        return None


async def _owner_for(ctx: ToolContext) -> str:
    from app.core.config import settings

    return await _user_github_owner(ctx) or settings.GITHUB_DEFAULT_ORG or "armx-projects"
