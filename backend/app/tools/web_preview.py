"""web_preview (MEDIUM) - re-open the preview of an existing generated project."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.builder import generator, preview
from app.models import GeneratedProject
from app.registry import RiskTier, ToolContext, ToolResult, tool


class WebPreviewInput(BaseModel):
    project_id: str = Field(default="", max_length=32, description="Project id (omit to use the latest)")
    refresh_files: bool = Field(default=False, description="Re-materialise the sandbox files from the saved project")


@tool(
    name="web_preview",
    description="Return a signed live-preview URL for a generated project without deploying anything.",
    risk=RiskTier.MEDIUM,
    input_model=WebPreviewInput,
    scopes=("web:build",),
    rate_limit_per_minute=20,
    category="builder",
)
async def web_preview(ctx: ToolContext, payload: WebPreviewInput) -> ToolResult:
    project: GeneratedProject | None = None
    if payload.project_id:
        project = await ctx.db.get(GeneratedProject, payload.project_id)
        if project is None or project.user_id != ctx.user.id:
            return ToolResult(ok=False, error="Project not found for this account")
    else:
        rows = (
            await ctx.db.execute(
                GeneratedProject.__table__.select()
                .where(GeneratedProject.user_id == ctx.user.id)
                .order_by(GeneratedProject.updated_at.desc())
                .limit(1)
            )
        ).first()
        if rows:
            project = await ctx.db.get(GeneratedProject, rows.id)
    if project is None:
        return ToolResult(ok=False, error="No generated project yet. Ask me to build one first.")

    if payload.refresh_files:
        import json

        generator.write_project(ctx.user.id, project.slug, json.loads(project.files or "{}"))

    token = preview.issue(project.id)
    return ToolResult(
        ok=True,
        data={
            "project_id": project.id,
            "name": project.name,
            "status": project.status,
            "lint_ok": project.lint_status == "pass",
            "preview_url": f"/api/preview/{project.id}/index.html?t={token}",
            "deploy_url": project.vercel_url,
            "repo_url": project.repo_url,
        },
        message=f"Preview for '{project.name}' is ready.",
    )
