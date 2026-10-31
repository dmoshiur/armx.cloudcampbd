"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api/client";
import type { Project } from "@/lib/types";
import { Badge, Card, CardHeader, EmptyState, ErrorState, LoadingBlock, PageHeader, LinkButton } from "@/components/ui/primitives";

export default function BuilderPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  const detail = useQuery({
    queryKey: ["project", selected],
    queryFn: () =>
      api.get<{
        id: string;
        name: string;
        description: string;
        files: string[];
        lint: { ok?: boolean; score?: number; errors?: { message: string }[]; warnings?: { message: string }[] };
        preview_url: string;
        repo_url: string;
        vercel_url: string;
        repo_is_platform_owned: boolean;
      }>(`/projects/${selected}`),
    enabled: Boolean(selected),
  });

  return (
    <div>
      <PageHeader
        title="Site builder"
        description="Describe it in the assistant, preview it in the sandbox, then approve one deployment. Every project keeps its repo, deployment and database reference."
        action={<LinkButton href="/" variant="primary">Open assistant</LinkButton>}
      />

      {projects.isLoading && <LoadingBlock label="Loading projects" />}
      {projects.isError && <ErrorState message={projects.error.message} onRetry={() => void projects.refetch()} />}

      {projects.data && projects.data.length === 0 && (
        <EmptyState
          icon="◈"
          title="No projects yet"
          description="Ask the assistant to “build a landing page for …”. It generates the site, runs the design audit and shows a preview before anything is published."
          action={<LinkButton href="/">Go to the assistant</LinkButton>}
        />
      )}

      {projects.data && projects.data.length > 0 && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div className="space-y-3">
            {projects.data.map((project) => (
              <button
                key={project.id}
                type="button"
                onClick={() => setSelected(project.id)}
                className={`block w-full rounded-lg border bg-surface p-4 text-left transition hover:border-accent/50 ${
                  selected === project.id ? "border-accent/60" : "border-edge"
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-h3">{project.name}</h3>
                  <Badge tone={project.status === "deployed" ? "success" : project.status === "failed" ? "danger" : "neutral"}>
                    {project.status}
                  </Badge>
                  <Badge tone={project.lint_status === "pass" ? "success" : "warning"}>lint {project.lint_status}</Badge>
                </div>
                <p className="mt-1 truncate text-caption text-fgmuted">{project.vercel_url || "not deployed"}</p>
                {project.repo_is_platform_owned && project.repo_url && (
                  <p className="mt-1 text-caption text-warning">Pushed to the platform GitHub account</p>
                )}
              </button>
            ))}
          </div>

          <Card>
            {!selected && <div className="p-6 text-body text-fgmuted">Select a project to inspect it.</div>}
            {selected && detail.isLoading && <div className="p-6"><LoadingBlock /></div>}
            {selected && detail.isError && (
              <div className="p-6">
                <ErrorState message={detail.error.message} onRetry={() => void detail.refetch()} />
              </div>
            )}
            {selected && detail.data && (
              <>
                <CardHeader
                  title={detail.data.name}
                  description={detail.data.description.slice(0, 160)}
                  action={
                    <div className="flex gap-2">
                      <a href={detail.data.preview_url} target="_blank" rel="noopener noreferrer">
                        <span className="inline-flex min-h-[40px] items-center rounded-md border border-edge px-3 text-caption font-semibold hover:bg-white/5">
                          Preview ↗
                        </span>
                      </a>
                      {detail.data.vercel_url && (
                        <a href={detail.data.vercel_url} target="_blank" rel="noopener noreferrer">
                          <span className="inline-flex min-h-[40px] items-center rounded-md bg-accent px-3 text-caption font-semibold text-ink">
                            Live site ↗
                          </span>
                        </a>
                      )}
                    </div>
                  }
                />
                <div className="space-y-5 p-5">
                  <iframe
                    src={detail.data.preview_url}
                    title={`Preview of ${detail.data.name}`}
                    className="h-[420px] w-full rounded-md border border-edge bg-white"
                    sandbox="allow-scripts allow-forms allow-popups"
                  />
                  <div>
                    <h4 className="text-caption font-semibold uppercase tracking-wide text-fgmuted">Design audit</h4>
                    {detail.data.lint?.ok ? (
                      <p className="mt-1 text-body text-success">Passed · score {detail.data.lint.score ?? 100}</p>
                    ) : (
                      <div className="mt-1 space-y-1 text-body text-danger">
                        {(detail.data.lint?.errors ?? []).slice(0, 4).map((error) => (
                          <p key={error.message}>{error.message}</p>
                        ))}
                      </div>
                    )}
                    {(detail.data.lint?.warnings ?? []).length > 0 && (
                      <ul className="mt-2 space-y-1 text-caption text-warning">
                        {detail.data.lint!.warnings!.slice(0, 4).map((warning) => (
                          <li key={warning.message}>{warning.message}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-md border border-edge bg-bg p-3">
                      <p className="text-caption text-fgmuted">Repository</p>
                      <p className="mt-1 truncate text-caption text-fg">{detail.data.repo_url || "—"}</p>
                    </div>
                    <div className="rounded-md border border-edge bg-bg p-3">
                      <p className="text-caption text-fgmuted">Files</p>
                      <p className="mt-1 truncate text-caption text-fg">{detail.data.files.join(", ")}</p>
                    </div>
                  </div>
                  <p className="text-caption text-fgmuted">
                    To change this site, describe the change in the assistant and deploy again — deployment always
                    asks for confirmation first.
                  </p>
                </div>
              </>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
