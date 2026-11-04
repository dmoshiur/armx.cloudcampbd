"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, describeError } from "@/lib/api/client";
import type { Project, ProjectDetail } from "@/lib/types";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, Label, LoadingBlock, PageHeader, Textarea } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";

interface LintReport {
  ok?: boolean;
  score?: number;
  errors?: { message: string }[];
  warnings?: { message: string }[];
  [key: string]: unknown;
}

interface FileMapResponse {
  files: Record<string, string>;
  count: number;
  status: string;
}

interface VersionRow {
  id: string;
  version: number;
  note: string;
  files: string[];
  created_at: string;
}

interface DeployStatus {
  confirmed: boolean;
  configured: boolean;
  state: string;
  url?: string;
  detail: string;
  provider?: string;
  simulated?: boolean;
  deployment_id?: string;
  local_status?: string;
}

interface GenerateResult {
  id: string;
  name: string;
  slug: string;
  mode: string;
  summary: string;
  files: string[];
  lint: LintReport;
  preview_url: string;
}

const COMPONENTS = ["hero", "features", "pricing", "contact", "styles"] as const;
const VIEWPORTS = [
  { id: "desktop", label: "Desktop", width: "100%" },
  { id: "tablet", label: "Tablet", width: "768px" },
  { id: "mobile", label: "Mobile", width: "390px" },
] as const;

function encodeProjectPath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

function BuilderWorkbench() {
  const params = useSearchParams();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(params.get("project"));
  const [prompt, setPrompt] = useState("");
  const [name, setName] = useState("");
  const [component, setComponent] = useState<(typeof COMPONENTS)[number]>("hero");
  const [componentPrompt, setComponentPrompt] = useState("");
  const [versionNote, setVersionNote] = useState("");
  const [selectedFile, setSelectedFile] = useState<string>("");
  const [fileContent, setFileContent] = useState("");
  const [viewport, setViewport] = useState<(typeof VIEWPORTS)[number]["id"]>("desktop");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState(false);

  useEffect(() => {
    const requested = params.get("project");
    if (requested && requested !== selected) setSelected(requested);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  const detail = useQuery({
    queryKey: ["project", selected],
    queryFn: () => api.get<ProjectDetail>(`/projects/${selected}`),
    enabled: Boolean(selected),
  });
  const files = useQuery({
    queryKey: ["project-files", selected],
    queryFn: () => api.get<FileMapResponse>(`/projects/${selected}/files`),
    enabled: Boolean(selected),
  });
  const versions = useQuery({
    queryKey: ["project-versions", selected],
    queryFn: () => api.get<VersionRow[]>(`/projects/${selected}/versions`),
    enabled: Boolean(selected),
  });
  const deployStatus = useQuery({
    queryKey: ["project-deploy", selected],
    queryFn: () => api.get<DeployStatus>(`/projects/${selected}/deploy-status`),
    enabled: Boolean(selected),
  });

  useEffect(() => {
    if (!files.data?.files) return;
    const paths = Object.keys(files.data.files).sort();
    const next = selectedFile && paths.includes(selectedFile) ? selectedFile : paths[0] || "";
    setSelectedFile(next);
    setFileContent(next ? files.data.files[next] : "");
  }, [files.data, selectedFile]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["projects"] });
    void queryClient.invalidateQueries({ queryKey: ["project", selected] });
    void queryClient.invalidateQueries({ queryKey: ["project-files", selected] });
    void queryClient.invalidateQueries({ queryKey: ["project-versions", selected] });
    void queryClient.invalidateQueries({ queryKey: ["project-deploy", selected] });
  };

  const generate = useMutation({
    mutationFn: () => api.post<GenerateResult>("/projects/generate", { prompt, name }),
    onSuccess: (result) => {
      setSelected(result.id);
      setPrompt("");
      setName("");
      setPreviewError(false);
      toast.push(`Generated ${result.files.length} real files (${result.mode} mode). Deployment is not claimed.`, "success");
      invalidate();
    },
    onError: (err) => toast.push(describeError(err, "generate a site"), "error"),
  });

  const saveFile = useMutation({
    mutationFn: () =>
      api.put<{ path: string; lint: LintReport; bytes: number }>(
        `/projects/${selected}/file/${encodeProjectPath(selectedFile)}`,
        { content: fileContent },
      ),
    onSuccess: () => {
      toast.push("File saved and design lint re-run.", "success");
      invalidate();
    },
    onError: (err) => toast.push(describeError(err, "save this file"), "error"),
  });

  const regenerateComponent = useMutation({
    mutationFn: () =>
      api.post<{ component: string; lint: LintReport; preview_url: string }>(
        `/projects/${selected}/regenerate-component`,
        { component, prompt: componentPrompt },
      ),
    onSuccess: (result) => {
      setComponentPrompt("");
      toast.push(`Regenerated ${result.component} block with escaped content.`, "success");
      invalidate();
    },
    onError: (err) => toast.push(describeError(err, "regenerate this component"), "error"),
  });

  const snapshot = useMutation({
    mutationFn: () => api.post(`/projects/${selected}/versions`, { note: versionNote || "Manual snapshot" }),
    onSuccess: () => {
      setVersionNote("");
      toast.push("Version snapshot saved.", "success");
      invalidate();
    },
    onError: (err) => toast.push(describeError(err, "create a version"), "error"),
  });

  const restore = useMutation({
    mutationFn: (version: number) => api.post(`/projects/${selected}/versions/${version}/restore`, {}),
    onSuccess: () => {
      toast.push("Version restored; a snapshot was taken first.", "success");
      invalidate();
    },
    onError: (err) => toast.push(describeError(err, "restore this version"), "error"),
  });

  const download = useMutation({
    mutationFn: async () => {
      const blob = await api.blob(`/projects/${selected}/download`);
      if (!blob) throw new Error("No source archive was returned.");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${detail.data?.slug || "armx-project"}.zip`;
      link.click();
      URL.revokeObjectURL(url);
    },
    onError: (err) => toast.push(describeError(err, "download the source"), "error"),
  });

  const previewUrl = detail.data?.preview_url || "";
  const confirmedUrl = deployStatus.data?.confirmed ? deployStatus.data.url || "" : "";
  const lint = detail.data?.lint as LintReport | undefined;

  return (
    <div className="space-y-5 pb-10">
      <PageHeader
        title="Site Builder"
        description="Generate real files, edit them, snapshot versions, preview in a sandbox and inspect provider-confirmed deployment status. No simulated success is shown as live."
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <div className="space-y-4">
          <Card>
            <CardHeader title="Generate a project" description="Direct deterministic/planner generation inside the sandbox path allowlist." />
            <div className="space-y-3 p-4">
              <div>
                <Label htmlFor="builder-name">Project name</Label>
                <Input id="builder-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Emerald Studio" />
              </div>
              <div>
                <Label htmlFor="builder-prompt">Brief</Label>
                <Textarea id="builder-prompt" rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Build a responsive landing page for a Dhaka design studio with pricing and contact sections." />
              </div>
              <Button className="w-full" onClick={() => generate.mutate()} loading={generate.isPending} disabled={prompt.trim().length < 10}>
                Generate real files
              </Button>
              <p className="text-[11px] text-fgmuted">Paths are validated, file sizes capped, design-linted and written to an isolated workspace. AI output is never executed as shell.</p>
            </div>
          </Card>

          <Card>
            <CardHeader title="Projects" description={`${projects.data?.length ?? 0} saved project(s)`} />
            <div className="space-y-2 p-4">
              {projects.isLoading && <LoadingBlock label="Loading projects" />}
              {projects.isError && <ErrorState message={projects.error.message} onRetry={() => void projects.refetch()} />}
              {projects.data?.length === 0 && <EmptyState title="No projects" description="Generate a project from a brief above." />}
              {(projects.data || []).map((project) => (
                <button
                  key={project.id}
                  type="button"
                  onClick={() => setSelected(project.id)}
                  className={clsx("w-full rounded-lg border p-3 text-left transition", selected === project.id ? "border-accent/60 bg-accent/5" : "border-edge bg-bg/40 hover:border-accent/40")}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-body font-semibold text-fg">{project.name}</span>
                    <Badge tone={project.status === "deployed" ? "success" : project.status === "failed" ? "danger" : "neutral"}>{project.status}</Badge>
                  </div>
                  <p className="mt-1 truncate font-mono text-caption text-fgmuted">{project.slug}</p>
                  <p className="mt-1 text-caption text-fgmuted">deploy: {project.deploy_status || "not_started"}</p>
                </button>
              ))}
            </div>
          </Card>
        </div>

        <div className="min-w-0 space-y-4">
          {!selected && (
            <Card><div className="p-8 text-center text-body text-fgmuted">Select or generate a project to open the workbench.</div></Card>
          )}
          {selected && (detail.isLoading || files.isLoading) && <Card><div className="p-6"><LoadingBlock label="Loading project files" /></div></Card>}
          {selected && (detail.isError || files.isError) && (
            <Card><div className="p-6"><ErrorState message={detail.error?.message || files.error?.message || "Could not load project"} onRetry={() => { void detail.refetch(); void files.refetch(); }} /></div></Card>
          )}

          {selected && detail.data && (
            <>
              <Card>
                <CardHeader
                  title={detail.data.name}
                  description={`${detail.data.files.length} files · lint ${detail.data.lint_status || "unknown"} · status ${detail.data.status}`}
                  action={
                    <div className="flex flex-wrap gap-2">
                      {previewUrl && (
                        <a href={previewUrl} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-touch items-center rounded-md border border-edge px-3 text-caption font-semibold text-fg hover:border-accent/50">
                          Open preview ↗
                        </a>
                      )}
                      <Button variant="secondary" size="sm" onClick={() => download.mutate()} loading={download.isPending}>Download ZIP</Button>
                    </div>
                  }
                />
                <div className="space-y-4 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    {VIEWPORTS.map((option) => (
                      <button key={option.id} type="button" onClick={() => setViewport(option.id)} aria-pressed={viewport === option.id} className={clsx("rounded-md border px-3 py-1.5 text-caption", viewport === option.id ? "border-accent/60 bg-accent/10 text-accent" : "border-edge text-fgmuted hover:text-fg")}>
                        {option.label}
                      </button>
                    ))}
                    {previewLoading && <span className="text-caption text-fgmuted">Loading preview…</span>}
                    {previewError && <Badge tone="danger">preview failed</Badge>}
                  </div>
                  <div className="overflow-hidden rounded-lg border border-edge bg-white/5 p-2">
                    <div className="mx-auto transition-[max-width] duration-200" style={{ maxWidth: VIEWPORTS.find((v) => v.id === viewport)?.width }}>
                      {previewUrl ? (
                        <iframe
                          key={`${previewUrl}-${viewport}`}
                          src={previewUrl}
                          title={`Sandbox preview of ${detail.data.name}`}
                          sandbox="allow-scripts allow-forms allow-popups"
                          className="h-[520px] w-full rounded-md border border-edge bg-white"
                          onLoad={() => { setPreviewLoading(false); setPreviewError(false); }}
                          onError={() => { setPreviewLoading(false); setPreviewError(true); }}
                        />
                      ) : (
                        <div className="grid h-[520px] place-items-center rounded-md border border-edge bg-bg/60 text-caption text-fgmuted">No signed preview URL is available.</div>
                      )}
                    </div>
                  </div>
                  {lint && (
                    <div className="rounded-md border border-edge bg-bg/40 p-3 text-caption">
                      <p className={lint.ok ? "text-success" : "text-danger"}>Design lint: {lint.ok ? "passed" : "failed"} · score {lint.score ?? 0}</p>
                      {(lint.errors || []).slice(0, 3).map((error) => <p key={error.message} className="mt-1 text-danger">{error.message}</p>)}
                    </div>
                  )}
                  <div className="rounded-md border border-edge bg-bg/40 p-3 text-caption">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={deployStatus.data?.confirmed ? "success" : deployStatus.data?.configured ? "warning" : "neutral"}>
                        {deployStatus.data?.confirmed ? "provider confirmed" : deployStatus.data?.configured ? "configured · awaiting confirmation" : "not configured"}
                      </Badge>
                      <span className="text-fgmuted">state: {deployStatus.data?.state || "unknown"}</span>
                      <span className="text-fgmuted">provider: {deployStatus.data?.provider || "none"}</span>
                    </div>
                    <p className="mt-2 text-fgmuted">{deployStatus.data?.detail || "Checking deployment status…"}</p>
                    {confirmedUrl ? (
                      <a href={confirmedUrl} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-accent hover:underline">Confirmed live URL ↗</a>
                    ) : (
                      <p className="mt-2 text-warning">No live URL is shown because no provider has confirmed a READY deployment.</p>
                    )}
                  </div>
                </div>
              </Card>

              <div className="grid gap-4 lg:grid-cols-2">
                <Card>
                  <CardHeader title="Edit generated files" description="Server-side path validation and design lint on save." />
                  <div className="space-y-3 p-4">
                    <div>
                      <Label htmlFor="builder-file">File</Label>
                      <select id="builder-file" value={selectedFile} onChange={(e) => { setSelectedFile(e.target.value); setFileContent(files.data?.files[e.target.value] || ""); }} className="h-10 w-full rounded-md border border-edge bg-bg px-3 text-caption text-fg">
                        {(files.data ? Object.keys(files.data.files).sort() : []).map((path) => <option key={path} value={path}>{path}</option>)}
                      </select>
                    </div>
                    <Textarea rows={10} value={fileContent} onChange={(e) => setFileContent(e.target.value)} className="font-mono text-[12px]" aria-label="File content" />
                    <Button onClick={() => saveFile.mutate()} loading={saveFile.isPending} disabled={!selectedFile}>Save file</Button>
                  </div>
                </Card>

                <Card>
                  <CardHeader title="Regenerate a component" description="Bounded, escaped HTML/CSS block. Never executes AI output." />
                  <div className="space-y-3 p-4">
                    <div>
                      <Label htmlFor="builder-component">Component</Label>
                      <select id="builder-component" value={component} onChange={(e) => setComponent(e.target.value as (typeof COMPONENTS)[number])} className="h-10 w-full rounded-md border border-edge bg-bg px-3 text-caption text-fg">
                        {COMPONENTS.map((value) => <option key={value} value={value}>{value}</option>)}
                      </select>
                    </div>
                    <Textarea rows={3} value={componentPrompt} onChange={(e) => setComponentPrompt(e.target.value)} placeholder="A concise new headline and supporting copy" />
                    <Button variant="secondary" onClick={() => regenerateComponent.mutate()} loading={regenerateComponent.isPending} disabled={componentPrompt.trim().length < 4}>
                      Regenerate component
                    </Button>
                  </div>
                </Card>
              </div>

              <Card>
                <CardHeader title="Version history" description="Every edit/regeneration snapshots the previous files first." />
                <div className="space-y-3 p-4">
                  <div className="flex gap-2">
                    <Input value={versionNote} onChange={(e) => setVersionNote(e.target.value)} placeholder="Snapshot note" />
                    <Button variant="secondary" onClick={() => snapshot.mutate()} loading={snapshot.isPending}>Snapshot</Button>
                  </div>
                  {versions.isError && <ErrorState message={versions.error.message} onRetry={() => void versions.refetch()} />}
                  <ul className="space-y-2">
                    {(versions.data || []).map((row) => (
                      <li key={row.id} className="flex flex-wrap items-center gap-2 rounded-md border border-edge bg-bg/40 p-2.5 text-caption">
                        <Badge tone="accent">v{row.version}</Badge>
                        <span className="text-fg">{row.note}</span>
                        <span className="text-fgmuted">{row.files.length} files</span>
                        <span className="ml-auto text-fgmuted">{new Date(row.created_at).toLocaleString()}</span>
                        <Button size="sm" variant="ghost" onClick={() => restore.mutate(row.version)} loading={restore.isPending}>Restore</Button>
                      </li>
                    ))}
                    {(versions.data || []).length === 0 && <p className="text-caption text-fgmuted">No versions yet. Save an edit or create a snapshot.</p>}
                  </ul>
                </div>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function BuilderPage() {
  return (
    <Suspense fallback={<div className="p-6 text-body text-fgmuted">Loading builder…</div>}>
      <BuilderWorkbench />
    </Suspense>
  );
}
