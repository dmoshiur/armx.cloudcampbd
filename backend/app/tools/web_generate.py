"""web_generate (MEDIUM) - draft a site in the sandbox and render a live preview."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.builder import generator, preview
from app.models import GeneratedProject
from app.registry import RiskTier, ToolContext, ToolResult, tool


class WebGenerateInput(BaseModel):
    prompt: str = Field(min_length=10, max_length=4000, description="What the site should be")
    name: str = Field(default="", max_length=60, description="Short project name")
    with_database: bool = Field(default=False, description="Provision a project-scoped Turso DB at deploy time")


@tool(
    name="web_generate",
    description=(
        "Generate a production-style static website from a description, run the design lint, "
        "and return a live preview URL. Nothing is pushed anywhere until web_deploy is approved."
    ),
    risk=RiskTier.MEDIUM,
    input_model=WebGenerateInput,
    scopes=("web:build",),
    rate_limit_per_minute=10,
    confirm=True,
    category="builder",
)
async def web_generate(ctx: ToolContext, payload: WebGenerateInput) -> ToolResult:
    name = payload.name.strip() or payload.prompt.split()[0][:24]
    slug = generator.slugify(name)

    existing = (
        await ctx.db.execute(
            GeneratedProject.__table__.select()
            .where(GeneratedProject.user_id == ctx.user.id, GeneratedProject.slug == slug)
            .limit(1)
        )
    ).first()

    result = await generator.generate(payload.prompt, name)
    files_json = json.dumps(result.files)
    lint_json = json.dumps(result.lint.as_dict())

    if ctx.dry_run:
        return ToolResult(
            ok=True,
            data={"slug": slug, "lint": result.lint.as_dict(), "files": list(result.files), "dry_run": True},
            message=f"Dry run: would generate {len(result.files)} files.",
        )

    if existing:
        project = await ctx.db.get(GeneratedProject, existing.id)
        project.files = files_json
        project.lint_report = lint_json
        project.lint_status = "pass" if result.lint.ok else "fail"
        project.description = payload.prompt[:2000]
        project.status = "preview"
    else:
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
        ctx.db.add(project)
    await ctx.db.commit()
    await ctx.db.refresh(project)

    generator.write_project(ctx.user.id, slug, result.files)
    token = preview.issue(project.id)

    return ToolResult(
        ok=True,
        data={
            "project_id": project.id,
            "slug": slug,
            "name": name,
            "mode": result.mode,
            "summary": result.summary,
            "files": sorted(result.files),
            "preview_url": f"/api/preview/{project.id}/index.html?t={token}",
            "preview_token": token,
            "lint": result.lint.as_dict(),
        },
        message=(
            f"Generated '{name}' ({result.mode} mode, {len(result.files)} files). "
            + ("Design lint passed. " if result.lint.ok else "Design lint found blocking issues. ")
            + "Preview is ready - deploy when you are happy."
        ),
    )
