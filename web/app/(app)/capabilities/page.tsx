"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, request } from "@/lib/api/client";
import type { IntegrationStatus, MatrixStatus } from "@/lib/types";
import { Badge, Card, CardHeader, ErrorState, PageHeader } from "@/components/ui/primitives";

interface PublicConfig {
  features: Record<string, boolean | number>;
  [key: string]: unknown;
}

interface ToolInfo {
  name: string;
  description?: string;
  risk_level?: string;
  requires_approval?: boolean;
  status?: string;
  version?: string;
}

interface Feature {
  title: string;
  route: string;
  detail: string;
  endpoint: string;
  status: "implemented" | "conditional";
  note: string;
}

export default function CapabilitiesPage() {
  const config = useQuery({ queryKey: ["config"], queryFn: () => request<PublicConfig>("/config", { auth: false }), retry: false });
  const tools = useQuery({ queryKey: ["tools"], queryFn: () => api.get<{ tools: ToolInfo[] } | ToolInfo[]>("/tools"), retry: false });
  const integrations = useQuery({ queryKey: ["integrations"], queryFn: () => api.get<{ integrations: IntegrationStatus[] }>("/integrations"), retry: false });
  const matrix = useQuery({ queryKey: ["matrix", "status"], queryFn: () => request<MatrixStatus>("/matrix/status", { auth: false }), retry: false });

  const toolList = Array.isArray(tools.data) ? tools.data : (tools.data?.tools || []);
  const features: Feature[] = [
    {
      title: "Durable streaming assistant",
      route: "/",
      detail: "Provider deltas over authenticated SSE, stop/retry controls, persisted run/user/message IDs and structured errors with request IDs.",
      endpoint: "/api/assistant/chat/stream",
      status: "implemented",
      note: "Streaming is real server-sent events; offline planning is a labelled fallback.",
    },
    {
      title: "Human approval workflow",
      route: "/",
      detail: "Hash-bound approvals, countdown/expiry, exact action arguments, approve/reject and retry. High-risk actions require explicit confirmation.",
      endpoint: "/api/assistant/runs/{id}/approve",
      status: "implemented",
      note: "No fake approvals; Security Gateway revalidates every action.",
    },
    {
      title: "Workspace intelligence",
      route: "/projects",
      detail: "Database-backed projects, ranked memory, automations, activity, analytics, preferences, version history and sandboxed previews.",
      endpoint: "/api/projects, /api/memory, /api/automations, /api/activity",
      status: "implemented",
      note: "Project files and versions persist in the database.",
    },
    {
      title: "Matrix / CMatrix",
      route: "/settings",
      detail: "Original GPL-3.0 CMatrix via isolated PTY with WebSocket then SSE, one-use tickets and an honestly labelled MIT JS port fallback.",
      endpoint: "/api/matrix/status, /api/matrix/ws",
      status: "conditional",
      note: matrix.data ? (matrix.data.available ? "Executable available on this backend." : matrix.data.reason || "Executable unavailable; MIT fallback is labelled.") : "Capability status loading.",
    },
    {
      title: "Resend email delivery",
      route: "/settings",
      detail: "Official REST API, hashed single-use links, bounded retries, idempotency, signed webhook events and a delivery ledger.",
      endpoint: "/api/auth/forgot-password, /api/webhooks/resend",
      status: "conditional",
      note: config.data?.features.resend_email ? "Server reports Resend configured; delivery still depends on signed webhook events." : "Requires RESEND_API_KEY, RESEND_FROM_EMAIL and APP_BASE_URL.",
    },
    {
      title: "Admin LLM routing",
      route: "/admin",
      detail: "Provider/model CRUD, enable/disable, weight, priority, context/cost and health checks. Exact route shown per assistant turn.",
      endpoint: "/api/admin/models",
      status: "implemented",
      note: "No silent model switching; DB routing is authoritative.",
    },
    {
      title: "Device & home automation",
      route: "/devices",
      detail: "Registered devices, allowlisted commands, explicit execution, audit history and integration status.",
      endpoint: "/api/devices, /api/automations/{id}/run",
      status: "conditional",
      note: "Commands run only for configured, allowlisted devices.",
    },
    {
      title: "Tool registry",
      route: "/tools",
      detail: "21 typed, timeout-bounded tools with declared schemas, risk levels, permissions and honest provider results.",
      endpoint: "/api/tools, /api/tools/registry",
      status: "implemented",
      note: "No tool output is fabricated; failures name the missing configuration.",
    },
  ];

  return (
    <div className="space-y-5 pb-10">
      <PageHeader title="Capabilities" description="Implemented features and their real backend status. Conditional capabilities state exactly what is missing." />

      <div className="grid gap-4 md:grid-cols-2">
        {features.map((feature) => (
          <Card key={feature.title}>
            <CardHeader
              title={feature.title}
              description={feature.detail}
              action={<Badge tone={feature.status === "implemented" ? "success" : "warning"}>{feature.status}</Badge>}
            />
            <div className="space-y-2 p-5 pt-0">
              <p className="font-mono text-caption text-accent">{feature.endpoint}</p>
              <p className="text-caption text-fgmuted">{feature.note}</p>
              <Link href={feature.route} className="inline-block text-caption text-accent hover:underline">Open {feature.title} →</Link>
            </div>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Public feature flags" description="Non-secret status from /api/config." />
          <div className="space-y-2 p-5 pt-0">
            {config.isError && <ErrorState message={config.error.message} onRetry={() => void config.refetch()} />}
            {Object.entries(config.data?.features || {}).map(([key, value]) => (
              <div key={key} className="flex items-center justify-between gap-2 border-b border-edge/60 py-1.5 text-caption last:border-0">
                <span className="font-mono text-fgmuted">{key}</span>
                <Badge tone={value === true ? "success" : value === false ? "warning" : "accent"}>{String(value)}</Badge>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <CardHeader title="Registered tools" description={`${toolList.length} tools`} />
          <div className="space-y-2 p-5 pt-0">
            {toolList.slice(0, 9).map((tool) => (
              <div key={tool.name} className="flex flex-wrap items-center gap-2 text-caption">
                <span className="font-mono text-fg">{tool.name}</span>
                {tool.risk_level && <Badge tone={tool.risk_level === "high" ? "danger" : tool.risk_level === "medium" ? "warning" : "neutral"}>{tool.risk_level}</Badge>}
                {tool.requires_approval && <Badge tone="accent">approval</Badge>}
              </div>
            ))}
            <Link href="/tools" className="inline-block text-caption text-accent hover:underline">Full tool registry →</Link>
          </div>
        </Card>
        <Card>
          <CardHeader title="Integration status" description="Honest configured/simulated state." />
          <div className="space-y-2 p-5 pt-0">
            {integrations.isError && <ErrorState message={integrations.error.message} onRetry={() => void integrations.refetch()} />}
            {(integrations.data?.integrations || []).slice(0, 9).map((item) => (
              <div key={item.provider} className="flex flex-wrap items-center gap-2 text-caption">
                <span className="font-mono text-fg">{item.provider}</span>
                <Badge tone={item.configured ? "success" : "warning"}>{item.configured ? "configured" : "missing"}</Badge>
                {item.simulated && <Badge tone="warning">simulated</Badge>}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
