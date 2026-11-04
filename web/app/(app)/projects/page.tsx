"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, describeError } from "@/lib/api/client";
import type { Project } from "@/lib/types";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";

interface DeployStatus {
  confirmed: boolean;
  configured: boolean;
  state: string;
  url?: string;
  detail: string;
  provider?: string;
}

function ProjectRow({ project }: { project: Project }) {
  const toast = useToast();
  const status = useQuery({
    queryKey: ["project-deploy", project.id],
    queryFn: () => api.get<DeployStatus>(`/projects/${project.id}/deploy-status`),
    retry: false,
  });

  const download = async () => {
    try {
      const blob = await api.blob(`/projects/${project.id}/download`);
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${project.slug}.zip`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.push(describeError(err, "download this project"), "error");
    }
  };

  return (
    <Card>
      <div className="flex flex-wrap items-start gap-3 p-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-body font-semibold text-fg">{project.name}</h3>
            <Badge tone={project.status === "deployed" ? "success" : project.status === "failed" ? "danger" : "neutral"}>{project.status}</Badge>
            <Badge tone="accent">{project.deploy_provider || "local"}</Badge>
          </div>
          <p className="mt-1 truncate text-caption text-fgmuted">{project.description || "No description"}</p>
          <p className="mt-1 font-mono text-caption text-fgmuted">{project.slug}</p>
          <p className="mt-2 text-caption text-fgmuted">
            {status.isLoading ? "Checking provider status…" : status.data?.detail || `deploy status: ${project.deploy_status || "not_started"}`}
          </p>
          {status.data?.confirmed && status.data.url ? (
            <a href={status.data.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-block text-caption text-accent hover:underline">Provider-confirmed URL ↗</a>
          ) : (
            <p className="mt-1 text-caption text-warning">No live URL is claimed without provider confirmation.</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href={`/builder?project=${project.id}`} className="inline-flex min-h-touch items-center rounded-md border border-accent/40 bg-accent/10 px-3 text-caption font-semibold text-accent hover:bg-accent/20">Open workbench</Link>
          <Button size="sm" variant="secondary" onClick={() => void download()}>Download ZIP</Button>
          {project.vercel_url && <Badge tone={status.data?.confirmed ? "success" : "warning"}>{status.data?.confirmed ? "confirmed URL" : "unconfirmed URL"}</Badge>}
        </div>
      </div>
    </Card>
  );
}

export default function ProjectsPage() {
  const list = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });

  return (
    <div className="space-y-5 pb-10">
      <PageHeader title="Projects" description="Generated files, versions, signed sandboxed previews and honest provider deployment status." />
      {list.isLoading && <Card><div className="p-6 text-body text-fgmuted">Loading projects…</div></Card>}
      {list.isError && <Card><div className="p-6"><ErrorState message={list.error.message} onRetry={() => void list.refetch()} /></div></Card>}
      {list.data?.length === 0 && <EmptyState title="No generated projects" description="Create one in the Site Builder workbench." />}
      <div className="space-y-3">
        {(list.data || []).map((project) => <ProjectRow key={project.id} project={project} />)}
      </div>
      <Card>
        <CardHeader title="Deployment integrity" description="Simulated mode is configuration state, never a live site." />
        <p className="p-5 pt-0 text-body text-fgmuted">
          A URL is shown only after the configured provider reports a READY deployment. Vercel, GitHub and related integrations are inspected through their status APIs; no DNS, web server or hosting provider is contacted from this page.
        </p>
      </Card>
    </div>
  );
}
