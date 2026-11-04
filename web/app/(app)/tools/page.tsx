"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api/client";
import { Badge, Card, CardHeader, EmptyState, ErrorState, Input, PageHeader } from "@/components/ui/primitives";

interface ToolDefinition {
  id: string;
  name: string;
  description: string;
  category: string;
  risk: string;
  permissions: string[];
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  requires_approval: boolean;
  timeout_seconds: number;
  rate_limit_per_minute: number;
  dry_run_supported: boolean;
  enabled: boolean;
  reason: string;
  status: string;
}

interface RegistryResponse {
  items: ToolDefinition[];
  total: number;
  kill_switch_safe: string[];
}

export default function ToolsPage() {
  const [query, setQuery] = useState("");
  const registry = useQuery({ queryKey: ["tools", "registry"], queryFn: () => api.get<RegistryResponse>("/tools/registry") });
  const tools = (registry.data?.items || []).filter((item) =>
    `${item.name} ${item.description} ${item.category}`.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <div className="space-y-5 pb-10">
      <PageHeader title="Tool Registry" description="Typed, timeout-bounded tools with declared schemas, permissions, risk and honest enablement reasons." />
      <Card>
        <div className="flex flex-wrap items-center gap-3 p-4">
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search tools, categories or descriptions" className="max-w-md" />
          <Badge tone="accent">{registry.data?.total ?? 0} registered</Badge>
          <Badge tone="success">kill-switch safe: {registry.data?.kill_switch_safe.join(", ") || "none"}</Badge>
          <Link href="/admin" className="ml-auto text-caption text-accent hover:underline">Admin controls →</Link>
        </div>
      </Card>
      {registry.isLoading && <Card><div className="p-6 text-body text-fgmuted">Loading tool registry…</div></Card>}
      {registry.isError && <Card><div className="p-6"><ErrorState message={registry.error.message} onRetry={() => void registry.refetch()} /></div></Card>}
      {tools.length === 0 && registry.data && <EmptyState title="No matching tools" description="Try a different search." />}
      <div className="grid gap-4 xl:grid-cols-2">
        {tools.map((tool) => (
          <Card key={tool.id}>
            <CardHeader
              title={tool.name}
              description={tool.description}
              action={<Badge tone={tool.enabled ? "success" : "warning"}>{tool.enabled ? "enabled" : "disabled"}</Badge>}
            />
            <div className="space-y-3 p-5 pt-0">
              <div className="flex flex-wrap gap-2 text-caption">
                <Badge tone={tool.risk === "high" ? "danger" : tool.risk === "medium" ? "warning" : "neutral"}>{tool.risk} risk</Badge>
                <Badge tone="accent">{tool.category}</Badge>
                {tool.requires_approval && <Badge tone="warning">approval required</Badge>}
                <Badge tone="neutral">{tool.timeout_seconds}s timeout</Badge>
                <Badge tone="neutral">{tool.rate_limit_per_minute}/min</Badge>
                {tool.dry_run_supported && <Badge tone="success">dry run</Badge>}
              </div>
              <p className="text-caption text-fgmuted">permissions: {tool.permissions.join(", ") || "none"}</p>
              <p className="text-caption text-fgmuted">status: {tool.status} · reason: {tool.reason}</p>
              <details className="rounded-md border border-edge bg-bg/50 p-3">
                <summary className="cursor-pointer text-caption font-semibold text-fg">Input schema</summary>
                <pre className="mt-2 max-h-48 overflow-auto text-[11px] text-fgmuted">{JSON.stringify(tool.input_schema, null, 2)}</pre>
              </details>
              <details className="rounded-md border border-edge bg-bg/50 p-3">
                <summary className="cursor-pointer text-caption font-semibold text-fg">Output schema</summary>
                <pre className="mt-2 max-h-48 overflow-auto text-[11px] text-fgmuted">{JSON.stringify(tool.output_schema, null, 2)}</pre>
              </details>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
